import socket
import threading
import json
from utils.logger import log
from queue import Queue

clients = {}          
player_queues = {}    

def send_message(conn, data):
    try:
        message = json.dumps(data).encode("utf-8")
        header = len(message).to_bytes(4, "big")
        conn.sendall(header + message)
    except Exception as e:
        log(f"发送消息失败: {e}", "red")

def send_to_player(player_id, data):
    if player_id in clients:
        send_message(clients[player_id], data)

def recv_exact(conn, n):
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            raise ConnectionError("连接已关闭")
        data += chunk
    return data

def receive_message(conn):
    try:
        length_bytes = recv_exact(conn, 4)
        length = int.from_bytes(length_bytes, "big")
        data_bytes = recv_exact(conn, length)
        data = data_bytes.decode("utf-8")
        return json.loads(data)
    except:
        return {}

def get_message(player_id, timeout=0.1):
    if player_id not in player_queues:
        return {}
    try:
        return player_queues[player_id].get(timeout=timeout)
    except:
        return {}

def start_network_server(host, port, game_state, on_player_join):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(8)
    log(f"✅ 服务器已启动，端口 {port}，等待玩家加入...", "green")

    def handle_client(conn, addr):
        player_id = f"player_{len(clients)}"
        name_msg = receive_message(conn)
        name = name_msg.get("name", f"玩家{len(clients)}")

        player = game_state.add_player(player_id, name)
        clients[player_id] = conn
        player_queues[player_id] = Queue()

        log(f"✅ {name} 加入游戏", "green")
        on_player_join(player, conn)

        while True:
            msg = receive_message(conn)
            if msg:
                player_queues[player_id].put(msg)
            else:
                break

    while len(clients) < game_state.max_players:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()