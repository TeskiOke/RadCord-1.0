"""
discovery.py — UDP broadcast peer discovery on the Radmin VPN network.

Every node broadcasts a "hello" packet every 5 seconds.
Nodes with matching network_id connect to each other via WebSocket.
"""
import asyncio
import json
import logging
import socket
from typing import Callable

from shared.protocol import (
    UDP_DISCOVERY_PORT, UDP_BROADCAST_ADDRS, UDP_INTERVAL, APP_VERSION
)

logger = logging.getLogger("discovery")


def get_local_ip() -> str:
    """Find Radmin VPN IP (26.x.x.x) or fall back to any local IP."""
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ip.startswith("26."):
                return ip
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class _DiscoveryReceiver(asyncio.DatagramProtocol):
    def __init__(self, config: dict, on_peer_found: Callable):
        self.config = config
        self.on_peer_found = on_peer_found

    def datagram_received(self, data: bytes, addr):
        try:
            msg = json.loads(data.decode())
            if msg.get("type") == "hello":
                
                # 1. Feed the GUI network scanner globally bypasses Windows port lock bug
                from core.network_scanner import NetworkScanner
                NetworkScanner.feed_packet(msg, addr[0])

                # 2. Check if this packet is for our already joined networks
                if msg.get("device_id") != self.config["profile"]["device_id"]:
                    my_nets = [n["id"] for n in self.config.get("networks", [])]
                    if msg.get("network_id") in my_nets:
                        self.on_peer_found(msg)

        except Exception:
            pass


    def error_received(self, exc):
        logger.debug(f"Discovery recv error: {exc}")


class PeerDiscovery:
    def __init__(self, config: dict, on_peer_found: Callable):
        self.config = config
        self.on_peer_found = on_peer_found
        self._running = False
        self._recv_transport = None
        self._stop_event = asyncio.Event()

    async def start(self):
        self._running = True
        loop = asyncio.get_event_loop()

        # --- Receive socket ---
        recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            recv_sock.bind(("", UDP_DISCOVERY_PORT))
        except OSError as e:
            logger.warning(f"Cannot bind UDP discovery port: {e}")
            recv_sock.close()
            return

        transport, _ = await loop.create_datagram_endpoint(
            lambda: _DiscoveryReceiver(self.config, self.on_peer_found),
            sock=recv_sock,
        )
        self._recv_transport = transport

        # --- Send socket (broadcast) ---
        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        send_sock.setblocking(False)

        my_ip = get_local_ip()
        logger.info(f"Local IP detected: {my_ip}")

        try:
            while self._running:
                my_ip = get_local_ip()
                my_nets = self.config.get("networks", [])
                
                for net in my_nets:
                    hello = json.dumps({
                        "type": "hello",
                        "device_id": self.config["profile"]["device_id"],
                        "nickname": self.config["profile"]["nickname"],
                        "avatar_color": self.config["profile"].get("avatar_color", "#7289da"),
                        "network_id": net["id"],
                        "network_name": net.get("name", ""),
                        "ip": my_ip,
                        "ws_port": 8765,
                        "version": APP_VERSION,
                    }).encode()

                    for addr in UDP_BROADCAST_ADDRS:
                        try:
                            send_sock.sendto(hello, (addr, UDP_DISCOVERY_PORT))
                        except Exception: pass

                    # Local loopback broadcast for same-PC instances
                    try:
                        send_sock.sendto(hello, ("127.255.255.255", UDP_DISCOVERY_PORT))
                    except Exception: pass

                    # Also broadcast on local subnet for any detected IP
                    if my_ip != "127.0.0.1":
                        parts = my_ip.split(".")
                        if len(parts) == 4:
                            subnet_bc = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
                            try:
                                send_sock.sendto(hello, (subnet_bc, UDP_DISCOVERY_PORT))
                            except Exception: pass



                # wait for interval or until stopped
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=UDP_INTERVAL)
                except asyncio.TimeoutError:
                    pass
        finally:
            send_sock.close()

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._recv_transport:
            self._recv_transport.close()
