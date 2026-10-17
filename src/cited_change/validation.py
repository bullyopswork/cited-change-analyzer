"""Strict source-bound quote validation; not a semantic explanation verifier."""

from __future__ import annotations

import math
from datetime import datetime

from .extraction import check_metadata

CATEGORIES = frozenset({"amount", "date", "requirement", "wording", "added",
                        "removed", "editorial", "moved"})


def validate(report: object) -> list[str]:
    """Return errors. An empty list certifies structure/quotes only, not meaning."""
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["report must be an object"]
    if report.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    for field in ("id", "section", "title", "corpus"):
        if not isinstance(report.get(field), str):
            errors.append(f"{field} must be a string")
    for field in ("id", "section"):
        if not report.get(field):
            errors.append(f"{field} must be nonempty")
    texts: dict[str, str] = {}
    for side in ("before", "after"):
        source = report.get(side)
        if not isinstance(source, dict):
            errors.append(f"{side} must be an object")
            continue
        try:
            check_metadata(source)
        except (ValueError, TypeError, AttributeError) as error:
            errors.append(f"{side}: {error}")
        if not isinstance(source.get("text"), str):
            errors.append(f"{side}.text must be a string")
        else:
            texts[side] = source["text"]
    changes = report.get("changes")
    if not isinstance(changes, list):
        errors.append("changes must be a list")
        changes = []
    ids = set()
    for index, change in enumerate(changes):
        prefix = f"changes[{index}]"
        if not isinstance(change, dict):
            errors.append(f"{prefix} must be an object")
            continue
        identifier = change.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            errors.append(f"{prefix}.id must be a unique nonempty string")
        else:
            ids.add(identifier)
        category = change.get("category")
        if not isinstance(category, str) or category not in CATEGORIES:
            errors.append(f"{prefix}.category is invalid")
        for field in ("summary", "method"):
            if not isinstance(change.get(field), str) or not change[field]:
                errors.append(f"{prefix}.{field} must be a nonempty string")
        if not isinstance(change.get("needs_review"), bool):
            errors.append(f"{prefix}.needs_review must be boolean")
        if "review_reason" not in change or (change["review_reason"] is not None and
                                             not isinstance(change["review_reason"], str)):
            errors.append(f"{prefix}.review_reason must be null or a string")
        if change.get("needs_review") is True and not change.get("review_reason"):
            errors.append(f"{prefix}.review_reason is required when review is needed")
        for side in ("before", "after"):
            key = f"{side}_evidence"
            if key not in change:
                errors.append(f"{prefix}.{key} is required")
                continue
            evidence = change[key]
            if evidence is None:
                continue
            if not isinstance(evidence, dict):
                errors.append(f"{prefix}.{key} must be an object or null")
                continue
            a, b, quote = evidence.get("start"), evidence.get("end"), evidence.get("quote")
            if type(a) is not int or type(b) is not int or not isinstance(quote, str):
                errors.append(f"{prefix}.{key} requires integer offsets and string quote")
                continue
            text = texts.get(side)
            if text is not None:
                if not 0 <= a < b <= len(text):
                    errors.append(f"{prefix}.{key} offsets outside source or empty")
                elif text[a:b] != quote:
                    errors.append(f"{prefix}.{key} quote does not match exact source slice")
        left, right = change.get("before_evidence"), change.get("after_evidence")
        if left is None and right is None:
            errors.append(f"{prefix} needs at least one source evidence")
        if category == "added" and (left is not None or right is None):
            errors.append(f"{prefix}: added text must have only after evidence")
        if category == "removed" and (right is not None or left is None):
            errors.append(f"{prefix}: removed text must have only before evidence")
        if isinstance(category, str) and category in CATEGORIES - {"added", "removed", "editorial"} and (left is None or right is None):
            errors.append(f"{prefix}: paired change requires both source evidence")
    warnings = report.get("warnings")
    if not isinstance(warnings, list) or any(not isinstance(w, str) for w in warnings):
        errors.append("warnings must be a list of strings")
    analysis = report.get("analysis")
    if not isinstance(analysis, dict):
        errors.append("analysis must be an object")
    else:
        if not isinstance(analysis.get("method"), str) or not analysis.get("method"):
            errors.append("analysis.method must be a nonempty string")
        for key in ("model", "prompt_version"):
            if key not in analysis or (analysis[key] is not None and not isinstance(analysis[key], str)):
                errors.append(f"analysis.{key} must be null or a string")
        try:
            generated = datetime.fromisoformat(analysis.get("generated_at", "").replace("Z", "+00:00"))
            if generated.tzinfo is None:
                raise ValueError("timezone required")
        except (ValueError, TypeError, AttributeError):
            errors.append("analysis.generated_at must be an ISO8601 timestamp with timezone")
        for key in ("latency_ms", "cost_usd", "input_tokens", "output_tokens"):
            value = analysis.get(key)
            if key == "cost_usd" and value is None and key in analysis:
                basis = analysis.get("billing_basis")
                if not isinstance(basis, str) or not basis.strip():
                    errors.append("analysis.cost_usd null requires a nonempty billing_basis")
                continue
            if (type(value) not in (int, float) or value < 0 or
                    (type(value) is float and not math.isfinite(value))):
                errors.append(f"analysis.{key} must be a finite nonnegative number")
            elif key.endswith("tokens") and type(value) is not int:
                errors.append(f"analysis.{key} must be an integer")
    return errors
