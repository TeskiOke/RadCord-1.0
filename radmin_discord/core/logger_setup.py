import logging
import os
import datetime
from collections import deque

# Global buffer to store logs for the UI
LOG_BUFFER = deque(maxlen=1000)

class BufferHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        LOG_BUFFER.append(msg)

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Format
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")

    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Buffer (for UI)
    bh = BufferHandler()
    bh.setFormatter(fmt)
    logger.addHandler(bh)

    # File handler
    if not os.path.exists("logs"):
        os.makedirs("logs")
    
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fh = logging.FileHandler(f"logs/analog_ds_{now}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

def get_logs() -> str:
    return "\n".join(LOG_BUFFER)
