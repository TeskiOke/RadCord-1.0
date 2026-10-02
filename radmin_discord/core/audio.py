"""
audio.py — Microphone capture + multi-peer audio mixing and playback.

Architecture:
  - InputStream callback  → pushes raw PCM chunks to _capture_queue
  - _capture_task (async) → reads queue, does VAD, sends via mesh
  - on_peer_audio()       → called by mesh on incoming binary audio frames
  - OutputStream callback → pops from per-peer jitter queues, mixes, outputs
"""
import asyncio
import logging
import queue
import threading
from typing import Callable, Dict, Optional, Set

import numpy as np
import sounddevice as sd

from shared.protocol import (
    AUDIO_SAMPLE_RATE, AUDIO_CHANNELS, AUDIO_DTYPE,
    AUDIO_CHUNK_FRAMES, AUDIO_RMS_THRESHOLD,
)

logger = logging.getLogger("audio")

_JITTER_MAX = 8   # max queued chunks per peer before dropping old ones


class AudioManager:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

        # State flags
        self._in_voice = False
        self._muted = False
        self._deafened = False
        self._speaking = False
        self._running = False

        # Capture pipeline
        self._capture_queue: queue.Queue = queue.Queue(maxsize=40)
        self._capture_task: Optional[asyncio.Task] = None

        # Playback pipeline: per-peer jitter buffer
        self._peer_queues: Dict[str, queue.Queue] = {}
        self._volumes: Dict[str, float] = {}   # device_id -> volume multiplier
        self._local_mutes: Set[str] = set()    # device_id (local mute)

        # Screen Stream Playback pipeline
        self._stream_queues: Dict[str, queue.Queue] = {}
        self._stream_volumes: Dict[str, float] = {}  # device_id -> volume multiplier (stream)

        self._master_volume = 1.0              # global multiplier
        self._peers_volume = 1.0               # global peer multiplier
        self._peer_lock = threading.Lock()

        # System Capture (for our own stream)
        self._system_capture_proc: Optional[asyncio.subprocess.Process] = None
        self.on_stream_audio_ready: Optional[Callable] = None

        # sounddevice streams
        self._in_stream: Optional[sd.InputStream] = None
        self._out_stream: Optional[sd.OutputStream] = None

        # Async callbacks (coroutine functions)
        self.on_audio_frame:   Optional[Callable] = None   # async (bytes) -> None
        self.on_speaking_change: Optional[Callable] = None  # async (bool) -> None
        self.on_rms_level:     Optional[Callable] = None   # (float) -> None

        # Mic Test State
        self._mic_test_active = False
        self._mic_test_queue: queue.Queue = queue.Queue(maxsize=10)
        self.vad_threshold = AUDIO_RMS_THRESHOLD

        # Selected devices (None = system default)
        self.device_in:  Optional[int] = None
        self.device_out: Optional[int] = None

        # Envelope gains for smooth fade-in / fade-out
        self._envelope_gain: float = 0.0   # current gain (0.0 to 1.0)
        self._hold_counter:  int = 0       # frames to hold after signal below threshold
        self._fade_release:  float = 0.92  # multiplier for exponential decay (~0.04 - 0.08 range)



    # Lifecycle

    def start_streams(self):
        """Open audio I/O streams (call from any thread)."""
        self._running = True
        try:
            in_kwargs = dict(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=AUDIO_CHANNELS,
                dtype=AUDIO_DTYPE,
                blocksize=AUDIO_CHUNK_FRAMES,
                callback=self._input_callback,
            )
            out_kwargs = dict(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=AUDIO_CHANNELS,
                dtype=AUDIO_DTYPE,
                blocksize=AUDIO_CHUNK_FRAMES,
                callback=self._output_callback,
            )
            if self.device_in is not None:
                in_kwargs["device"] = self.device_in
            if self.device_out is not None:
                out_kwargs["device"] = self.device_out

            self._in_stream  = sd.InputStream(**in_kwargs)
            self._out_stream = sd.OutputStream(**out_kwargs)
            self._in_stream.start()
            self._out_stream.start()
            in_name  = sd.query_devices(self.device_in)["name"]  if self.device_in  is not None else "default"
            out_name = sd.query_devices(self.device_out)["name"] if self.device_out is not None else "default"
            logger.info(f"Audio streams started — mic: {in_name!r}  speaker: {out_name!r}")
        except Exception as e:
            logger.error(f"Failed to start audio streams: {e}")

    def stop_streams(self):
        """Close audio streams."""
        self._running = False
        for stream in (self._in_stream, self._out_stream):
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        self._in_stream = None
        self._out_stream = None

    def set_master_volume(self, value: float):
        self._master_volume = value

    def set_peers_volume(self, value: float):
        self._peers_volume = value

    def set_ui_volume(self, value: float):
        self._ui_volume = value

    def start_capture_task(self):
        """Start the async VAD+send task (call inside asyncio loop)."""
        self._capture_task = asyncio.ensure_future(self._capture_loop())

    def stop_capture_task(self):
        if self._capture_task:
            self._capture_task.cancel()
            self._capture_task = None

    # sounddevice callbacks (real-time audio thread, keep fast!)

    def _input_callback(self, indata, frames, time_info, status):
        # Always calculate RMS for meter if requested
        rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
        if self.on_rms_level:
            try:
                self.on_rms_level(rms)
            except RuntimeError:
                # Occurs if Qt Signal source gets deleted before unset
                self.on_rms_level = None
            except Exception:
                pass


        if self._mic_test_active:
            # Check threshold
            if rms > self.vad_threshold:
                self._hold_counter = 20 # Hold for ~400ms
            
            # If we are in signal or in 'tail' period, queue the frame
            if rms > self.vad_threshold or self._hold_counter > 0:
                try:
                    self._mic_test_queue.put_nowait(indata[:, 0].copy())
                except queue.Full:
                    pass
                if rms <= self.vad_threshold:
                    self._hold_counter -= 1

        if not self._in_voice or self._muted:
            return

        # Same logic for transmission capture
        if rms > self.vad_threshold:
            self._capture_hold = 20
        
        if rms > self.vad_threshold or getattr(self, "_capture_hold", 0) > 0:
            try:
                self._capture_queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass
            if rms <= self.vad_threshold:
                self._capture_hold -= 1


    def _output_callback(self, outdata, frames, time_info, status):
        mixed = np.zeros(frames, dtype=np.int32)
        
        # Add mic test loopback with funnel fade
        if self._mic_test_active:
            try:
                chunk = self._mic_test_queue.get_nowait()
                # Always approach target gain 1.0 if we have samples
                self._envelope_gain = min(1.0, self._envelope_gain + 0.25)
                mixed += (chunk.astype(np.float32) * self._envelope_gain).astype(np.int32)
            except queue.Empty:
                if self._envelope_gain > 0.001:
                    # Funnel effect: exponential decay
                    self._envelope_gain *= self._fade_release
                    if self._envelope_gain < 0.001: self._envelope_gain = 0.0

        if not self._deafened:
            with self._peer_lock:
                # 2. Voices
                if self._in_voice:
                    for did, q in self._peer_queues.items():
                        if did in self._local_mutes:
                            continue
                        try:
                            chunk: np.ndarray = q.get_nowait()
                            if len(chunk) == frames:
                                # Peer individual volume * Global peers volume
                                v = self._volumes.get(did, 1.0) * self._peers_volume
                                if v != 1.0:
                                    chunk = (chunk * v).astype(np.int32)
                                mixed += chunk.astype(np.int32)
                        except queue.Empty:
                            pass
                
                # 3. Screen Streams (mixed even if not in voice, if unmuted)
                for did, q in self._stream_queues.items():
                    try:
                        chunk: np.ndarray = q.get_nowait()
                        # Stream volume: 0.0 (muted) by default, up to 2.0
                        vol = self._stream_volumes.get(did, 0.0)
                        if vol > 0.001:
                            if len(chunk) == frames:
                                if vol != 1.0:
                                    chunk = (chunk * vol).astype(np.int32)
                                mixed += chunk.astype(np.int32)
                    except queue.Empty:
                        pass


        # Apply master volume
        if self._master_volume != 1.0:
            mixed = (mixed * self._master_volume).astype(np.int32)


        clipped = np.clip(mixed, -32768, 32767).astype(np.int16)
        outdata[:, 0] = clipped


    # Async capture loop (VAD + send)

    async def _capture_loop(self):
        while self._running:
            await asyncio.sleep(0.005)
            if not self._in_voice or self._muted:
                # Drain queue silently
                while not self._capture_queue.empty():
                    try:
                        self._capture_queue.get_nowait()
                    except queue.Empty:
                        break
                continue

            chunks = []
            while not self._capture_queue.empty():
                try:
                    chunks.append(self._capture_queue.get_nowait())
                except queue.Empty:
                    break

            for chunk in chunks:
                rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                is_active = rms > self.vad_threshold
                
                # Update speaking state (with hysteresis for UI)
                if is_active:
                    self._ui_hold = 15
                    if not self._speaking:
                        self._speaking = True
                        if self.on_speaking_change:
                            asyncio.ensure_future(self.on_speaking_change(True))
                else:
                    self._ui_hold = getattr(self, "_ui_hold", 0) - 1
                    if self._ui_hold <= 0 and self._speaking:
                        self._speaking = False
                        if self.on_speaking_change:
                            asyncio.ensure_future(self.on_speaking_change(False))

                # Amplitude Envelope (the actual "funnel" for transmission)
                if is_active:
                    self._trans_gain = min(1.0, getattr(self, "_trans_gain", 0.0) + 0.3)
                else:
                    self._trans_gain = getattr(self, "_trans_gain", 0.0) * self._fade_release
                
                if self._trans_gain > 0.001:
                    faded = (chunk.astype(np.float32) * self._trans_gain)
                    audio_bytes = np.clip(faded, -32768, 32767).astype(np.int16).tobytes()
                    asyncio.ensure_future(self.on_audio_frame(audio_bytes))

    # System Audio Capture Management (Helper Process)

    async def start_system_audio(self, pid: int, mode: int = 1):
        """Start the C# helper to capture audio of a process or exclude our app."""
        await self.stop_system_audio()
        
        import os
        helper_path = os.path.join(os.path.dirname(__file__), "audio_helper.exe")
        if not os.path.exists(helper_path):
            logger.error("Audio helper EXE not found")
            return

        try:
            self._system_capture_proc = await asyncio.create_subprocess_exec(
                helper_path, str(pid), str(mode),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            asyncio.ensure_future(self._read_system_audio())
            logger.info(f"System audio capture started for PID {pid} (Mode {mode})")
        except Exception as e:
            logger.error(f"Failed to start audio helper: {e}")

    async def stop_system_audio(self):
        if self._system_capture_proc:
            try:
                self._system_capture_proc.terminate()
                await self._system_capture_proc.wait()
            except Exception:
                pass
            self._system_capture_proc = None

    async def _read_system_audio(self):
        while self._system_capture_proc:
            try:
                # 48000 Hz, 16-bit Mono, chunk size 960 frames = 1920 bytes
                chunk_bytes = await self._system_capture_proc.stdout.readexactly(1920)
                if self.on_stream_audio_ready:
                    asyncio.ensure_future(self.on_stream_audio_ready(chunk_bytes))
            except asyncio.IncompleteReadError:
                break
            except Exception as e:
                logger.error(f"Read system audio error: {e}")
                break
        self._system_capture_proc = None

    # Stream Playback controls

    def receive_peer_stream_audio(self, device_id: str, audio_bytes: bytes):
        """Thread-safe. Push incoming stream audio into the peer's stream jitter buffer."""
        chunk = np.frombuffer(audio_bytes, dtype=np.int16)
        if len(chunk) != AUDIO_CHUNK_FRAMES:
            return
        with self._peer_lock:
            if device_id not in self._stream_queues:
                self._stream_queues[device_id] = queue.Queue(maxsize=_JITTER_MAX)
            q = self._stream_queues[device_id]
        try:
            q.put_nowait(chunk)
        except queue.Full:
            try:
                q.get_nowait()
                q.put_nowait(chunk)
            except queue.Empty:
                pass

    def set_peer_stream_volume(self, device_id: str, volume: float):
        """Set volume multiplier for peer's screen stream (0.0 to 2.0)."""
        with self._peer_lock:
            self._stream_volumes[device_id] = max(0.0, volume)

    def get_peer_stream_volume(self, device_id: str) -> float:
        with self._peer_lock:
            # Default to 0.0 (muted) as requested: "initially sound not enabled"
            return self._stream_volumes.get(device_id, 0.0)

    # Called from mesh when audio frame arrives from a peer

    def receive_peer_audio(self, device_id: str, audio_bytes: bytes):
        """Thread-safe. Called from asyncio but output callback is real-time."""
        chunk = np.frombuffer(audio_bytes, dtype=np.int16)
        if len(chunk) != AUDIO_CHUNK_FRAMES:
            return
        with self._peer_lock:
            if device_id not in self._peer_queues:
                self._peer_queues[device_id] = queue.Queue(maxsize=_JITTER_MAX)
            q = self._peer_queues[device_id]
        try:
            q.put_nowait(chunk)
        except queue.Full:
            # Drop oldest, add newest
            try:
                q.get_nowait()
                q.put_nowait(chunk)
            except queue.Empty:
                pass

    def remove_peer(self, device_id: str):
        with self._peer_lock:
            self._peer_queues.pop(device_id, None)
            self._volumes.pop(device_id, None)

    def set_peer_volume(self, device_id: str, volume: float):
        """Set volume multiplier for peer (0.0 to 2.0)."""
        with self._peer_lock:
            self._volumes[device_id] = max(0.0, volume)

    def get_peer_volume(self, device_id: str) -> float:
        """Get current volume multiplier for peer."""
        with self._peer_lock:
            return self._volumes.get(device_id, 1.0)

    def set_peer_local_mute(self, device_id: str, muted: bool):
        """Mute peer ONLY for the local user."""
        with self._peer_lock:
            if muted:
                self._local_mutes.add(device_id)
            else:
                self._local_mutes.discard(device_id)

    def is_peer_locally_muted(self, device_id: str) -> bool:
        with self._peer_lock:
            return device_id in self._local_mutes

    # Properties

    @property
    def in_voice(self) -> bool:
        return self._in_voice

    @in_voice.setter
    def in_voice(self, value: bool):
        self._in_voice = value
        if not value:
            self._speaking = False

    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, value: bool):
        self._muted = value

    @property
    def deafened(self) -> bool:
        return self._deafened

    @deafened.setter
    def deafened(self, value: bool):
        self._deafened = value

    @property
    def mic_test_active(self) -> bool:
        return self._mic_test_active

    @mic_test_active.setter
    def mic_test_active(self, value: bool):
        self._mic_test_active = value
        if not value:
            # Drain queue
            while not self._mic_test_queue.empty():
                self._mic_test_queue.get_nowait()


    @property
    def speaking(self) -> bool:
        return self._speaking
