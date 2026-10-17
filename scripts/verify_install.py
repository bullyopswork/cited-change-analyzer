#!/usr/bin/env python3
"""Bounded wheel-only install proof. Requires Python >=3.11, never Node.

Only pip installation uses the network. Application requests use loopback and
synthetic documents; no own-key configuration is inherited or printed.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import http.client
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time


class VerificationError(Exception):
    """Safe, authored diagnostic; never include captured subprocess output."""


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def clean_environment(root):
    keep = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL",
            "LC_CTYPE", "TMP", "TEMP", "TMPDIR", "SYSTEMDRIVE"}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    home = root / "home"
    home.mkdir()
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_STATE_HOME=str(home / "state"),
               APPDATA=str(home / "AppData" / "Roaming"),
               LOCALAPPDATA=str(home / "AppData" / "Local"),
               PYTHONNOUSERSITE="1", PIP_CONFIG_FILE=os.devnull,
               PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    return env


def start(command, *, cwd, env, stdout=subprocess.PIPE):
    options = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout,
                            stderr=subprocess.STDOUT, **options)


def stop(process):
    """Stop only this owned process tree, including spawned document workers."""
    if os.name == "nt":
        if process.poll() is None:
            killer = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
            try:
                subprocess.run([str(killer), "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=10, check=False)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)


def run(command, *, cwd, env, timeout=30):
    process = start(command, cwd=cwd, env=env)
    try:
        output, _ = process.communicate(timeout=timeout)
        require(process.returncode == 0, "A verification subprocess failed (output withheld).")
        return output.decode("utf-8")
    except subprocess.TimeoutExpired:
        raise VerificationError("A verification subprocess exceeded its time limit.") from None
    finally:
        stop(process)
        if process.stdout:
            process.stdout.close()


def make_pdf(text):
    """A complete single-page selectable-text PDF, without a generator dependency."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"]
    raw = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(raw))
        raw.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(raw)
    raw.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        raw.extend(f"{offset:010d} 00000 n \n".encode())
    raw.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(raw)


def stable(report):
    result = json.loads(json.dumps(report))
    for field in ("generated_at", "latency_ms"):
        result.get("analysis", {}).pop(field, None)
    # Import dates are checked independently; a proof can cross UTC midnight.
    for side in ("before", "after"):
        result[side].pop("date", None)
    return result


