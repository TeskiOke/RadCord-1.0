"""
identity.py — Device ID (MAC-based) + local config management
"""
import uuid
import hashlib
import json
import random
from pathlib import Path

from shared.protocol import AVATAR_COLORS

CONFIG_PATH = Path("config.json")


def get_device_id() -> str:
    """Deterministic unique ID based on random UUID."""
    return uuid.uuid4().hex[:16]


def make_network_id(network_name: str, password: str) -> str:
    """SHA-256 hash used to filter peers — only matching hashes can connect."""
    raw = f"{network_name.strip().lower()}:{password}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def load_config() -> dict | None:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                # Migration: if no "profile" key, it's an old config
                if "profile" not in cfg:
                    return None
                return cfg
        except Exception:
            return None
    return None


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def create_profile(nickname: str, theme: str = "dark", app_color: str = "#7289da", avatar_color: str = None) -> dict:
    """Initial one-time registration of the user's profile."""
    config = {
        "profile": {
            "nickname": nickname.strip(),
            "avatar_color": avatar_color if avatar_color else random.choice(AVATAR_COLORS),
            "device_id": get_device_id(),
            "theme": theme,
            "app_color": app_color,
            "audio_input_device": None,
            "audio_output_device": None,
        },
        "networks": []
    }
    save_config(config)
    return config


def add_network(config: dict, name: str, password: str) -> dict:
    net_id = make_network_id(name, password)
    # Duplicate name check
    nn = name.strip().lower()
    if any(n["name"].lower() == nn for n in config["networks"]):
        return config


    config["networks"].append({
        "name": name.strip(),
        "password": password,
        "id": net_id,
        "voice_channels": ["Голосовой"]
    })

    save_config(config)
    return config


def remove_network(config: dict, net_id: str) -> dict:
    config["networks"] = [n for n in config["networks"] if n["id"] != net_id]
    save_config(config)
    return config


def add_voice_channel_to_config(config: dict, net_id: str, channel_name: str) -> dict:
    for n in config["networks"]:
        if n["id"] == net_id:
            if "voice_channels" not in n: n["voice_channels"] = ["Голосовой"]
            if channel_name not in n["voice_channels"]:
                n["voice_channels"].append(channel_name)
            break
    save_config(config)
    return config


def remove_voice_channel_from_config(config: dict, net_id: str, channel_name: str) -> dict:
    if channel_name == "Голосовой": return config
    for n in config["networks"]:
        if n["id"] == net_id:
            if "voice_channels" in n and channel_name in n["voice_channels"]:
                n["voice_channels"].remove(channel_name)
            break
    save_config(config)
    return config


