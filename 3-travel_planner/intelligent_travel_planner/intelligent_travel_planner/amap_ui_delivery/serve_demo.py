from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os


def main() -> None:
    root = Path(__file__).resolve().parent
    os.chdir(root)
    server = ThreadingHTTPServer(("127.0.0.1", 8010), SimpleHTTPRequestHandler)
    print("Serving amap_ui_delivery at http://127.0.0.1:8010/map_demo.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
