"""The demo page: paste code, see what breaks in the next Odoo version.

A plain WSGI app (no framework), deployed on Vercel as a Python function:

    GET  /           the page
    POST /api/check  {"kind": "python" | "xml" | "js", "code": "...", "from": 16, "to": 17}

The code is checked in memory and not stored or logged.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from odoo_preflight import __version__  # noqa: E402
from odoo_preflight.cli import LATEST, check_source  # noqa: E402

PAGE = (Path(__file__).parent / "index.html").read_text(encoding="utf-8").replace("{{version}}", __version__)
MAX_CODE = 100_000
KINDS = ("python", "xml", "js")


def app(environ, start_response):
    path, method = environ.get("PATH_INFO", "/"), environ.get("REQUEST_METHOD", "GET")
    if path == "/api/check" and method == "POST":
        status, body = check(environ)
        return respond(start_response, status, json.dumps(body, ensure_ascii=False), "application/json")
    if path in ("/", "/index.html") and method in ("GET", "HEAD"):
        return respond(start_response, "200 OK", PAGE, "text/html; charset=utf-8", cache=True)
    return respond(start_response, "404 Not Found", json.dumps({"error": "Not found"}), "application/json")


def check(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > MAX_CODE * 4:
        return "413 Payload Too Large", {"error": "The code is too long (100,000 characters at most)."}
    try:
        request = json.loads(environ["wsgi.input"].read(length) or b"{}")
        kind, code = request["kind"], request["code"]
        version_from, version_to = int(request["from"]), int(request["to"])
    except (ValueError, KeyError, TypeError):
        return "400 Bad Request", {"error": "Send kind, code, from and to."}
    if kind not in KINDS or not isinstance(code, str) or not 16 <= version_from < version_to <= LATEST:
        return "400 Bad Request", {"error": f"kind must be one of {', '.join(KINDS)}, and 16 <= from < to <= {LATEST}."}
    if len(code) > MAX_CODE:
        return "413 Payload Too Large", {"error": "The code is too long (100,000 characters at most)."}
    try:
        findings = check_source(kind, code, version_from, version_to)
    except (SyntaxError, ValueError, RecursionError) as error:
        return "200 OK", {"findings": [], "parse_error": parse_error(kind, error)}
    return "200 OK", {"findings": [finding.as_dict(ROOT) for finding in findings]}


def parse_error(kind, error):
    line = getattr(error, "lineno", None)
    message = getattr(error, "msg", None) or str(error)
    language = {"python": "Python", "xml": "XML", "js": "JavaScript"}[kind]
    return f"This is not valid {language}" + (f" (line {line}: {message})." if line else f": {message}.")


def respond(start_response, status, body, content_type, cache=False):
    data = body.encode("utf-8")
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(data))),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("Cache-Control", "public, max-age=300" if cache else "no-store"),
    ]
    start_response(status, headers)
    return [data]


if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    print("http://localhost:8000")
    make_server("", 8000, app).serve_forever()
