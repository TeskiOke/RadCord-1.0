"""
network_scanner.py — Brief UDP scan to find all RadCord networks nearby.

Usage:
    scanner = NetworkScanner()
    networks = await scanner.scan(duration=4.0)
    # networks = [{"name": "Моя банда", "network_id": "abc..", "users": ["alice", "bob"], "ips": [...]}]
"""
import asyncio
import json
import logging
import socket
from typing import Dict, List

from shared.protocol import UDP_DISCOVERY_PORT

logger = logging.getLogger("scanner")


class NetworkScanner:
    """Listen for ALL UDP hello packets (ignoring network_id filter)."""
    _cached_networks: dict = {}

    @classmethod
    def feed_packet(cls, msg: dict, ip: str):
        if msg.get("type") != "hello": return
        nid = msg.get("network_id", "")
        if not nid: return
        
        name = msg.get("network_name", "Неизвестная сеть")
        nick = msg.get("nickname", "?")
        
        if nid not in cls._cached_networks:
            cls._cached_networks[nid] = {"name": name, "network_id": nid, "users": [], "ips": []}
        entry = cls._cached_networks[nid]
        if nick not in entry["users"]: entry["users"].append(nick)
        if ip and ip not in entry["ips"]: entry["ips"].append(ip)

    async def scan(self, duration: float = 4.0) -> List[dict]:
        loop = asyncio.get_event_loop()
        
        # Clear cache before scan
        NetworkScanner._cached_networks.clear()

        # Try to run an actual UDP socket (for SetupDialog when nothing is running)
        class ScanProtocol(asyncio.DatagramProtocol):
            def connection_made(self, transport): pass
            def connection_lost(self, exc): pass
            def datagram_received(self, data, addr):
                try:
                    msg = json.loads(data.decode())
                    NetworkScanner.feed_packet(msg, addr[0])
                except: pass

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        transport = None
        
        try:
            sock.bind(("", UDP_DISCOVERY_PORT))
            transport, _ = await loop.create_datagram_endpoint(ScanProtocol, sock=sock)
        except OSError as e:
            # If we fail to bind, it's fine, PeerDiscovery is probably running and will feed us
            sock.close()

        # Wait to collect packets from either this socket or PeerDiscovery feeding us
        await asyncio.sleep(duration)
        
        if transport:
            transport.close()

        return sorted(NetworkScanner._cached_networks.values(), key=lambda n: -len(n["users"]))

