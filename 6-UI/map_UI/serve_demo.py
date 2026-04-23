from __future__ import annotations

import json
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DELIVERY_DIR = Path(__file__).resolve().parent
ROOT_DIR = DELIVERY_DIR.parent
ENV_PATH = ROOT_DIR / "azure_client" / ".env"
STATIC_ENV_PATH = DELIVERY_DIR / "amap-env.js"
HOST = "127.0.0.1"
PORT = 8126


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_static_amap_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    content = path.read_text(encoding="utf-8")

    key_match = re.search(
        r'window\.AMAP_JS_API_KEY\s*=\s*window\.AMAP_JS_API_KEY\s*\|\|\s*["\']([^"\']+)["\']',
        content,
    )
    if key_match:
        values["AMAP_JS_API_KEY"] = key_match.group(1)

    security_match = re.search(r'securityJsCode\s*:\s*["\']([^"\']+)["\']', content)
    if security_match:
        values["AMAP_SECURITY_JSCODE"] = security_match.group(1)

    return values


def resolve_amap_key(env_values: dict[str, str]) -> tuple[str, str]:
    if env_values.get("AMAP_JS_API_KEY"):
        return env_values["AMAP_JS_API_KEY"], "AMAP_JS_API_KEY"
    if env_values.get("AMAP_KEY"):
        return env_values["AMAP_KEY"], "AMAP_KEY"
    return "YOUR_AMAP_JS_API_KEY", "missing"


def resolve_security_code(env_values: dict[str, str]) -> tuple[str, str]:
    for key in ("AMAP_SECURITY_JSCODE", "AMAP_JS_SECURITY_CODE", "AMAP_SECURITY_CODE"):
        if env_values.get(key):
            return env_values[key], key
    return "", "missing"


def resolve_runtime_config() -> tuple[str, str, str, str]:
    env_values = load_env(ENV_PATH)
    static_values = load_static_amap_env(STATIC_ENV_PATH)

    key, source = resolve_amap_key(env_values)
    if source == "missing":
        fallback_key = static_values.get("AMAP_JS_API_KEY", "")
        if fallback_key:
            key = fallback_key
            source = "amap-env.js"

    security_code, security_source = resolve_security_code(env_values)
    if security_source == "missing":
        fallback_security_code = static_values.get("AMAP_SECURITY_JSCODE", "")
        if fallback_security_code:
            security_code = fallback_security_code
            security_source = "amap-env.js"

    return key, source, security_code, security_source


def masked(value: str) -> str:
    if not value or value == "YOUR_AMAP_JS_API_KEY":
        return value
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DELIVERY_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self.path = "/map_demo.html"
            return super().do_GET()

        if self.path == "/amap-env.js":
            key, source, security_code, security_source = resolve_runtime_config()
            payload = (
                f"window.AMAP_JS_API_KEY = {json.dumps(key)};\n"
                f"window.AMAP_KEY_SOURCE = {json.dumps(source)};\n"
                f"window.AMAP_SECURITY_CODE_SOURCE = {json.dumps(security_source)};\n"
            )
            if security_code:
                payload += (
                    "window._AMapSecurityConfig = "
                    f"{{ securityJsCode: {json.dumps(security_code)} }};\n"
                )
            data = payload.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if self.path == "/key-status":
            key, source, security_code, security_source = resolve_runtime_config()
            body = json.dumps(
                {
                    "env_path": str(ENV_PATH),
                    "exists": ENV_PATH.exists(),
                    "static_env_path": str(STATIC_ENV_PATH),
                    "static_exists": STATIC_ENV_PATH.exists(),
                    "source": source,
                    "masked_key": masked(key),
                    "using_placeholder": key == "YOUR_AMAP_JS_API_KEY",
                    "security_code_source": security_source,
                    "has_security_code": bool(security_code),
                    "masked_security_code": masked(security_code),
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        return super().do_GET()


def main() -> None:
    key, source, security_code, security_source = resolve_runtime_config()

    print(f"Serving delivery demo from: {DELIVERY_DIR}")
    print(f"Environment file: {ENV_PATH} (exists={ENV_PATH.exists()})")
    print(f"Static amap file: {STATIC_ENV_PATH} (exists={STATIC_ENV_PATH.exists()})")
    print(f"Key source: {source}")
    print(f"Key preview: {masked(key)}")
    print(f"Security code source: {security_source}")
    print(f"Security code preview: {masked(security_code)}")
    print(f"Open: http://{HOST}:{PORT}/map_demo.html")
    print(f"Status: http://{HOST}:{PORT}/key-status")

    server = ThreadingHTTPServer((HOST, PORT), DemoHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
