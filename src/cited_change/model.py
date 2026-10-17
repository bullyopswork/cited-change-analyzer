"""Strict model-output import and opt-in, budget-reserved OpenAI Responses calls.

Importing outputs never calls a model. Exact source grounding is not verification
of a model's explanation. No credentials other than OPENAI_API_KEY are consulted.
"""

from __future__ import annotations

import copy
from collections import Counter
import difflib
import json
import math
import os
import re
import sqlite3
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

from .validation import CATEGORIES, validate

PROMPT_VERSION = "cca-grounded-v1"
MAX_RESPONSE_BYTES = 2_000_000
OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["changes", "warnings"],
    "properties": {
        "changes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["category", "summary", "before_quote", "after_quote",
                         "needs_review", "review_reason"],
            "properties": {
                "category": {"type": "string", "enum": sorted(CATEGORIES)},
                "summary": {"type": "string"},
                "before_quote": {"type": ["string", "null"]},
                "after_quote": {"type": ["string", "null"]},
                "needs_review": {"type": "boolean"},
                "review_reason": {"type": ["string", "null"]},
            }}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


class ModelError(ValueError):
    """Rejected input, model output, or redacted transport failure."""


class BudgetError(ModelError):
    """No request may be sent under this ledger's limits."""


def build_model_input(comparison: dict) -> dict:
    """Common native-helper/API prompt contract; no network or credentials.

    Pass the instructions, dated input and output schema to the model; import its
    changes/warnings object separately. Source text remains byte-for-byte intact.
    """
    if validate(comparison):
        raise ModelError("valid comparison required")
    return {
        "prompt_version": PROMPT_VERSION,
        "instructions": (Path(__file__).with_name('resources') / (PROMPT_VERSION + '.txt')).read_text(encoding='utf-8'),
        "input": copy.deepcopy({"section": comparison["section"], "before": comparison["before"],
                                "after": comparison["after"]}),
        "output_schema": copy.deepcopy(OUTPUT_SCHEMA),
    }


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelError("duplicate JSON object key")
        result[key] = value
    return result


def _loads(content):
    try:
        return json.loads(content, object_pairs_hook=_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(ModelError("nonfinite JSON")))
    except (ValueError, TypeError, UnicodeError):
        raise ModelError("invalid model JSON") from None


def parse_model_json(content):
    """Strict saved-output parsing, identical to live response parsing."""
    return _loads(content)


def _evidence(text, quote, side):
    if quote is None:
        return None
    if not isinstance(quote, str) or not quote.strip():
        raise ModelError(f"{side} quote must be nonempty or null")
    start = text.find(quote)
    if start < 0:
        raise ModelError(f"{side} quote absent from source")
    # Search from start+1, not start+len: overlapping repeats are ambiguous too.
    if text.find(quote, start + 1) >= 0:
        raise ModelError(f"{side} quote is ambiguous in source")
    return {"start": start, "end": start + len(quote), "quote": quote}


def _touches(evidence, opcodes, side):
    """A cited span must intersect a textual edit, not just unrelated context."""
    for tag, a, b, c, d in opcodes:
        if tag == "equal":
            continue
        start, end = (a, b) if side == "before" else (c, d)
        if (start < evidence["end"] and end > evidence["start"]) or (
                start == end and evidence["start"] < start < evidence["end"]):
            return True
    return False


def _one_sided_edit(evidence, opcodes, side):
    tag = "delete" if side == "before" else "insert"
    for operation, a, b, c, d in opcodes:
        start, end = (a, b) if side == "before" else (c, d)
        if operation == tag and start <= evidence["start"] < evidence["end"] <= end:
            return True
    return False


