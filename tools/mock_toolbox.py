"""Mock toolbox for local dev: echoes uploaded image as PNG response.

Use it to verify the end-to-end agent flow without depending on L20_1 services.
Listens on http://localhost:8080.
"""
import cgi
import http.server


class MockHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path != "/api/shared/frame-bg-remover/process":
            self.send_error(404, "unknown endpoint")
            return

        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self.send_error(400, "expected multipart/form-data")
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype},
        )

        if "image" not in form:
            self.send_error(400, "missing 'image' field")
            return

        img_bytes = form["image"].file.read()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(img_bytes)))
        self.end_headers()
        self.wfile.write(img_bytes)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[MOCK] {fmt % args}", flush=True)


def main() -> None:
    server = http.server.HTTPServer(("localhost", 8080), MockHandler)
    print("Mock toolbox listening on http://localhost:8080", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