def check_report(report, pair, valid_dates):
    require(len(report.get("changes", [])) == 1, "Synthetic rate change was not detected exactly once.")
    for side, (path, text) in zip(("before", "after"), pair):
        source = report[side]
        require(source["text"] == text, "Extracted fixture text differs from the exact expected text.")
        require(source["snapshot_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest(),
                "Fixture source hash differs.")
        require(source["source_kind"] == "local" and source["filename"] == path.name and source["url"] == "",
                "Local source identity differs.")
        require(source["date"] in valid_dates, "Local import date is not a UTC proof date.")
        require(source["format"] == ("pdf" if path.suffix == ".pdf" else "text"), "Source format differs.")
        if path.suffix == ".pdf":
            require(source["pages"] == [{"number": 1, "start": 0, "end": len(text)}], "PDF page offsets differ.")
        evidence = report["changes"][0][side + "_evidence"]
        require(evidence is not None and source["text"][evidence["start"]:evidence["end"]] == evidence["quote"],
                "Change evidence does not match the exact source slice.")
        require(evidence["quote"] == text, "Rate-change citation differs from the synthetic sentence.")


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name") == "cca-local-token":
            self.token = attrs.get("content")
        if tag == "script" and attrs.get("src"):
            self.urls.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("href"):
            self.urls.append(attrs["href"])


def request(port, method, path, *, token=None, value=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    outgoing = {"Content-Type": "application/json"}
    if token is not None:
        outgoing["X-CCA-Token"] = token
    outgoing.update(headers or {})
    try:
        connection.request(method, path, body=None if value is None else json.dumps(value).encode(), headers=outgoing)
        response = connection.getresponse()
        body = response.read(4 * 1024 * 1024 + 1)
        require(len(body) <= 4 * 1024 * 1024, "Local response exceeded proof size limit.")
        return response.status, dict(response.getheaders()), body
    finally:
        connection.close()


def prove(artifact, root, proof):
    env = clean_environment(root)
    work = root / "outside-checkout"
    work.mkdir()
    venv = root / "venv"
    run([sys.executable, "-I", "-m", "venv", str(venv)], cwd=work, env=env, timeout=60)
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    command = scripts / ("cited-change.exe" if os.name == "nt" else "cited-change")
    run([str(python), "-I", "-m", "pip", "install", "--no-cache-dir", "--retries", "1", "--timeout", "20", str(artifact)],
        cwd=work, env=env, timeout=150)
    inspection = run([str(python), "-I", "-c",
                      "import importlib.metadata as m,json,pathlib,sys,cited_change,pypdf; "
                      "assert pathlib.Path(cited_change.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve()); "
                      "print(json.dumps({'package_version':m.version('cited-change-analyzer'),'pypdf_version':m.version('pypdf')}))"],
                     cwd=work, env=env)
    proof.update(json.loads(inspection))
    proof["checks"].append("clean-venv-installed-package-and-pypdf")
    pairs = {}
    for kind, suffixes in {"txt": ("txt", "txt"), "pdf": ("pdf", "pdf"), "mixed": ("txt", "pdf")}.items():
        pair = []
        for side, amount, suffix in zip(("before", "after"), (100, 150), suffixes):
            text = f"Pay ${amount}."
            path = work / f"{kind}-{side}.{suffix}"
            path.write_bytes(make_pdf(text) if suffix == "pdf" else text.encode())
            pair.append((path, text))
        pairs[kind] = pair
    expected = {}
    first_date = datetime.now(timezone.utc).date().isoformat()
    for kind, pair in pairs.items():
        destination = work / f"{kind}-report.json"
        run([str(command), "compare", "--before", str(pair[0][0]), "--after", str(pair[1][0]), "--output", str(destination)], cwd=work, env=env)
        report = json.loads(destination.read_text(encoding="utf-8"))
        check_report(report, pair, {first_date, datetime.now(timezone.utc).date().isoformat()})
        validation = json.loads(run([str(command), "validate", str(destination)], cwd=work, env=env))
        require(validation["valid"] and validation["errors"] == [], "Installed validator rejected the CLI report.")
        expected[kind] = report
        proof["checks"].append(f"installed-cli-{kind}-exact-sources-citations-and-validation")

    with (root / "server.log").open("wb") as output:
        server = start([str(command), "serve", "--port", "0", "--no-browser"], cwd=work, env=env, stdout=output)
        try:
            deadline = time.monotonic() + 20
            port = None
            while time.monotonic() < deadline:
                require(server.poll() is None, "Installed server exited during startup.")
                match = re.search(rb"http://127\.0\.0\.1:(\d+)/", (root / "server.log").read_bytes())
                if match:
                    port = int(match.group(1))
                    break
                time.sleep(0.1)
            require(port is not None, "Installed server startup exceeded its time limit.")
            status, headers, body = request(port, "GET", "/")
            require(status == 200 and headers.get("Cache-Control") == "no-store", "Bundled index unavailable or cached.")
            assets = Assets()
            assets.feed(body.decode("utf-8"))
            require(assets.token and assets.urls, "Bundled UI lacks session bootstrap or assets.")
            for url in assets.urls:
                require(not re.match(r"^[a-z]+:|^//", url) and ".." not in url.split("/"), "Bundled asset is not local.")
                status, _, asset = request(port, "GET", "/" + url.lstrip("./"))
                require(status == 200 and asset, "Bundled UI asset is missing.")
            status, _, body = request(port, "GET", "/api/bootstrap", token=assets.token)
            bootstrap = json.loads(body)
            require(status == 200 and bootstrap["version"] == proof["package_version"] and not bootstrap["ai"]["configured"],
                    "Installed bootstrap differs or inherited own-key configuration.")
            proof["checks"].append("installed-bundled-ui-assets-and-key-free-bootstrap")
            for token, extra in [(None, {}), ("invalid-proof-token", {}),
                                 (assets.token, {"Origin": "https://foreign.invalid"}),
                                 (assets.token, {"Host": "foreign.invalid"}),
                                 (assets.token, {"Sec-Fetch-Site": "cross-site"})]:
                require(request(port, "GET", "/api/bootstrap", token=token, headers=extra)[0] == 403,
                        "Local API authorization negative was not denied.")
            require(request(port, "POST", "/api/compare", value={})[0] == 403, "Unauthenticated upload was not denied.")
            require(request(port, "POST", "/api/compare", token=assets.token, value={},
                            headers={"Origin": "https://foreign.invalid"})[0] == 403, "Cross-origin upload was not denied.")
            proof["checks"].append("token-origin-host-and-cross-site-denials")
            for kind, pair in pairs.items():
                payload = {side: {"filename": path.name, "content_base64": base64.b64encode(path.read_bytes()).decode("ascii")}
                           for side, (path, _) in zip(("before", "after"), pair)}
                status, _, body = request(port, "POST", "/api/compare", token=assets.token, value=payload)
                require(status == 202, "Installed upload was not accepted.")
                identifier = json.loads(body)["job_id"]
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    status, _, body = request(port, "GET", "/api/jobs/" + identifier, token=assets.token)
                    require(status == 200, "Installed job was unavailable.")
                    job = json.loads(body)
                    if job["status"] != "running":
                        break
                    time.sleep(0.1)
                require(job["status"] == "succeeded", "Installed comparison did not finish successfully within its bound.")
                check_report(job["report"], pair, {first_date, datetime.now(timezone.utc).date().isoformat()})
                require(stable(job["report"]) == stable(expected[kind]), "Installed API and validated CLI reports differ.")
                proof["checks"].append(f"installed-api-{kind}-matches-validated-cli-report")
        finally:
            stop(server)
    proof["checks"].append("owned-server-and-workers-stopped")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True, help="built release wheel")
    parser.add_argument("--report", type=Path, required=True, help="safe JSON proof destination")
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    proof = {"ok": False, "platform": platform.system(), "python": platform.python_version(), "checks": []}
    try:
        require(sys.version_info >= (3, 11), "Verification requires Python 3.11 or newer.")
        require(artifact.is_file() and artifact.suffix == ".whl", "Artifact must be an existing wheel.")
        proof["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        # tempfile chooses the platform temporary directory, never the checkout.
        with tempfile.TemporaryDirectory(prefix="cca-install-proof-") as temporary:
            root = Path(temporary).resolve()
            require(not root.is_relative_to(Path(__file__).resolve().parent.parent), "Temporary proof directory must be outside the checkout.")
            prove(artifact, root, proof)
        proof["checks"].append("temporary-contexts-removed")
        proof["ok"] = True
    except VerificationError as error:
        proof["error"] = str(error)
    except Exception as error:
        proof["error"] = "Verification failed: " + type(error).__name__ + " (details withheld)."
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof))
    return 0 if proof["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
