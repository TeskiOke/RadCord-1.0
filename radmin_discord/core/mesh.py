"""
mesh.py — P2P WebSocket mesh network.

Each node:
  - Runs a WS server (accepts incoming connections)
  - Connects outward to every discovered peer
  - Deduplicates broadcast messages by msg_id
"""
import asyncio
import json
import logging
import uuid
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed

from shared.protocol import WS_PORT, MSG_IDENTIFY, BIN_AUDIO, BIN_SCREEN, BIN_STREAM_AUDIO

logger = logging.getLogger("mesh")


@dataclass
class Peer:
    device_id: str
    nickname: str
    avatar_color: str
    ip: str
    ws: object                # websockets connection
    network_ids: Set[str] = field(default_factory=set)
    voice_channel: str = ""
    in_voice: bool = False
    is_speaking: bool = False
    muted: bool = False
    deafened: bool = False
    is_sharing: bool = False
    ping: int = 0
    _ping_sent_at: float = 0





class MeshNetwork:
    def __init__(self, config: dict, loop: asyncio.AbstractEventLoop):
        self.config = config
        self.device_id: str = config["device_id"]
        self._loop = loop

        self.peers: Dict[str, Peer] = {}          # device_id -> Peer
        self._connecting: Set[str] = set()         # IPs currently being dialed


        # Deduplication ring-buffer
        self._seen_ids: Set[str] = set()
        self._seen_queue: deque = deque(maxlen=2000)

        self.on_peer_join:          Optional[Callable[[Peer], None]] = None
        self.on_peer_leave:         Optional[Callable[[Peer], None]] = None
        self.on_text_message:       Optional[Callable[[Peer, dict], None]] = None
        self.on_voice_frame:        Optional[Callable[[Peer, bytes], None]] = None
        self.on_screen_frame:       Optional[Callable[[Peer, bytes], None]] = None
        self.on_voice_state:        Optional[Callable[[Peer], None]] = None
        self.on_screen_state_change:Optional[Callable[[Peer], None]] = None
        self.on_stream_audio_frame: Optional[Callable[[Peer, bytes], None]] = None

    # Public start

    async def start_server(self):
        """Start WS server and run forever."""
        self._stop_event = asyncio.Event()
        asyncio.ensure_future(self._ping_loop())
        
        async with websockets.serve(self._handle_incoming, "0.0.0.0", WS_PORT,
                                    ping_interval=20, ping_timeout=20):
            logger.info(f"WS server listening on port {WS_PORT}")
            await self._stop_event.wait()

    async def _ping_loop(self):
        while hasattr(self, "_stop_event") and not self._stop_event.is_set():
            t = time.monotonic()
            for peer in list(self.peers.values()):
                peer._ping_sent_at = t
                asyncio.ensure_future(self._send_to(peer, {"type": "ping"}))
            await asyncio.sleep(5.0)

            
    def stop(self):
        """Signal the WS server to close gracefully."""
        if hasattr(self, "_stop_event"):
            logger.info("Graceful stop triggered")
            self._loop.call_soon_threadsafe(self._stop_event.set)



    # Called by discovery when a new peer IP appears
    def peer_discovered(self, info: dict):
        ip = info.get("ip", "")
        if not ip:
            return
        # Only connect if we share a network with this peer
        their_net = info.get("network_id", "")
        my_nets = self.config.get("_network_ids", [])
        if their_net and my_nets and their_net not in my_nets:
            return  # Different network entirely — ignore
        asyncio.ensure_future(self._connect_to(ip, info.get("ws_port", WS_PORT)))

    # Outgoing connection

    async def _connect_to(self, ip: str, port: int):
        # Already connected or connecting?
        if ip in self._connecting:
            return
        for p in self.peers.values():
            if p.ip == ip:
                return

        self._connecting.add(ip)
        try:
            uri = f"ws://{ip}:{port}"
            ws = await asyncio.wait_for(
                websockets.connect(uri, ping_interval=20, ping_timeout=20),
                timeout=5.0,
            )
            # Send our identity first
            await ws.send(self._identity_json())
            # Wait for their identity
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            msg = json.loads(raw)
            if not self._valid_identity(msg):
                await ws.close()
                return

            # Determine all shared networks this peer belongs to
            peer_net_ids = set(msg.get("network_ids", []))
            my_net_ids = set(self.config.get("_network_ids", []))
            shared_nets = peer_net_ids.intersection(my_net_ids)
            
            # If no shared networks in list, fall back to the one-off ID if provided
            if not shared_nets and msg.get("network_id"):
                shared_nets.add(msg["network_id"])
            # If still empty — accept all peer's networks (timing race on startup)
            if not shared_nets:
                shared_nets = peer_net_ids

            peer = Peer(
                device_id=msg["device_id"],
                nickname=msg["nickname"],
                avatar_color=msg.get("avatar_color", "#7289da"),
                ip=ip,
                ws=ws,
                network_ids=shared_nets,
            )
            await self._register_peer(peer)

            asyncio.ensure_future(self._handle_peer(peer))

        except Exception as e:
            logger.error(f"Connect to {ip} failed: {type(e).__name__}: {e}")
        finally:
            self._connecting.discard(ip)

    # Incoming connection handler (WS server callback)

    async def _handle_incoming(self, ws, path=""):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            msg = json.loads(raw)
            if not self._valid_identity(msg):
                await ws.close()
                return

            # Avoid duplicate if we're also connecting outward to the same peer
            if msg["device_id"] in self.peers:
                await ws.close()
                return

            # Reply with our identity
            await ws.send(self._identity_json())

            # Determine all shared networks this peer belongs to
            peer_net_ids = set(msg.get("network_ids", []))
            my_net_ids = set(self.config.get("_network_ids", []))
            shared_nets = peer_net_ids.intersection(my_net_ids)
            
            if not shared_nets and msg.get("network_id"):
                shared_nets.add(msg["network_id"])
            # If still empty — accept all peer's networks (timing race on startup)
            if not shared_nets:
                shared_nets = peer_net_ids

            ip = ws.remote_address[0] if ws.remote_address else "?"
            peer = Peer(
                device_id=msg["device_id"],
                nickname=msg["nickname"],
                avatar_color=msg.get("avatar_color", "#7289da"),
                ip=ip,
                ws=ws,
                network_ids=shared_nets,
            )
            await self._register_peer(peer)

            await self._handle_peer(peer)  # blocks until disconnect

        except Exception as e:
            logger.error(f"Incoming handler error: {type(e).__name__}: {e}")

    # Per-peer message loop

    async def _handle_peer(self, peer: Peer):
        try:
            async for message in peer.ws:
                try:
                    if isinstance(message, bytes):
                        self._handle_binary(peer, message)
                    else:
                        self._handle_json(peer, message)
                except Exception as e:
                    logger.error(f"Error processing message from {peer.nickname}: {e}")
                    # Continue loop, don't kill peer connection for one bad frame
        except (ConnectionClosed, Exception) as e:
            logger.debug(f"Peer {peer.nickname} disconnected: {e}")
        finally:
            self.peers.pop(peer.device_id, None)
            if self.on_peer_leave:
                self.on_peer_leave(peer)

    def _handle_json(self, peer: Peer, raw: str):
        try:
            msg = json.loads(raw)
        except Exception:
            return

        try:
            # Dedup by msg_id
            mid = msg.get("msg_id")
            if mid:
                if mid in self._seen_ids:
                    return
                self._seen_ids.add(mid)
                self._seen_queue.append(mid)
                # Clean stale ids when queue wraps (deque handles maxlen)
                if len(self._seen_ids) > 2200:
                    for _ in range(200):
                        try:
                            old = self._seen_queue.popleft()
                            self._seen_ids.discard(old)
                        except IndexError:
                            break

            t = msg.get("type")
            if t == "text":
                if self.on_text_message:
                    self.on_text_message(peer, msg)

            elif t == "voice_join":
                peer.in_voice = True
                peer.voice_channel = msg.get("channel", "Голосовой")
                if hasattr(self, "on_voice_state") and self.on_voice_state:
                    self.on_voice_state(peer)

            elif t == "voice_leave":
                peer.in_voice = False
                peer.voice_channel = ""
                if hasattr(self, "on_voice_state") and self.on_voice_state:
                    self.on_voice_state(peer)

            elif t == "voice_speaking":
                peer.is_speaking = msg.get("speaking", False)
                if hasattr(self, "on_voice_state") and self.on_voice_state:
                    self.on_voice_state(peer)

            elif t == "voice_state":
                peer.muted = msg.get("muted", False)
                peer.deafened = msg.get("deafened", False)
                if hasattr(self, "on_voice_state") and self.on_voice_state:
                    self.on_voice_state(peer)

            elif t == "screen_start":
                peer.is_sharing = True
                if self.on_screen_state_change:
                    self.on_screen_state_change(peer)

            elif t == "screen_stop":
                peer.is_sharing = False
                if self.on_screen_state_change:
                    self.on_screen_state_change(peer)

            elif t == "channel_add":
                from ui.signals import signals
                signals.voice_channel_added.emit(msg.get("name", "Новый канал"))

            elif t == "channel_remove":
                from ui.signals import signals
                signals.voice_channel_removed.emit(msg.get("name", ""))

            elif t == "ping":
                asyncio.ensure_future(self._send_to(peer, {"type": "pong"}))
            elif t == "pong":
                if peer._ping_sent_at > 0:
                    rtt = int((time.monotonic() - peer._ping_sent_at) * 1000)
                    peer.ping = rtt
                    from ui.signals import signals
                    signals.ping_updated.emit(peer.device_id, rtt)
        except Exception as e:
            logger.error(f"Error handling JSON message: {e}")
            return


    def _handle_binary(self, peer: Peer, data: bytes):
        if len(data) < 1:
            return
        frame_type = data[0]
        payload = data[1:]
        if frame_type == BIN_AUDIO and self.on_voice_frame:
            self.on_voice_frame(peer, payload)
        elif frame_type == BIN_SCREEN and self.on_screen_frame:
            self.on_screen_frame(peer, payload)
        elif frame_type == BIN_STREAM_AUDIO and self.on_stream_audio_frame:
            self.on_stream_audio_frame(peer, payload)

    # Send helpers

    async def _send_to(self, peer: Peer, msg: dict):
        try:
            await peer.ws.send(json.dumps(msg))
        except Exception:
            pass

    async def broadcast_binary(self, frame_type: int, payload: bytes, network_id: str = None):
        """Send a binary frame to all peers in the specified network."""
        data = bytes([frame_type]) + payload
        for peer in list(self.peers.values()):
            if network_id and peer.network_ids and network_id not in peer.network_ids:
                continue
            try:
                await peer.ws.send(data)
            except Exception:
                pass

    async def broadcast_json(self, msg: dict, network_id: str = None):

        if network_id:
            msg["network_id"] = network_id
        
        if "msg_id" not in msg:
            msg["msg_id"] = str(uuid.uuid4())
        # Mark as seen so we don't echo ourselves
        self._seen_ids.add(msg["msg_id"])
        self._seen_queue.append(msg["msg_id"])
        
        data = json.dumps(msg)
        for peer in list(self.peers.values()):
            # Allow sending if peer.network_ids is empty (timing race fallback)
            if network_id and peer.network_ids and network_id not in peer.network_ids:
                continue
            try:
                await peer.ws.send(data)
            except Exception:
                pass


    async def broadcast_binary(self, frame_type: int, payload: bytes, network_id: str = None):
        data = bytes([frame_type]) + payload
        for peer in list(self.peers.values()):
            # Allow sending if peer.network_ids is empty (timing race fallback)
            if network_id and peer.network_ids and network_id not in peer.network_ids:
                continue
            try:
                await peer.ws.send(data)
            except Exception:
                pass


    async def broadcast_audio_to_voice(self, payload: bytes, network_id: str = None):
        """Send audio only to peers currently in the voice channel of the target network."""
        await self.broadcast_binary(BIN_AUDIO, payload, network_id)

    async def broadcast_stream_audio(self, payload: bytes, network_id: str = None):
        """Send stream audio to peers in the voice channel (or anyone watching)."""
        # For simplicity, we send to everyone in the same voice network/channel
        await self.broadcast_binary(BIN_STREAM_AUDIO, payload, network_id)


    # High-level actions

    async def send_text(self, channel: str, content: str, network_id: str) -> dict:
        msg = {
            "type": "text",
            "channel": channel,
            "content": content,
            "from": self.device_id,
            "nickname": self.config["nickname"],
            "avatar_color": self.config["avatar_color"],
            "ts": int(time.time()),
            "network_id": network_id
        }
        await self.broadcast_json(msg, network_id)
        return msg

    async def join_voice(self, channel_name: str, network_id: str):
        """Broadcast joining a voice channel."""
        await self.broadcast_json({"type": "voice_join", "channel": channel_name}, network_id)

    async def leave_voice(self, channel_name: str, network_id: str):
        await self.broadcast_json({"type": "voice_leave", "channel": channel_name}, network_id)


    async def add_voice_channel(self, name: str, network_id: str):
        await self.broadcast_json({"type": "channel_add", "name": name}, network_id)

    async def remove_voice_channel(self, name: str, network_id: str):
        await self.broadcast_json({"type": "channel_remove", "name": name}, network_id)

    async def set_speaking(self, speaking: bool, network_id: str):
        await self.broadcast_json({"type": "voice_speaking", "speaking": speaking}, network_id)

    async def start_screen_share(self, network_id: str):
        await self.broadcast_json({"type": "screen_start"}, network_id)

    async def stop_screen_share(self, network_id: str):
        await self.broadcast_json({"type": "screen_stop"}, network_id)



    # Internal helpers

    async def _register_peer(self, peer: Peer):
        if peer.device_id in self.peers:
            return
        self.peers[peer.device_id] = peer
        if self.on_peer_join:
            self.on_peer_join(peer)
        logger.info(f"+ Peer joined: {peer.nickname} ({peer.ip})")

    def _identity_dict(self) -> dict:
        return {
            "type": MSG_IDENTIFY,
            "device_id": self.config["device_id"],
            "nickname": self.config["nickname"],
            "avatar_color": self.config.get("avatar_color", "#7289da"),
            # Send full list of network IDs so receiver can match
            "network_ids": self.config.get("_network_ids", []),
        }

    def _identity_json(self) -> str:
        """Return serialized identity payload for the WS handshake."""
        return json.dumps(self._identity_dict())



    def _valid_identity(self, msg: dict) -> bool:
        # Accept any RadCord peer that has a different device_id.
        # Network-level filtering is done later at broadcast/voice level.
        return (
            msg.get("type") == MSG_IDENTIFY
            and bool(msg.get("device_id"))
            and msg.get("device_id") != self.device_id
        )
