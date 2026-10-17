"""Opt-in user-key API enrichment, bounded independently of local comparison.

Only OPENAI_API_KEY is consulted for credential presence. Neither the key nor
transport exception text is returned. Windows use Python code-point coordinates;
no normalization, concatenation, or fabricated source URLs are involved.
"""
from __future__ import annotations

import copy
import os
import re
from decimal import Decimal, InvalidOperation

from .model import BudgetError, BudgetLedger, ModelError, TokenRates, analyze_openai
from .validation import validate

MAX_SOURCE_CHARACTERS = 100_000
MAX_WINDOW_CHARACTERS = 20_000
MAX_REQUESTS = 8
CONTEXT_CHARACTERS = 384


def _configuration():
    """Return a public configuration and private rate objects, never a key."""
    public = {"configured": False, "model": None, "cap_usd": None, "reason": None}
    model = os.environ.get("OPENAI_MODEL", "").strip()
    if not model or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model) or model.startswith("sk-"):
        public["reason"] = "Set OPENAI_MODEL to an explicit API model identifier."
        return public, None
    public["model"] = model
    try:
        cap = Decimal(os.environ.get("CCA_API_CAP_USD", "1"))
        if not cap.is_finite() or not Decimal("0.000000001") <= cap <= 10:
            raise ValueError
        # Canonical decimal text, not binary float or exponent notation.
        public["cap_usd"] = format(cap, "f")
    except (InvalidOperation, ValueError):
        public["reason"] = "CCA_API_CAP_USD must be a positive USD amount from 0.000000001 through 10."
        return public, None
    try:
        rates = TokenRates(os.environ.get("OPENAI_INPUT_USD_PER_MILLION"),
                           os.environ.get("OPENAI_OUTPUT_USD_PER_MILLION"))
    except (ModelError, ValueError):
        public["reason"] = ("Set positive, finite OPENAI_INPUT_USD_PER_MILLION and "
                            "OPENAI_OUTPUT_USD_PER_MILLION rates for your selected model.")
        return public, None
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        public["reason"] = "Set your own OPENAI_API_KEY in the local server environment; no other credential source is used."
        return public, None
    public.update(configured=True)
    return public, rates


def get_ai_configuration() -> dict:
    """JSON-safe setup information; makes no requests and reads no files."""
    return _configuration()[0]


def _notify(progress, message):
    if progress is not None:
        try:
            progress(message)
        except Exception:
            # An optional UI progress callback must not discard the local result.
            pass


def _bounds(changes, side):
    spans = [change[side + "_evidence"] for change in changes if change[side + "_evidence"] is not None]
    if not spans:
        return None
    return min(item["start"] for item in spans), max(item["end"] for item in spans)


def _fits(changes):
    return all(bounds is None or bounds[1] - bounds[0] <= MAX_WINDOW_CHARACTERS
               for bounds in (_bounds(changes, "before"), _bounds(changes, "after")))


def _plan(report):
    """Partition complete local claims, never truncate or silently drop one."""
    changes = report["changes"]
    if max(len(report[side]["text"]) for side in ("before", "after")) <= MAX_WINDOW_CHARACTERS:
        return [list(range(len(changes)))], []
    groups, current, skipped = [], [], []
    for index, change in enumerate(changes):
        if not _fits([change]):
            skipped.append(index)
            continue
        if current and not _fits([changes[i] for i in current] + [change]):
            groups.append(current)
            current = []
        current.append(index)
    if current:
        groups.append(current)
    # Keep every excess claim in the deterministic result, with reported counts.
    for group in groups[MAX_REQUESTS:]:
        skipped.extend(group)
    return groups[:MAX_REQUESTS], skipped


