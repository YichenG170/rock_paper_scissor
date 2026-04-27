import json
import os
import socket
import sys
import threading
import time
import uuid
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


sessions = {}
game_server_started = False
game_server_error = None
game_server_lock = threading.Lock()


def send_message(conn, data):
    message = json.dumps(data).encode("utf-8")
    conn.sendall(len(message).to_bytes(4, "big") + message)


def recv_exact(conn, size):
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise ConnectionError("connection closed")
        data += chunk
    return data


def receive_message(conn):
    length = int.from_bytes(recv_exact(conn, 4), "big")
    return json.loads(recv_exact(conn, length).decode("utf-8"))


def port_is_available(port):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


class WebSession:
    def __init__(self, name, host):
        self.id = uuid.uuid4().hex
        self.name = name
        self.host = host
        self.messages = []
        self.lock = threading.Lock()
        self.connected = False
        self.error = None
        self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conn.connect((host, 5555))
        send_message(self.conn, {"name": name})
        self.connected = True
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self):
        while True:
            try:
                msg = receive_message(self.conn)
                if not msg:
                    raise ConnectionError("empty message")
                with self.lock:
                    self.messages.append({"time": time.time(), "data": msg})
                    self.messages = self.messages[-80:]
            except Exception as exc:
                self.connected = False
                self.error = str(exc)
                with self.lock:
                    self.messages.append({
                        "time": time.time(),
                        "data": {"type": "disconnect", "error": self.error},
                    })
                break

    def drain(self, after_index):
        with self.lock:
            total = len(self.messages)
            start = max(0, min(after_index, total))
            return total, self.messages[start:]

    def send(self, payload):
        if not self.connected:
            raise ConnectionError(self.error or "not connected")
        send_message(self.conn, payload)


def ensure_local_game_server(max_players):
    global game_server_started, game_server_error
    with game_server_lock:
        if game_server_started and port_is_available(5555):
            game_server_started = False
            game_server_error = None
        if game_server_started:
            return
        from server.game_server import start_server

        def run():
            global game_server_error
            try:
                start_server("Web Host", max_players)
            except Exception as exc:
                game_server_error = str(exc)

        threading.Thread(target=run, daemon=True).start()
        game_server_started = True
        game_server_error = None

    time.sleep(1.0)
    if game_server_error:
        game_server_started = False
        raise RuntimeError(f"game server failed to start: {game_server_error}")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/messages":
            self.handle_messages(parsed)
            return
        if parsed.path == "/":
            self.path = "/templates/index.html"
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/connect":
            self.handle_connect()
            return
        if parsed.path == "/api/action":
            self.handle_action()
            return
        self.send_error(404)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_connect(self):
        global game_server_started
        data = self.read_json()
        name = (data.get("name") or "玩家").strip()[:24]
        host = (data.get("host") or "127.0.0.1").strip()
        max_players = int(data.get("maxPlayers") or 2)
        if data.get("createServer"):
            ensure_local_game_server(max_players)
            host = "127.0.0.1"
        try:
            session = WebSession(name, host)
            sessions[session.id] = session
            self.send_json({"ok": True, "sessionId": session.id})
        except Exception as exc:
            if data.get("createServer"):
                game_server_started = False
            self.send_json({"ok": False, "error": str(exc)}, 500)

    def handle_messages(self, parsed):
        query = parse_qs(parsed.query)
        session_id = query.get("session", [""])[0]
        after = int(query.get("after", ["0"])[0] or 0)
        session = sessions.get(session_id)
        if not session:
            self.send_json({"ok": False, "error": "session not found"}, 404)
            return
        index, messages = session.drain(after)
        self.send_json({
            "ok": True,
            "index": index,
            "connected": session.connected,
            "messages": messages,
        })

    def handle_action(self):
        data = self.read_json()
        session = sessions.get(data.get("session"))
        if not session:
            self.send_json({"ok": False, "error": "session not found"}, 404)
            return
        try:
            session.send(data.get("payload") or {})
            self.send_json({"ok": True})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 500)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    os.chdir(ROOT)
    port = int(os.environ.get("WEB_PORT", "8001"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Web interface: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
