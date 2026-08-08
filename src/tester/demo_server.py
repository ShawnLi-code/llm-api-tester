"""Tiny demo API for offline e2e runs. No external deps beyond stdlib + json.

Run:  python -m tester.demo_server  (serves on 127.0.0.1:8000)
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_USERS = {"1": {"id": 1, "name": "alice"}, "2": {"id": 2, "name": "bob"}}
_CONFIG = {
    "title": "Demo Config",
    "category": "testing",
    "graph": {"enabled": True, "depth": 3},
    "labels": ["a", "b"],
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code: int, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)
        if path == "/health":
            self._send(200, {"status": "ok"})
        elif path == "/users":
            limit = int(qs.get("limit", ["10"])[0])
            offset = int(qs.get("offset", ["0"])[0])
            self._send(200, {"items": list(_USERS.values())[offset : offset + limit], "total": len(_USERS)})
        elif path.startswith("/users/"):
            uid = path.rsplit("/", 1)[-1]
            user = _USERS.get(uid)
            if user:
                self._send(200, user)
            else:
                self._send(404, {"error": "not found"})
        elif path == "/config":
            self._send(200, _CONFIG)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/users":
            data = self._read_json()
            if not data.get("name"):
                self._send(400, {"error": "name required"})
                return
            uid = str(max(int(k) for k in _USERS) + 1)
            _USERS[uid] = {"id": int(uid), "name": data["name"]}
            self._send(201, _USERS[uid])
        else:
            self._send(404, {"error": "not found"})


def serve(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    return server


def serve_in_thread(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    server = serve(host, port)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


if __name__ == "__main__":
    srv = serve()
    print(f"demo server on {srv.server_address[0]}:{srv.server_address[1]}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