def _relocated(left, right, before, after):
    """Establish paragraph order change, not a mere shifted character offset."""
    blocks = lambda text: [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    old, new = blocks(left['quote']), blocks(right['quote'])
    if left['quote'] != right['quote']:
        return len(old) >= 2 and old != new and Counter(old) == Counter(new)
    if left['start'] == right['start']:
        return False
    # An unchanged anchor must cross the cited text. Prefix insertion/deletion
    # alone therefore cannot be mislabeled as a structural move.
    common = set(blocks(before)) & set(blocks(after))
    for anchor in common:
        if anchor in left['quote'] or before.count(anchor) != 1 or after.count(anchor) != 1:
            continue
        if (before.find(anchor) - left['start']) * (after.find(anchor) - right['start']) < 0:
            return True
    return False


def apply_model_output(comparison: dict, output: dict, *, model: str,
                       provenance: dict | None = None) -> dict:
    """Return a new validated comparison, replacing (never mutating) its changes.

    Native imports default to unpriced existing-account credits, not $0. Missing
    native usage/time is explicitly marked unavailable; required numeric fields
    are zero placeholders, not measurements. Supply provenance for real metadata.
    """
    errors = validate(comparison)
    if errors:
        raise ModelError("input comparison failed validation: " + "; ".join(errors))
    if not isinstance(model, str) or not model.strip():
        raise ModelError("an explicit model is required")
    if provenance is not None and not isinstance(provenance, dict):
        raise ModelError("provenance must be an object")
    meta = copy.deepcopy(provenance or {})
    method = meta.get("method", "native_codex")
    if method not in ("native_codex", "openai_responses"):
        raise ModelError("unsupported analysis method")
    if not isinstance(output, dict) or set(output) != {"changes", "warnings"}:
        raise ModelError("model output requires only changes and warnings")
    if not isinstance(output["changes"], list) or len(output["changes"]) > 2000:
        raise ModelError("changes must be a list of at most 2000 items")
    if not isinstance(output["warnings"], list) or any(not isinstance(w, str) for w in output["warnings"]):
        raise ModelError("warnings must be a list of strings")
    before, after = comparison["before"]["text"], comparison["after"]["text"]
    if max(len(before), len(after)) > 20_000:
        raise ModelError('model import is limited to 20,000 code points per source')
    # Bounded exact alignment avoids autojunk treating common regulatory letters
    # as noise. This alignment locates edits; it cannot certify their meaning.
    opcodes = difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
    changes = []
    seen = set()
    fields = {"category", "summary", "before_quote", "after_quote", "needs_review", "review_reason"}
    for item in output["changes"]:
        if not isinstance(item, dict) or set(item) != fields:
            raise ModelError("each change must match the exact output schema")
        category = item["category"]
        if not isinstance(category, str) or category not in CATEGORIES:
            raise ModelError("invalid change category")
        if not isinstance(item["summary"], str) or not item["summary"].strip():
            raise ModelError("summary must be nonempty")
        if type(item["needs_review"]) is not bool:
            raise ModelError("needs_review must be boolean")
        reason = item["review_reason"]
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ModelError("review_reason must be a nonempty string or null")
        if item["needs_review"] and reason is None:
            raise ModelError("review_reason required for needs_review")
        left = _evidence(before, item["before_quote"], "before")
        right = _evidence(after, item["after_quote"], "after")
        alignment_reason = None
        if category == "added":
            if left is not None or right is None:
                raise ModelError("added requires only after evidence")
            if right["quote"] in before:
                raise ModelError("false addition: after quote already present before")
            if not _one_sided_edit(right, opcodes, "after"):
                alignment_reason = 'One-sided evidence overlaps a complex revision; review addition versus replacement.'
        elif category == "removed":
            if right is not None or left is None:
                raise ModelError("removed requires only before evidence")
            if left["quote"] in after:
                raise ModelError("false removal: before quote still present after")
            if not _one_sided_edit(left, opcodes, "before"):
                alignment_reason = 'One-sided evidence overlaps a complex revision; review removal versus replacement.'
        elif category == 'editorial' and (left is None) != (right is None):
            # A source notice or publication citation can be added or removed
            # without becoming a new requirement. Category and direction differ.
            present = right if right is not None else left
            other = before if right is not None else after
            if present['quote'] in other:
                raise ModelError('one-sided editorial quote is unchanged on the other side')
        else:
            if left is None or right is None:
                raise ModelError("paired category requires both evidence sides")
            if category == "moved":
                if not _relocated(left, right, before, after):
                    raise ModelError("move requires an established paragraph order change")
            elif left["quote"] == right["quote"]:
                raise ModelError("no textual change in cited spans")
            elif not (_touches(left, opcodes, "before") or _touches(right, opcodes, "after")):
                raise ModelError("no textual change in cited spans")
        identity = (category, item["before_quote"], item["after_quote"])
        if identity in seen:
            raise ModelError("duplicate model claim")
        seen.add(identity)
        changes.append({"id": f"change-{len(changes) + 1}", "category": category,
                        "summary": item["summary"], "before_evidence": left,
                        "after_evidence": right, "needs_review": item["needs_review"] or alignment_reason is not None,
                        "review_reason": '; '.join(x for x in (reason, alignment_reason) if x) or None, "method": method})
    analysis = {
        "method": method, "model": model, "prompt_version": meta.get("prompt_version"),
        "generated_at": meta.get("generated_at", datetime.now(timezone.utc).isoformat()),
        "latency_ms": meta.get("latency_ms", 0),
        "input_tokens": meta.get("input_tokens", 0),
        "output_tokens": meta.get("output_tokens", 0),
        "usage_available": meta.get("usage_available", "input_tokens" in meta and "output_tokens" in meta),
        "latency_available": meta.get("latency_available", "latency_ms" in meta),
        "cost_usd": meta.get("cost_usd"),
        "billing_basis": meta.get("billing_basis", "unpriced existing account credits" if method == "native_codex" else "unpriced API cost"),
    }
    if any(type(analysis[key]) is not bool for key in ("usage_available", "latency_available")):
        raise ModelError("metadata availability flags must be boolean")
    if analysis["usage_available"] and not all(key in meta for key in ("input_tokens", "output_tokens")):
        raise ModelError("available usage requires both measured token counts")
    if analysis["latency_available"] and "latency_ms" not in meta:
        raise ModelError("available latency requires measured latency_ms")
    if method == "openai_responses" and not all(key in meta for key in (
            "prompt_version", "latency_ms", "input_tokens", "output_tokens", "cost_usd", "billing_basis")):
        raise ModelError("API provenance requires prompt, timing, usage and billing metadata")
    result = copy.deepcopy(comparison)
    warnings = list(dict.fromkeys(comparison["warnings"] + output["warnings"]))
    result.update(changes=changes, warnings=warnings, analysis=analysis)
    errors = validate(result)
    if errors:
        raise ModelError("enriched comparison failed validation: " + "; ".join(errors))
    return result


def _decimal(value, name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise BudgetError(f"{name} must be an explicit positive finite number") from None
    if not result.is_finite() or result <= 0:
        raise BudgetError(f"{name} must be an explicit positive finite number")
    return result


@dataclass(frozen=True)
class TokenRates:
    """Caller-verified USD per million input/output tokens; no default rates."""
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal

    def __post_init__(self):
        object.__setattr__(self, "input_usd_per_million", _decimal(self.input_usd_per_million, "input rate"))
        object.__setattr__(self, "output_usd_per_million", _decimal(self.output_usd_per_million, "output rate"))

    def cost_nano_usd(self, input_tokens, output_tokens):
        # Integer nano-USD, rounding UP, avoids budget float undercounting.
        return int(((self.input_usd_per_million * input_tokens +
                     self.output_usd_per_million * output_tokens) * 1000).to_integral_value(rounding=ROUND_CEILING))


class BudgetLedger:
    """Persistent, concurrent-safe reservations, capped at USD10 with no retry.

    Unknown/failed outcomes retain their full reservation. Reopening never resets
    spending, request count, deadline, or configured limits. No secrets are stored.
    The caller must reuse ONE ledger for a run; separate ledgers are separate caps.
    """

    def __init__(self, path: str | Path, *, cap_usd="10", max_requests=20, max_seconds=600):
        cap = _decimal(cap_usd, "cap_usd")
        if cap > 10 or type(max_requests) is not int or not 1 <= max_requests <= 100:
            raise BudgetError("cap must be <= USD10 and max_requests within 1..100")
        if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or not 0 < max_seconds <= 600:
            raise BudgetError("max_seconds must be within (0, 600]")
        if str(path) == ":memory:":
            raise BudgetError("a persistent ledger path is required")
        self.path = str(path)
        # Never round a caller's cap upward, even by a fraction of a nano-USD.
        cap_nano = int(cap * 1_000_000_000)
        if cap_nano < 1:
            raise BudgetError("cap_usd must be at least one nano-USD")
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS limits (id INTEGER PRIMARY KEY CHECK(id=1), cap INTEGER, requests INTEGER, seconds REAL, deadline REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, reserved INTEGER NOT NULL, charged INTEGER NOT NULL, state TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO limits VALUES (1,?,?,?,?)", (cap_nano, max_requests, max_seconds, time.time() + max_seconds))
            limits = db.execute("SELECT cap, requests, seconds FROM limits WHERE id=1").fetchone()
            if limits != (cap_nano, max_requests, max_seconds):
                raise BudgetError("existing ledger limits differ; cannot reset or widen")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def snapshot(self):
        """Read-only accounting; this method never creates requests."""
        with self._connect() as db:
            amount, count = db.execute("SELECT COALESCE(SUM(charged),0),COUNT(*) FROM calls").fetchone()
            cap, requests, _, deadline = db.execute("SELECT cap,requests,seconds,deadline FROM limits WHERE id=1").fetchone()
        return {"charged_or_reserved_usd": amount / 1_000_000_000, "requests": count,
                "cap_usd": cap / 1_000_000_000, "max_requests": requests,
                "seconds_remaining": max(0, deadline - time.time())}

    def reserve(self, nano_usd):
        if type(nano_usd) is not int or nano_usd <= 0:
            raise BudgetError("positive integer reservation required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cap, requests, _, deadline = db.execute("SELECT cap,requests,seconds,deadline FROM limits WHERE id=1").fetchone()
            amount, count = db.execute("SELECT COALESCE(SUM(charged),0),COUNT(*) FROM calls").fetchone()
            if time.time() >= deadline or count >= requests or amount + nano_usd > cap:
                raise BudgetError("budget, request count, or time limit exhausted before network")
            cursor = db.execute("INSERT INTO calls(reserved,charged,state) VALUES (?,?,'unknown')", (nano_usd, nano_usd))
            return cursor.lastrowid, deadline - time.time()

    def settle(self, identifier, actual_nano_usd):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT reserved,state FROM calls WHERE id=?", (identifier,)).fetchone()
            if row is None or row[1] != "unknown" or type(actual_nano_usd) is not int or actual_nano_usd < 0:
                raise BudgetError("invalid or already settled reservation")
            if actual_nano_usd > row[0]:
                # Unexpected accounting never creates refundable headroom.
                db.execute("UPDATE limits SET deadline=0 WHERE id=1")
                db.execute("UPDATE calls SET charged=?,state='overrun' WHERE id=?", (actual_nano_usd, identifier))
            else:
                db.execute("UPDATE calls SET charged=?,state='complete' WHERE id=?", (actual_nano_usd, identifier))
        if actual_nano_usd > row[0]:
            raise BudgetError("usage exceeded reservation; ledger closed to further calls")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_response(handle, deadline):
    """Bound bytes and tighten the stdlib HTTP socket timeout as time runs out."""
    chunks, size = [], 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModelError("OpenAI response time limit exceeded")
        sock = getattr(getattr(getattr(handle, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            sock.settimeout(remaining)
        # HTTPResponse.read1 does at most one underlying read, so slow trickles
        # cannot restart the full request timeout for every received chunk.
        chunk = handle.read1(min(65_536, MAX_RESPONSE_BYTES + 1 - size))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise ModelError("OpenAI response exceeds byte limit")


def _parse_response(response):
    if not isinstance(response, dict) or response.get("status") != "completed":
        raise ModelError("OpenAI response refused, incomplete, or failed")
    texts = []
    if not isinstance(response.get("output"), list):
        raise ModelError("malformed OpenAI output list")
    for item in response["output"]:
        if not isinstance(item, dict):
            raise ModelError("malformed OpenAI output")
        if item.get("type") != "message":
            continue  # Reasoning metadata is not a model answer.
        if item.get("status", "completed") != "completed":
            raise ModelError("incomplete OpenAI message")
        if not isinstance(item.get("content"), list):
            raise ModelError("malformed OpenAI message content")
        for content in item["content"]:
            if not isinstance(content, dict) or content.get("type") != "output_text":
                raise ModelError("OpenAI refusal or unsupported message content")
            texts.append(content.get("text"))
    if len(texts) != 1 or not isinstance(texts[0], str):
        raise ModelError("expected exactly one structured OpenAI output_text")
    usage = response.get("usage")
    if not isinstance(usage, dict) or any(type(usage.get(key)) is not int or usage[key] < 0 for key in ("input_tokens", "output_tokens")):
        raise ModelError("missing or malformed OpenAI token usage")
    if not isinstance(response.get("model"), str) or not response["model"].strip():
        raise ModelError("missing OpenAI response model")
    return _loads(texts[0]), usage


def analyze_openai(comparison: dict, *, model: str, rates: TokenRates,
                   ledger: BudgetLedger, max_output_tokens=2048,
                   timeout_seconds=30) -> dict:
    """One explicitly configured, store:false Responses request; never retries.

    This is opt-in, API-key-only functionality. Existing account credit imports
    should use apply_model_output instead, with no standalone API spending.
    """
    if not isinstance(model, str) or not model.strip() or validate(comparison):
        raise ModelError("explicit model and valid comparison required")
    if not isinstance(rates, TokenRates) or not isinstance(ledger, BudgetLedger):
        raise ModelError("explicit TokenRates and persistent BudgetLedger required")
    if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 8192:
        raise ModelError("max_output_tokens must be within 1..8192")
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60:
        raise ModelError("timeout_seconds must be within (0, 60]")
    key = os.environ.get("OPENAI_API_KEY")
    if not key or not key.strip():
        raise ModelError("OPENAI_API_KEY is required; no other credential source is used")
    contract = build_model_input(comparison)
    payload = {
        "model": model, "store": False, "max_output_tokens": max_output_tokens,
        "instructions": contract["instructions"],
        "input": json.dumps(contract["input"], ensure_ascii=False, allow_nan=False),
        "text": {"format": {"type": "json_schema", "name": "change_analysis",
                            "schema": contract["output_schema"], "strict": True}},
    }
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(body) > 1_000_000:
        raise ModelError("model request exceeds 1,000,000 UTF8 bytes")
    # A byte per token is conservative for input UTF8; include the entire wire
    # schema and additional framing allowance, never use len(text)/4 estimates.
    input_bound = len(body) + 4096
    reserved = rates.cost_nano_usd(input_bound, max_output_tokens)
    identifier, remaining = ledger.reserve(reserved)
    started = time.monotonic()
    try:
        request = urllib.request.Request("https://api.openai.com/v1/responses", data=body,
                                         headers={"Authorization": "Bearer " + key,
                                                  "Content-Type": "application/json"}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=min(timeout_seconds, remaining)) as handle:
            if handle.status != 200:
                raise ModelError("OpenAI request failed")
            raw = _read_response(handle, started + min(timeout_seconds, remaining))
    except Exception:
        # Never echo credential-bearing headers, exception messages, or bodies.
        raise ModelError("OpenAI request failed; conservative reservation retained") from None
    elapsed = (time.monotonic() - started) * 1000
    if elapsed > min(timeout_seconds, remaining) * 1000:
        raise ModelError("OpenAI request exceeded time limit; reservation retained")
    response = _loads(raw)
    output, usage = _parse_response(response)
    if usage["input_tokens"] > input_bound or usage["output_tokens"] > max_output_tokens:
        raise ModelError("OpenAI usage exceeded reserved token bounds; reservation retained")
    cost = rates.cost_nano_usd(usage["input_tokens"], usage["output_tokens"])
    result = apply_model_output(comparison, output, model=response["model"], provenance={
        "method": "openai_responses", "prompt_version": PROMPT_VERSION,
        "latency_ms": round(elapsed, 3), "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"], "cost_usd": cost / 1_000_000_000,
        "billing_basis": "caller-supplied USD per million token rates; no cache discount assumed",
    })
    ledger.settle(identifier, cost)
    return result
