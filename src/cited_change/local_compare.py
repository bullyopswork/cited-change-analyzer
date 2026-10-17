"""Offline document comparison using the established exact-citation engine."""

from __future__ import annotations

from .documents import extract_document
from .engine import compare_texts
from .validation import validate


def compare_documents(before_raw: bytes, before_filename: str,
                      after_raw: bytes, after_filename: str) -> dict:
    """Extract both complete files and return a validated deterministic report."""
    before = extract_document(before_raw, before_filename)
    after = extract_document(after_raw, after_filename)
    identifier = f"local__{before['snapshot_sha256']}__{after['snapshot_sha256']}"
    report = compare_texts(before["text"], after["text"], section="document",
                           title=f"{before['filename']} → {after['filename']}",
                           corpus="Local documents", before_metadata=before,
                           after_metadata=after, comparison_id=identifier)
    report["warnings"] = ["Local source dates record UTC import, not publication or effective dates. "
                          "This is lexical comparison, not legal or semantic verification."]
    for side, snapshot in (("Earlier document", before), ("Revised document", after)):
        report["warnings"].extend(f"{side}: {warning}" for warning in snapshot["extraction_warnings"])
    errors = validate(report)
    if errors:
        raise ValueError("invalid local comparison: " + "; ".join(errors))
    return report