def _window(report, indices, full):
    chunk = copy.deepcopy(report)
    origins = {}
    selected = [report["changes"][index] for index in indices]
    for side in ("before", "after"):
        text = report[side]["text"]
        if full:
            start, end = 0, len(text)
        else:
            bounds = _bounds(selected, side)
            if bounds is None:
                # One-sided edits need some opposite-side context. This is only
                # context, not asserted alignment; global addition/removal checks
                # below prevent treating out-of-window text as newly absent.
                bounds = (0, 0)
            a, b = bounds
            spare = MAX_WINDOW_CHARACTERS - (b - a)
            padding = min(CONTEXT_CHARACTERS, spare // 2)
            start, end = max(0, a - padding), min(len(text), b + padding)
            if start == end and text:
                start, end = 0, min(len(text), CONTEXT_CHARACTERS)
        origins[side] = start
        chunk[side]["text"] = text[start:end]
        if chunk[side].get("source_kind") == "local" and not full:
            # The request contains a verbatim text excerpt, not a whole PDF.
            # Retain filename/hash/date; full PDF page ranges stay in the result.
            chunk[side]["format"] = "text"
            chunk[side].pop("pages", None)
    chunk["changes"] = []  # Model prompt uses sources, not prior classifications.
    if not full:
        chunk["section"] += " (bounded excerpts; infer changes only within these excerpts)"
    if validate(chunk):
        raise ModelError("AI source window could not be validated")
    return chunk, origins


def _overlaps(left, right):
    return left is not None and right is not None and left["start"] < right["end"] and right["start"] < left["end"]


def _mapped_changes(result, report, indices, origins, full):
    if validate(result):
        raise ModelError("AI response failed source validation")
    mapped = copy.deepcopy(result["changes"])
    for change in mapped:
        for side in ("before", "after"):
            evidence = change[side + "_evidence"]
            if evidence is not None:
                evidence["start"] += origins[side]
                evidence["end"] += origins[side]
                if report[side]["text"][evidence["start"]:evidence["end"]] != evidence["quote"]:
                    raise ModelError("AI evidence failed full-source mapping")
        left, right = change["before_evidence"], change["after_evidence"]
        if change["category"] == "added" and right["quote"] in report["before"]["text"]:
            raise ModelError("AI addition is present in the full earlier source")
        if change["category"] == "removed" and left["quote"] in report["after"]["text"]:
            raise ModelError("AI removal is present in the full revised source")
        if not full:
            # Reject claims about window boundaries or unrelated context, even if
            # the source slices are exact. Both paired sides must touch a target.
            for side in ("before", "after"):
                evidence = change[side + "_evidence"]
                if evidence is not None and not any(
                        _overlaps(evidence, report["changes"][i][side + "_evidence"]) for i in indices):
                    raise ModelError("AI claim is outside the selected local changes")
            change["needs_review"] = True
            reason = "Bounded source excerpts were analyzed; review in the complete documents."
            change["review_reason"] = "; ".join(filter(None, (change["review_reason"], reason)))
    return mapped


def _covered(evidence, claims, side):
    if evidence is None:
        return True
    end = evidence["start"]
    spans = sorted((item[side + "_evidence"]["start"], item[side + "_evidence"]["end"])
                   for item in claims if item[side + "_evidence"] is not None)
    for a, b in spans:
        if a > end:
            break
        end = max(end, b)
        if end >= evidence["end"]:
            return True
    return False


def enrich_local_report(report: dict, ledger_path, progress=None) -> dict:
    """Return a validated copy with bounded API claims and retained local work.

    The caller owns explicit consent and its outer process deadline. Requests
    share a persistent 8-call/600-second ledger, reserve cost before transport,
    and never retry. Errors expose fixed messages, never exception details.
    ``analysis.ai_coverage`` describes partial/unavailable work and reservations.
    """
    if validate(report):
        raise ModelError("A validated local comparison is required for AI analysis")
    if max(len(report[side]["text"]) for side in ("before", "after")) > MAX_SOURCE_CHARACTERS:
        raise ModelError("Local AI sources are limited to 100000 code points each")
    original = copy.deepcopy(report)
    result = copy.deepcopy(report)
    configuration, rates = _configuration()
    coverage = {"status": "unavailable", "local_changes": len(report["changes"]),
                "covered_local_changes": 0, "retained_local_changes": len(report["changes"]),
                "planned_chunks": 0, "attempted_chunks": 0, "succeeded_chunks": 0,
                "failed_chunks": 0, "skipped_local_changes": 0}
    result["analysis"]["ai_coverage"] = coverage
    warnings = result["warnings"]
    if not configuration["configured"]:
        warnings.append("Optional AI unavailable: " + configuration["reason"])
        return result
    if not report["changes"]:
        coverage["status"] = "complete"
        warnings.append("No local changes were identified; no document content was sent for optional AI analysis.")
        return result
    groups, skipped = _plan(report)
    coverage.update(planned_chunks=len(groups), skipped_local_changes=len(skipped))
    if skipped:
        warnings.append(f"AI partial coverage: {len(skipped)} local changes exceed the source-window or eight-request limit and remain local.")
    try:
        ledger = BudgetLedger(ledger_path, cap_usd=configuration["cap_usd"],
                              max_requests=MAX_REQUESTS, max_seconds=600)
    except Exception:
        warnings.append("Optional AI unavailable: persistent budget ledger could not be opened with the configured limits. Local changes retained.")
        return result
    collected, covered, analyses = [], set(), []
    full = max(len(report[side]["text"]) for side in ("before", "after")) <= MAX_WINDOW_CHARACTERS
    for number, indices in enumerate(groups, 1):
        _notify(progress, f"Analyzing optional AI section {number} of {len(groups)}")
        coverage["attempted_chunks"] += 1
        try:
            chunk, origins = _window(original, indices, full)
            enriched = analyze_openai(chunk, model=configuration["model"], rates=rates,
                                      ledger=ledger, max_output_tokens=4096, timeout_seconds=20)
            mapped = _mapped_changes(enriched, original, indices, origins, full)
            collected.extend(mapped)
            analyses.append(enriched["analysis"])
            warnings.extend(enriched["warnings"])
            for index in indices:
                if all(_covered(original["changes"][index][side + "_evidence"], mapped, side)
                       for side in ("before", "after")):
                    covered.add(index)
            coverage["succeeded_chunks"] += 1
        except BudgetError:
            coverage["failed_chunks"] += 1
            warnings.append("AI partial coverage: budget, request, or time limit prevented this section; local changes retained. No retry was made.")
            break
        except Exception:
            coverage["failed_chunks"] += 1
            warnings.append("AI partial coverage: this section failed or its evidence was rejected; local changes retained. No retry was made; any reservation remains charged conservatively.")
    retained = [change for i, change in enumerate(original["changes"]) if i not in covered]
    coverage.update(covered_local_changes=len(covered), retained_local_changes=len(retained))
    coverage["status"] = ("complete" if len(covered) == len(original["changes"]) else
                          "partial" if coverage["succeeded_chunks"] else "unavailable")
    if retained:
        warnings.append(f"AI coverage incomplete: {len(retained)} local changes remain because AI did not fully cover their exact evidence. Local findings are not silently removed.")
    # Deduplicate overlapping-window claims only when category AND exact spans
    # agree; repeated text at different source coordinates remains distinct.
    changes, seen = [], set()
    for change in retained + collected:
        key = (change["category"],) + tuple(
            None if change[side + "_evidence"] is None else
            (change[side + "_evidence"]["start"], change[side + "_evidence"]["end"])
            for side in ("before", "after"))
        if key not in seen:
            changes.append(change)
            seen.add(key)
    for index, change in enumerate(changes, 1):
        change["id"] = f"change-{index}"
    result["changes"] = changes
    if analyses:
        aggregate = copy.deepcopy(analyses[-1])
        for field in ("latency_ms", "input_tokens", "output_tokens", "cost_usd"):
            aggregate[field] = sum(analysis[field] for analysis in analyses)
        aggregate["billing_basis"] = ("Measured successful API requests only; failed outcomes retain conservative reservations in ai_coverage.budget. "
                                      "Caller-supplied token rates; no cache discount assumed.")
        aggregate["ai_coverage"] = coverage
        result["analysis"] = aggregate
    else:
        # Failed calls may cost money; a deterministic $0 must not imply free API.
        result["analysis"].update(cost_usd=None, usage_available=False,
                                    billing_basis="No completed measured AI usage; conservative reservations, if any, are recorded in ai_coverage.budget.")
    try:
        coverage["budget"] = ledger.snapshot()
    except Exception:
        warnings.append("AI budget accounting could not be read; do not assume unused funds or retry automatically.")
    result["warnings"] = list(dict.fromkeys(warnings))
    if validate(result):
        # Defensive fail-closed return: preserve source and original findings.
        fallback = copy.deepcopy(original)
        fallback["warnings"].append("Optional AI result failed final validation; all local findings retained.")
        fallback["analysis"].update(
            cost_usd=None, usage_available=False,
            billing_basis="AI output was rejected; any measured or reserved costs remain in ai_coverage.budget.",
            ai_coverage={**coverage, "status": "unavailable", "covered_local_changes": 0,
                         "retained_local_changes": len(original["changes"])})
        return fallback
    return result
