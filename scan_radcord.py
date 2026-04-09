import socket
import json
from datetime import datetime

UDP_PORT = 8766

def listen():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Bind directly to all interfaces
    sock.bind(("", UDP_PORT))
    
    print("=" * 60)
    print(f"РАДАР RADCORD: СЛУШАЮ ЭФИР НА ПОРТУ {UDP_PORT}...")
    print("Включите RadCord, зайдите в любой канал/группу и подождите 5-10 секунд.")
    print("Если пакеты отправляются, они появятся здесь:")
    print("=" * 60)
    
    found = 0
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            msg = json.loads(data.decode('utf-8', 'ignore'))
            
            if msg.get("type") == "hello":
                found += 1
                name = msg.get("network_name", "Без названия")
                nick = msg.get("nickname", "Аноним")
                net_id = msg.get("network_id", "???")
                ip = msg.get("ip", addr[0])
                tstamp = datetime.now().strftime("%H:%M:%S")
                
                print(f"[{tstamp}] СЕТЬ НАЙДЕНА!")
                print(f"   Кем создана: {nick} (IP: {ip})")
                print(f"   Название:    '{name}'")
                print(f"   Идентификатор: {net_id}")
                print("-" * 60)
                
        except Exception as e:
            pass

if __name__ == "__main__":
    try:
        listen()
    except KeyboardInterrupt:
        print("\nРадар остановлен.")
