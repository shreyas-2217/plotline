"""Local dev server: mimics the Vercel function so the front-end can be
tested end-to-end without any Vercel tooling.

    python tests/local_server.py   ->  http://localhost:8787
"""

import io
import json
import sys
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from api.story import handler  # noqa: E402


class H(SimpleHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        if self.path != "/api/story":
            self._send(404, json.dumps({"ok": False, "error": "not found"}))
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        # multipart? take the file part crudely
        ctype = self.headers.get("Content-Type", "")
        if "multipart" in ctype:
            boundary = ctype.split("boundary=")[-1].strip().encode()
            parts = raw.split(b"--" + boundary)
            for p in parts:
                if p and b"filename=" in p:
                    raw = p.split(b"\r\n\r\n", 1)[1]
                    if raw.endswith(b"\r\n"):
                        raw = raw[:-2]
                    break
        resp = handler({"method": "POST", "body": raw})
        self._send(resp["statusCode"], resp["body"])

    def translate_path(self, path):
        # local aliases matching the Vercel routes
        if path.startswith("/samples/"):
            path = "/data/" + path[len("/samples/"):]
        elif path.startswith("/css/") or path.startswith("/js/"):
            path = "/web" + path
        return super().translate_path(path)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"Plotline dev server: http://localhost:{port}  (root: {ROOT})")
    HTTPServer(("127.0.0.1", port), H).serve_forever()
