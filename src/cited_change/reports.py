"""Validated, atomic JSON and script-free standalone HTML report exports."""

from __future__ import annotations

import html
import json
import os
import tempfile
from pathlib import Path

from .validation import validate


def _checked(report: dict) -> None:
    errors = validate(report)
    if errors:
        raise ValueError("invalid comparison: " + "; ".join(errors))


def _atomic_write(path: str | Path, content: str) -> None:
    destination = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def export_json(report: dict, path: str | Path | None = None) -> str:
    _checked(report)
    content = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if path is not None:
        _atomic_write(path, content)
    return content


def export_html(report: dict, path: str | Path | None = None) -> str:
    _checked(report)
    escape = lambda value: html.escape(str(value), quote=True)
    parts = ["<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">",
             "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
             "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">",
             f"<title>{escape(report['title'])} — Cited Change Analyzer</title>",
             "<style>body{font:16px system-ui;max-width:960px;margin:2rem auto;padding:0 1rem;color:#182333}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f4f6;padding:1rem}article{border-top:1px solid #ccd;padding:1rem 0}small{overflow-wrap:anywhere}</style>",
             f"<h1>{escape(report['section'])}: {escape(report['title'])}</h1>",
             f"<p>{escape(report['corpus'])}</p>",
             "<p>Exact citations are checked against these saved texts. This does not establish legal or semantic accuracy.</p>"]
    for side in ("before", "after"):
        source = report[side]
        if source.get("source_kind") == "local":
            parts.extend([f"<h2>{side.title()} — Local file: {escape(source['filename'])}</h2>",
                          f"<p>{escape(source['format'].upper())}; imported {escape(source['date'])} UTC "
                          "(not a publication or effective date).</p>"])
            if source.get("pages"):
                labels = "; ".join(f"Page {p['number']} [{p['start']}, {p['end']})"
                                   for p in source["pages"])
                parts.append(f"<p>Extracted page ranges: {labels}</p>")
        else:
            parts.extend([f"<h2>{side.title()} — {escape(source['date'])}</h2>",
                          f"<p><a href=\"{escape(source['url'])}\" rel=\"noreferrer\">Dated source</a></p>"])
        parts.extend([f"<small>Snapshot SHA-256: {escape(source['snapshot_sha256'])}</small>",
                      f"<pre>{escape(source['text']) if source['text'] else '[Section absent from this snapshot]'}</pre>"])
    parts.append(f"<h2>Changes ({len(report['changes'])})</h2>")
    for change in report["changes"]:
        parts.extend([f"<article><h3>{escape(change['category'])}</h3><p>{escape(change['summary'])}</p>"])
        if change["needs_review"]:
            parts.append(f"<p><strong>Needs review:</strong> {escape(change['review_reason'])}</p>")
        for side in ("before", "after"):
            evidence = change[f"{side}_evidence"]
            if evidence is not None:
                source = report[side]
                label = side.title()
                if source.get("source_kind") == "local":
                    label += f" — {source['filename']}"
                    numbers = [str(p["number"]) for p in source.get("pages", [])
                               if p["start"] < evidence["end"] and p["end"] > evidence["start"]]
                    if numbers:
                        label += " — Page " + ", ".join(numbers)
                parts.append(f"<h4>{escape(label)} [{evidence['start']}, {evidence['end']})</h4><pre>{escape(evidence['quote'])}</pre>")
        parts.append("</article>")
    for warning in report["warnings"]:
        parts.append(f"<p>Warning: {escape(warning)}</p>")
    parts.append("</html>\n")
    content = "\n".join(parts)
    if path is not None:
        _atomic_write(path, content)
    return content
