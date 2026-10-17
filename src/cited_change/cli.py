"""Reproducible local fetch/compare/validate commands, with JSON stdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .engine import compare_texts
from .extraction import MAX_XML_BYTES, extract_snapshot, section_source
from .fetch import fetch_bytes
from .provenance import connect, record_comparison
from .reports import export_html, export_json
from .validation import validate


def _read(path: str) -> bytes:
    with open(path, "rb") as handle:
        content = handle.read(MAX_XML_BYTES + 1)
    if not content or len(content) > MAX_XML_BYTES:
        raise ValueError(f"input is empty or exceeds the byte limit: {path}")
    return content


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="cited-change", description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="fetch a complete dated XML snapshot")
    fetch.add_argument("--url", required=True)
    fetch.add_argument("--date", required=True)
    fetch.add_argument("--output", required=True, help="local raw XML destination")
    compare = commands.add_parser("compare", help="compare local dated snapshot files")
    compare.add_argument("--before", required=True)
    compare.add_argument("--after", required=True)
    compare.add_argument("--before-date")
    compare.add_argument("--after-date")
    compare.add_argument("--before-url")
    compare.add_argument("--after-url")
    compare.add_argument("--section", default="local-documents")
    compare.add_argument("--title", default="")
    compare.add_argument("--corpus", default="")
    compare.add_argument("--format", choices=("auto", "xml", "text"), default="auto")
    compare.add_argument("--output", help="validated JSON destination; otherwise stdout")
    compare.add_argument("--html", help="optional standalone HTML destination")
    compare.add_argument("--database", help="optional append-only SQLite provenance archive")
    validate_parser = commands.add_parser("validate", help="validate contract and exact citations")
    validate_parser.add_argument("report", help="comparison JSON file")
    enrich = commands.add_parser("enrich", help="import saved model JSON with exact source grounding; no API calls")
    enrich.add_argument("report", help="existing validated comparison JSON")
    enrich.add_argument("--model-output", required=True, help="changes/warnings JSON returned by the model")
    enrich.add_argument("--model", required=True, help="actual model that generated the saved output")
    enrich.add_argument("--provenance", help="optional saved metadata JSON (prompt version, usage, billing)")
    enrich.add_argument("--output", help="validated JSON destination; otherwise stdout")
    serve = commands.add_parser("serve", help="launch the installed local browser application")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--web-root", help=argparse.SUPPRESS)
    explain = commands.add_parser("explain", help="optional own-key AI for a local comparison report")
    explain.add_argument("report")
    explain.add_argument("--budget-ledger", required=True, help="persistent ledger for this explicitly authorized analysis")
    explain.add_argument("--output", required=True)
    explain.add_argument("--html")
    explain.add_argument("--consent", action="store_true", help="send extracted sections directly to OpenAI using your own configured key")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "serve":
            from .local_server import serve
            if not 0 <= args.port <= 65535:
                raise ValueError("port must be within 0..65535")
            serve(port=args.port, open_browser=not args.no_browser, web_root=args.web_root)
        elif args.command == "explain":
            if not args.consent:
                raise ValueError("--consent is required to send extracted document sections to OpenAI")
            from .local_server import run_isolated
            report = json.loads(_read(args.report).decode("utf-8"))
            result = run_isolated("ai", {"report": report}, ledger_path=args.budget_ledger, timeout=180)
            export_json(result, args.output)
            if args.html:
                export_html(result, args.html)
            coverage = result.get("analysis", {}).get("ai_coverage", {})
            available = coverage.get("status") != "unavailable"
            print(json.dumps({"ok": available, "output": args.output, "ai_coverage": coverage}))
            return 0 if available else 1
        elif args.command == "fetch":
            raw = fetch_bytes(args.url)
            snapshot = extract_snapshot(raw, date=args.date, url=args.url)
            # Parse completely before writing; a failed fetch never creates empties.
            Path(args.output).write_bytes(raw)
            print(json.dumps({"ok": True, "path": args.output,
                              **{key: snapshot[key] for key in ("date", "url", "snapshot_sha256", "byte_length")},
                              "sections": sorted(snapshot["sections"])}))
        elif args.command == "compare":
            xml_auto = args.format == "auto" and Path(args.before).suffix.lower() == ".xml" and Path(args.after).suffix.lower() == ".xml"
            if (args.format == "auto" and not xml_auto) or (args.format == "text" and not (args.before_url or args.after_url)):
                from .local_server import run_isolated
                report = run_isolated("compare", {"before_raw": _read(args.before), "before_filename": Path(args.before).name,
                                                  "after_raw": _read(args.after), "after_filename": Path(args.after).name})
                if args.database:
                    connection = connect(args.database)
                    try:
                        saved = connection.execute('SELECT report_json FROM comparisons WHERE id=?', (report['id'],)).fetchone()
                        if saved:
                            previous = json.loads(saved[0])
                            def stable_local(value):
                                value = json.loads(json.dumps(value))
                                for field in ('generated_at', 'latency_ms'):
                                    value.get('analysis', {}).pop(field, None)
                                return value
                            if stable_local(previous) == stable_local(report):
                                report = previous
                        record_comparison(connection, report)
                    finally:
                        connection.close()
                content = export_json(report, args.output)
                if args.html:
                    export_html(report, args.html)
                print(json.dumps({"ok": True, "changes": len(report["changes"]), "output": args.output, "html": args.html}) if args.output else content, end="\n" if args.output else "")
                return 0
            if not all((args.before_date, args.after_date, args.before_url, args.after_url)):
                raise ValueError("dated XML/text snapshots require both dates and source URLs; local TXT/PDF files use --format auto")
            sources = {}
            titles = {}
            for side in ("before", "after"):
                raw = _read(getattr(args, side))
                date = getattr(args, f"{side}_date")
                url = getattr(args, f"{side}_url")
                if args.format == "xml" or xml_auto:
                    snapshot = extract_snapshot(raw, date=date, url=url)
                    sources[side] = section_source(snapshot, args.section)
                    titles[side] = snapshot["sections"].get(args.section, {}).get("title", "")
                else:
                    sources[side] = {"date": date, "url": url,
                                     "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
                                     "text": raw.decode("utf-8")}
            report = compare_texts(sources["before"]["text"], sources["after"]["text"],
                                   section=args.section, corpus=args.corpus,
                                   title=args.title or titles.get("after") or titles.get("before", ""),
                                   before_metadata=sources["before"], after_metadata=sources["after"])
            if args.database:
                connection = connect(args.database)
                try:
                    saved = connection.execute('SELECT report_json FROM comparisons WHERE id=?', (report['id'],)).fetchone()
                    if saved:
                        previous = json.loads(saved[0])
                        def stable(value):
                            value = json.loads(json.dumps(value))
                            for volatile in ('generated_at', 'latency_ms'):
                                value.get('analysis', {}).pop(volatile, None)
                            return value
                        if stable(previous) == stable(report):
                            report = previous
                    record_comparison(connection, report)
                finally:
                    connection.close()
            content = export_json(report, args.output)
            if args.html:
                export_html(report, args.html)
            if args.output:
                print(json.dumps({"ok": True, "id": report["id"], "changes": len(report["changes"]),
                                  "output": args.output, "html": args.html}))
            else:
                print(content, end="")
        elif args.command == "enrich":
            from .model import apply_model_output, parse_model_json
            report = parse_model_json(_read(args.report).decode("utf-8"))
            model_output = parse_model_json(_read(args.model_output).decode("utf-8"))
            provenance = (parse_model_json(_read(args.provenance).decode("utf-8"))
                          if args.provenance else None)
            report = apply_model_output(report, model_output, model=args.model, provenance=provenance)
            content = export_json(report, args.output)
            if args.output:
                print(json.dumps({"ok": True, "id": report["id"], "changes": len(report["changes"]),
                                  "output": args.output, "method": report["analysis"]["method"]}))
            else:
                print(content, end="")
        else:
            report = json.loads(_read(args.report).decode("utf-8"))
            errors = validate(report)
            print(json.dumps({"valid": not errors, "errors": errors,
                              "scope": "structure and exact source quotes, not semantic correctness"}))
            return int(bool(errors))
    except (ValueError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1
    return 0
