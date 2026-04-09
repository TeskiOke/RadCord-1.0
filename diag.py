import socket
import json
import time
import threading

UDP_PORT = 8766

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except:
        return "127.0.0.1"

def listen_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", UDP_PORT))
    print(f"[+] Listening for UDP packets on port {UDP_PORT}...")
    
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            msg = json.loads(data.decode('utf-8', 'ignore'))
            if msg.get("type") == "hello":
                name = msg.get("network_name", "Unknown")
                nick = msg.get("nickname", "Unknown")
                ip = msg.get("ip", addr[0])
                print(f"[!] FOUND NETWORK: '{name}' (hosted by {nick} at {ip}) - Raw: {addr}")
        except Exception as e:
            pass

def broadcast_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    
    my_ip = get_local_ip()
    print(f"[+] My detected IP: {my_ip}")
    
    hello = json.dumps({
        "type": "hello",
        "device_id": "diag-test-1234",
        "nickname": "TestUser",
        "network_id": "testnet-01",
        "network_name": "Diagnostic Network",
        "ip": my_ip
    }).encode()
    
    while True:
        targets = ["255.255.255.255", "26.255.255.255", "127.255.255.255"]
        
        if my_ip != "127.0.0.1":
            parts = my_ip.split(".")
            targets.append(f"{parts[0]}.{parts[1]}.{parts[2]}.255")
            
        for t in set(targets):
            try:
                sock.sendto(hello, (t, UDP_PORT))
            except:
                pass
        
        time.sleep(2)

if __name__ == "__main__":
    print("=== RADCORD NETWORK DIAGNOSTIC TOOL ===")
    threading.Thread(target=listen_loop, daemon=True).start()
    broadcast_loop()
