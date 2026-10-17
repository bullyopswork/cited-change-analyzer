"""Conservative lexical alignment. Citation validity is not semantic accuracy."""

from __future__ import annotations

import copy
import difflib
import re
import time
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone

from .extraction import check_metadata


def _paragraphs(text: str) -> list[dict]:
    records = []
    start = 0
    for boundary in list(re.finditer(r"\n[ \t]*\n+", text)) + [None]:
        stop = boundary.start() if boundary else len(text)
        chunk = text[start:stop]
        left = len(chunk) - len(chunk.lstrip())
        right = len(chunk.rstrip())
        if right > left:
            a, b = start + left, start + right
            records.append({"start": a, "end": b, "quote": text[a:b],
                            "key": " ".join(text[a:b].split())})
        if boundary:
            start = boundary.end()
    return records


def _evidence(paragraph: dict | None) -> dict | None:
    return ({key: paragraph[key] for key in ("start", "end", "quote")}
            if paragraph else None)


def _category(before: str, after: str) -> str:
    # Classify only changed lexical tokens, not unrelated unchanged dates/modals.
    old, new = Counter(before.split()), Counter(after.split())
    deleted, inserted = list((old - new).elements()), list((new - old).elements())
    changed = " ".join(deleted + inserted)
    dates = r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:,?\s+\d{4})?)\b"
    if re.findall(dates, before, re.I) != re.findall(dates, after, re.I):
        return "date"
    # A bare modal "may" is not the month May. Named calendar dates were
    # checked above with a day; standalone month words remain lexical edits.
    if re.search(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|20\d{2})\b", changed, re.I):
        return "date"
    if re.search(r"[$€£]|\b\d[\d,.]*(?:%|\b)|\b(?:dollars?|cents?)\b", changed, re.I):
        return "amount"
    if re.search(r"\b(?:must|shall|may|not|never|required|prohibited|cannot|can't|mandatory|unless|except)\b", changed, re.I):
        return "requirement"
    # Case and punctuation alone are editorial candidates, not asserted harmless.
    if re.sub(r"[^\w]", "", before).casefold() == re.sub(r"[^\w]", "", after).casefold():
        return "editorial"
    return "wording"


def compare_texts(before: str, after: str, *, section: str, title: str = "",
                  corpus: str = "", before_metadata: dict, after_metadata: dict,
                  comparison_id: str | None = None) -> dict:
    """Compare original strings without changing their citation coordinate space.

    metadata requires date, url, snapshot_sha256 (digest of original snapshot).
    Text may be empty only when caller has established absence in a valid dated
    snapshot. Paragraph moves are matched before unmatched text is paired.
    """
    started = time.perf_counter()
    if not isinstance(before, str) or not isinstance(after, str):
        raise ValueError("before and after must be strings")
    if max(len(before), len(after)) > 1_000_000:
        raise ValueError("section text exceeds the 1,000,000 code-point comparison limit")
    if not isinstance(section, str) or not section.strip():
        raise ValueError("section is required")
    check_metadata(before_metadata)
    check_metadata(after_metadata)
    old, new = _paragraphs(before), _paragraphs(after)
    if max(len(old), len(new)) > 2_000:
        raise ValueError("section exceeds the 2,000 paragraph comparison limit")
    # Wrapping or blank-line insertion can change apparent paragraph boundaries
    # without changing text. Suppress that whole-document formatting control.
    if " ".join(before.split()) == " ".join(after.split()):
        old, new = [], []
    old_keys, new_keys = [p["key"] for p in old], [p["key"] for p in new]
    matcher = difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    unchanged_old, unchanged_new = set(), set()
    for a, b, size in matcher.get_matching_blocks():
        unchanged_old.update(range(a, a + size))
        unchanged_new.update(range(b, b + size))
    unmatched_old = set(range(len(old))) - unchanged_old
    unmatched_new = set(range(len(new))) - unchanged_new
    lookup = defaultdict(deque)
    for j in sorted(unmatched_new):
        lookup[new[j]["key"]].append(j)
    changes = []

    def add(category: str, left: dict | None, right: dict | None) -> None:
        uncertain = category in {"amount", "date", "requirement", "wording", "editorial"}
        summary = {"added": "Paragraph text added.", "removed": "Paragraph text removed.",
                   "moved": "Matching paragraph appears at a different position.",
                   "amount": "Numeric or amount wording changed.",
                   "date": "Date-like wording changed.",
                   "requirement": "Requirement or negation wording changed.",
                   "editorial": "Case or punctuation changed; significance needs review.",
                   "wording": "Paragraph wording revised."}[category]
        changes.append({"id": f"change-{len(changes) + 1}", "category": category,
                        "summary": summary, "before_evidence": _evidence(left),
                        "after_evidence": _evidence(right), "needs_review": uncertain,
                        "review_reason": ("Lexical classification only; review legal and semantic significance."
                                          if uncertain else None), "method": "deterministic"})

    # Pair identical unmatched paragraphs first, including repeats, in stable order.
    for i in sorted(unmatched_old):
        candidates = lookup[old[i]["key"]]
        if candidates:
            j = candidates.popleft()
            add("moved", old[i], new[j])
            unmatched_old.remove(i)
            unmatched_new.remove(j)
    # Pair revisions only inside their original edit region, not across anchors.
    for tag, a, b, c, d in matcher.get_opcodes():
        if tag == "equal":
            continue
        left = [old[i] for i in range(a, b) if i in unmatched_old]
        right = [new[j] for j in range(c, d) if j in unmatched_new]
        for k in range(max(len(left), len(right))):
            prior = left[k] if k < len(left) else None
            later = right[k] if k < len(right) else None
            category = ("added" if prior is None else "removed" if later is None
                        else _category(prior["key"], later["key"]))
            add(category, prior, later)
    identifier = comparison_id or f"{section}__{before_metadata['date']}__{after_metadata['date']}"

    def source(metadata: dict, text: str) -> dict:
        keys = ["date", "url", "snapshot_sha256"]
        if metadata.get("source_kind") == "local":
            keys += ["source_kind", "filename", "format", "extraction_warnings"]
            if "pages" in metadata:
                keys.append("pages")
        return {key: copy.deepcopy(metadata[key]) for key in keys} | {"text": text}

    return {"schema_version": "1.0", "id": identifier, "section": section,
            "title": title or section, "corpus": corpus,
            "before": source(before_metadata, before),
            "after": source(after_metadata, after),
            "changes": changes, "warnings": [],
            "analysis": {"method": "deterministic", "model": None, "prompt_version": None,
                         "generated_at": datetime.now(timezone.utc).isoformat(),
                         "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                         "input_tokens": 0, "output_tokens": 0, "cost_usd": 0}}
