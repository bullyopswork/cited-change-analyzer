"""Loopback-only application server with ephemeral documents and bounded workers.

The public static demo has no corresponding processing endpoint. This server is
started by the installer on their own machine; only explicit AI work may egress.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import mimetypes
import multiprocessing
import os
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import unquote, urlsplit
import webbrowser
import psutil

VERSION = "0.2.0"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_BODY_BYTES = 30 * 1024 * 1024
LIMITS = {"file_bytes": MAX_FILE_BYTES, "pdf_pages": 50, "characters": 100_000}
MAX_JOBS = 4
JOB_TTL = 1800
MAX_WORKER_RSS = 512 * 1024 * 1024


def _worker(send, mode, payload, ledger_path):
    try:
        # Parse/compare in an expendable child. POSIX additionally bounds CPU;
        # every platform is covered by the parent's wall-clock termination.
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (40, 41))
            if hasattr(resource, "RLIMIT_AS") and os.uname().sysname != "Darwin":
                resource.setrlimit(resource.RLIMIT_AS, (1024 ** 3, 1024 ** 3))
        except (ImportError, OSError, ValueError):
            pass
        if mode == "compare":
            import sys
            def no_network(event, _arguments):
                if event in {"socket.connect", "socket.getaddrinfo"}:
                    raise PermissionError("Local document comparison cannot make network requests.")
            sys.addaudithook(no_network)
            from .local_compare import compare_documents
            send.send({"kind": "progress", "stage": "Extracting and comparing documents locally"})
            result = compare_documents(payload["before_raw"], payload["before_filename"],
                                       payload["after_raw"], payload["after_filename"])
        elif mode == "ai":
            from .local_ai import enrich_local_report
            result = enrich_local_report(payload["report"], ledger_path,
                                         progress=lambda stage: send.send({"kind": "progress", "stage": str(stage)[:200]}))
        else:
            raise ValueError("Unsupported processing operation.")
        send.send({"kind": "result", "report": result})
    except ValueError as error:
        # Document/model errors are intentionally authored, bounded messages.
        send.send({"kind": "error", "error": str(error)[:500]})
    except BaseException:
        send.send({"kind": "error", "error": "The local worker could not process this document. Check its format and processing limits."})
    finally:
        send.close()


def run_isolated(mode, payload, *, ledger_path=None, timeout=60, progress=None, stop=None):
    """Run a single bounded child; never read a caller supplied filesystem path."""
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    child = context.Process(target=_worker, args=(send, mode, payload, ledger_path), daemon=True)
    child.start()
    send.close()
    deadline = time.monotonic() + timeout
    try:
        monitored = psutil.Process(child.pid)
        while time.monotonic() < deadline:
            if stop is not None and stop.is_set():
                raise ValueError("Processing stopped; no automatic retry was made.")
            try:
                if monitored.memory_info().rss > MAX_WORKER_RSS:
                    raise ValueError("Document processing exceeded the 512 MiB worker memory limit and was stopped.")
            except psutil.NoSuchProcess:
                pass
            if receive.poll(0.02):
                try:
                    message = receive.recv()
                except EOFError:
                    break
                if message["kind"] == "result":
                    return message["report"]
                if message["kind"] == "error":
                    raise ValueError(message["error"])
                if progress:
                    progress(message.get("stage", "Processing"))
            elif not child.is_alive():
                break
        if time.monotonic() >= deadline:
            raise ValueError("Processing exceeded the time limit and was stopped. Local results remain available; an AI request may still have incurred provider usage.")
        raise ValueError("The bounded document worker stopped before returning a result.")
    finally:
        if child.is_alive():
            child.terminate()
        child.join(timeout=3)
        if child.is_alive():
            child.kill()
            child.join(timeout=2)
        receive.close()


def user_state_directory():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    return base / "cited-change-analyzer"


class LocalApplication:
    def __init__(self, *, web_root=None, state_root=None, runner=run_isolated):
        self.web_root = Path(web_root) if web_root else files("cited_change").joinpath("web")
        self.state_root = Path(state_root) if state_root else user_state_directory()
        self.token = secrets.token_urlsafe(32)
        self.jobs = {}
        self.lock = threading.RLock()
        self.busy = False
        self.stop = threading.Event()
        self.runner = runner

    def configuration(self):
        from .local_ai import get_ai_configuration
        return {"version": VERSION, "limits": LIMITS, "ai": get_ai_configuration()}

    def _expire(self):
        now = time.monotonic()
        for key in list(self.jobs):
            if self.jobs[key]["status"] != "running" and now - self.jobs[key].get("last_access", self.jobs[key]["created"]) > JOB_TTL:
                del self.jobs[key]

    def job(self, identifier):
        with self.lock:
            self._expire()
            data = self.jobs.get(identifier)
            if data:
                data["last_access"] = time.monotonic()
            return {k: v for k, v in data.items() if k in {"job_id", "status", "stage", "report", "error", "local_report"}} if data else None

    def start(self, payload, *, identifier=None, ai=False):
        with self.lock:
            self._expire()
            if self.busy:
                raise RuntimeError("One analysis is already running. Wait for it to finish.")
            if ai:
                if identifier not in self.jobs or "local_report" not in self.jobs[identifier]:
                    raise ValueError("Compare documents locally before requesting AI explanations.")
                job = self.jobs[identifier]
                if job.get("ai_requested"):
                    raise ValueError("AI was already requested for this comparison. No automatic repeat charge is allowed.")
                if not self.configuration()["ai"]["configured"]:
                    raise ValueError("Own-key AI is not configured. See local setup instructions.")
                job["ai_requested"] = True
                payload = {"report": job["local_report"]}
            else:
                if len(self.jobs) >= MAX_JOBS:
                    oldest = min(self.jobs, key=lambda key: self.jobs[key]["created"])
                    del self.jobs[oldest]
                identifier = secrets.token_hex(12)
                job = {"job_id": identifier, "created": time.monotonic()}
                self.jobs[identifier] = job
            job.update(status="running", stage="Preparing optional AI" if ai else "Preparing local comparison")
            job.pop("error", None)
            self.busy = True

        def update(stage):
            with self.lock:
                job["stage"] = stage

        def execute():
            try:
                ledger = None
                if ai:
                    self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                    ledger = str(self.state_root / ("ai-" + identifier + ".sqlite"))
                report = self.runner("ai" if ai else "compare", payload, ledger_path=ledger,
                                     timeout=180 if ai else 60, progress=update, stop=self.stop)
                with self.lock:
                    job.update(report=report, status="succeeded", stage="Comparison ready", last_access=time.monotonic())
                    if not ai:
                        job["local_report"] = report
                    elif report.get("analysis", {}).get("ai_coverage", {}).get("status") == "unavailable":
                        job.update(status="error", error="AI explanations were unavailable. The local comparison is preserved.", stage="Local comparison preserved")
            except Exception as error:
                with self.lock:
                    job.update(status="error", stage="Analysis stopped", error=str(error)[:500] if isinstance(error, ValueError) else "Analysis could not be completed.")
                    if "local_report" in job:
                        job["report"] = job["local_report"]
            finally:
                # Input byte arrays leave scope here; no document file is saved.
                payload.clear()
                with self.lock:
                    self.busy = False
        threading.Thread(target=execute, daemon=True, name="cca-analysis").start()
        return identifier


class LocalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, application):
        if address[0] != "127.0.0.1":
            raise ValueError("Local processing binds only to 127.0.0.1.")
        self.application = application
        super().__init__(address, LocalHandler)

    def server_close(self):
        self.application.stop.set()
        super().server_close()


class LocalHandler(BaseHTTPRequestHandler):
    server_version = "CitedChangeLocal/0.2"

    def log_message(self, *_args):
        pass  # URLs/filenames/documents and tokens never enter request logs.

    def _target_allowed(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        return (host in hosts and self.headers.get("Sec-Fetch-Site") != "cross-site" and
                (not origin or origin in {"http://" + h for h in hosts}))

    def _reply(self, status, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _authorize(self, *, api=False):
        if not self._target_allowed():
            self._reply(403, {"error": "Only this local application origin is allowed."})
            return False
        if api and not hmac.compare_digest(self.headers.get("X-CCA-Token", ""), self.server.application.token):
            self._reply(403, {"error": "Local session token is required. Reload the application."})
            return False
        return True

    def do_OPTIONS(self):
        self._reply(403, {"error": "Cross-origin access is not enabled."})

    def do_GET(self):
        path = urlsplit(self.path).path
        api = path.startswith("/api/")
        if not self._authorize(api=api):
            return
        app = self.server.application
        if path == "/api/bootstrap":
            return self._reply(200, app.configuration())
        if path.startswith("/api/jobs/"):
            identifier = path.removeprefix("/api/jobs/")
            job = app.job(identifier)
            return self._reply(200 if job else 404, job or {"error": "Comparison expired or is not available. Select the files again."})
        if api:
            return self._reply(404, {"error": "Unknown local operation."})
        relative = unquote(path).lstrip("/") or "index.html"
        if any(p in {"", ".", ".."} for p in relative.split("/")) or "\\" in relative or "\x00" in relative:
            return self._reply(404, {"error": "Not found."})
        resource = app.web_root.joinpath(relative)
        try:
            body = resource.read_bytes()
        except (OSError, FileNotFoundError, IsADirectoryError):
            return self._reply(404, {"error": "Application asset missing. Install the complete release wheel."})
        if relative == "index.html":
            marker = f'<meta name="cca-local-token" content="{app.token}">'
            body = body.replace(b"</head>", marker.encode("ascii") + b"</head>", 1)
        kind = mimetypes.guess_type(relative)[0] or "application/octet-stream"
        if relative.endswith((".js", ".mjs")):
            kind = "text/javascript"
        self._reply(200, body, kind + ("; charset=utf-8" if kind.startswith("text/") else ""))

    def do_POST(self):
        if not self._authorize(api=True):
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self._reply(415, {"error": "Use JSON for local operations."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY_BYTES or self.headers.get("Transfer-Encoding"):
                return self._reply(413, {"error": "Request exceeds the local processing limit."})
            self.connection.settimeout(10)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete local request.")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Local request must be an object.")
            path = urlsplit(self.path).path
            app = self.server.application
            if path == "/api/compare":
                payload = {}
                for side in ("before", "after"):
                    item = value.get(side)
                    if not isinstance(item, dict) or not isinstance(item.get("filename"), str) or not isinstance(item.get("content_base64"), str):
                        raise ValueError("Select both an earlier and a revised TXT or PDF document.")
                    name = item["filename"]
                    if not name or len(name) > 255 or any(ord(c) < 32 for c in name):
                        raise ValueError("Document filename is invalid.")
                    try:
                        data = base64.b64decode(item["content_base64"], validate=True)
                    except (binascii.Error, ValueError):
                        raise ValueError("Document data is invalid.") from None
                    if not 0 < len(data) <= MAX_FILE_BYTES:
                        raise ValueError("Each document must be nonempty and at most 10 MiB.")
                    payload[side + "_raw"] = data
                    payload[side + "_filename"] = name
                identifier = app.start(payload)
            elif path.startswith("/api/jobs/") and path.endswith("/ai"):
                if value.get("consent") is not True:
                    raise ValueError("Explicit consent to send document sections to OpenAI is required.")
                identifier = app.start({}, identifier=path[len("/api/jobs/"):-len("/ai")], ai=True)
            else:
                return self._reply(404, {"error": "Unknown local operation."})
            self._reply(202, {"job_id": identifier})
        except RuntimeError as error:
            self._reply(429, {"error": str(error)})
        except (ValueError, UnicodeError, TimeoutError):
            # Authored ValueErrors carry actionable validation; JSON exceptions
            # are not allowed to dump document contents into a response.
            import sys
            error = sys.exc_info()[1]
            message = str(error) if type(error) is ValueError else "Local request could not be read."
            self._reply(400, {"error": message[:500]})


def serve(*, port=8765, open_browser=True, web_root=None):
    app = LocalApplication(web_root=web_root)
    if not app.web_root.joinpath("index.html").is_file():
        raise ValueError("Bundled interface is missing. Install the release wheel, or build the interface with the documented developer command.")
    server = LocalHTTPServer(("127.0.0.1", port), app)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Cited Change Analyzer {VERSION}: {url}", flush=True)
    print("Local comparison has no external requests. Press Ctrl+C to stop and discard in-memory documents.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
