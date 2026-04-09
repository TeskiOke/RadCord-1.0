"""
message_cache.py — Persist last N chat messages to disk (per channel).
Loaded on app startup so users see recent history.
"""
import json
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger("cache")

MAX_MESSAGES = 150
CACHE_DIR = Path("cache")


def _get_path(network_id: str, channel: str) -> Path:
    safe_id = "".join(c for c in network_id if c.isalnum())[:16]
    return CACHE_DIR / f"net_{safe_id}_{channel}.json"


def load_messages(network_id: str, channel: str) -> List[dict]:
    if not network_id:
        return []
    path = _get_path(network_id, channel)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Cache load error [{channel}]: {e}")
    return []


def save_message(network_id: str, channel: str, msg: dict):
    """Append message to cache, keep last MAX_MESSAGES."""
    if not network_id:
        return
    # Don't cache system messages
    if msg.get("from") == "__system__":
        return
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        messages = load_messages(network_id, channel)

        # Dedup by msg_id
        if msg.get("msg_id"):
            ids = {m.get("msg_id") for m in messages}
            if msg["msg_id"] in ids:
                return

        messages.append(msg)
        if len(messages) > MAX_MESSAGES:
            messages = messages[-MAX_MESSAGES:]

        path = _get_path(network_id, channel)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Cache save error [{channel}]: {e}")


def clear_network_cache(network_id: str):
    """Remove all cache files associated with a network."""
    safe_id = "".join(c for c in network_id if c.isalnum())[:16]
    pattern = f"net_{safe_id}_*.json"
    for p in CACHE_DIR.glob(pattern):
        try:
            p.unlink()
        except Exception:
            pass

