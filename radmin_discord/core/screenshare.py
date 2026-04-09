"""
screenshare.py — Screen/window capture with configurable quality, FPS, and source.

Source dict (from ScreenPickerDialog):
    {"type": "monitor", "monitor_index": 1, "width": 1280, "height": 720,
     "jpeg_quality": 65, "fps": 30}
    {"type": "window", "hwnd": 12345, "rect": (x,y,x2,y2), "width": ..., ...}
"""
import asyncio
import io
import logging
import threading
import time
from typing import Callable, Optional

from PIL import Image

logger = logging.getLogger("screenshare")

_DEFAULTS = {
    "type": "monitor",
    "monitor_index": 1,
    "width": 1280,
    "height": 720,
    "jpeg_quality": 65,
    "fps": 24,
}


class ScreenCapture:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._source: dict = dict(_DEFAULTS)
        self.on_frame: Optional[Callable] = None   # async (bytes) -> None

    def configure(self, source: dict):
        """Update source config. Can be called before or during capture."""
        self._source = {**_DEFAULTS, **source}

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop_fn, daemon=True)
        self._thread.start()
        logger.info(f"Screen capture started: {self._source}")

    def stop(self):
        self._running = False

    # ─────────────────────────────────────────────────────────────────────────

    def _loop_fn(self):
        src = self._source
        fps      = max(1, src.get("fps", 24))
        interval = 1.0 / fps
        w        = src.get("width",  1280)
        h        = src.get("height", 720)
        quality  = src.get("jpeg_quality", 65)

        if src.get("type") == "window":
            self._run_window_capture(src, interval, w, h, quality)
        else:
            self._run_monitor_capture(src, interval, w, h, quality)

    def _run_monitor_capture(self, src, interval, w, h, quality):
        try:
            import mss
        except ImportError:
            logger.error("mss not installed")
            return

        with mss.mss() as sct:
            idx = src.get("monitor_index", 1)
            monitors = sct.monitors
            if idx >= len(monitors):
                idx = 1
            monitor = monitors[idx]

            while self._running:
                t0 = time.monotonic()
                try:
                    raw = sct.grab(monitor)
                    # Get scale factors (raw grab is at full resolution)
                    scale_x = w / raw.width
                    scale_y = h / raw.height
                    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                    img = img.resize((w, h), Image.Resampling.BILINEAR)
                    # Draw cursor scaled to resized image
                    mon_x = monitor.get("left", 0)
                    mon_y = monitor.get("top", 0)
                    self._draw_cursor_scaled(img, mon_x, mon_y, scale_x, scale_y)
                    frame = self._encode(img, quality)
                    if self.on_frame and self._running:
                        asyncio.run_coroutine_threadsafe(
                            self.on_frame(frame), self._loop
                        )
                except Exception as e:
                    logger.error(f"Monitor capture: {e}")

                elapsed = time.monotonic() - t0
                sleep = max(0.0, interval - elapsed)
                if sleep:
                    time.sleep(sleep)

    def _run_window_capture(self, src, interval, w, h, quality):
        rect = src.get("rect")
        if not rect:
            logger.error("Window capture: no rect provided")
            return

        from PIL import ImageGrab

        while self._running:
            t0 = time.monotonic()
            try:
                img = ImageGrab.grab(bbox=rect, all_screens=True)
                if img.width < 2 or img.height < 2:
                    raise ValueError("Empty window")
                orig_w, orig_h = img.size
                img = img.resize((w, h), Image.Resampling.BILINEAR)
                scale_x = w / orig_w
                scale_y = h / orig_h
                self._draw_cursor_scaled(img, rect[0], rect[1], scale_x, scale_y)
                frame = self._encode(img, quality)
                if self.on_frame and self._running:
                    asyncio.run_coroutine_threadsafe(
                        self.on_frame(frame), self._loop
                    )
            except Exception as e:
                logger.error(f"Window capture: {e}")

            elapsed = time.monotonic() - t0
            sleep = max(0.0, interval - elapsed)
            if sleep:
                time.sleep(sleep)

    @staticmethod
    def _encode(img: Image.Image, quality: int) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()

    @staticmethod
    def _draw_cursor_scaled(img: Image.Image, offset_x: int, offset_y: int, scale_x: float, scale_y: float):
        """Paint the current Windows cursor onto a PIL image scaled correctly."""
        try:
            import ctypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            class CURSORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint32),
                    ("flags", ctypes.c_uint32),
                    ("hCursor", ctypes.c_void_p),
                    ("ptScreenPos", POINT),
                ]

            ci = CURSORINFO()
            ci.cbSize = ctypes.sizeof(CURSORINFO)
            if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(ci)):
                return
            if ci.flags != 1:  # CURSOR_SHOWING = 1
                return

            # Map screen coords to image coords
            cx = int((ci.ptScreenPos.x - offset_x) * scale_x)
            cy = int((ci.ptScreenPos.y - offset_y) * scale_y)

            if cx < 0 or cy < 0 or cx >= img.width or cy >= img.height:
                return  # Cursor outside capture area

            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            r = 7
            # White filled circle with black outline = clear cross-platform cursor
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill="white", outline="black", width=2)
            # Inner dot
            draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill="black")
        except Exception:
            pass  # Cursor drawing is best-effort
