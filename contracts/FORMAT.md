# Comparison format, v1

The Python engine and TypeScript viewer share the following JSON contracts. Python Unicode code point offsets are converted by the viewer using Array.from before slicing, so non ASCII characters remain aligned. Offsets are half open.

## Comparison

```json
{
  "schema_version": "1.0",
  "id": "301-10.1__2025-12-07__2025-12-08",
  "section": "301-10.1",
  "title": "What is my general policy?",
  "corpus": "41 CFR Part 301-10",
  "before": {"date":"2025-12-07","url":"https://www.ecfr.gov/on/2025-12-07/title-41/section-301-10.1","snapshot_sha256":"hex","text":"Earlier passage."},
  "after": {"date":"2025-12-08","url":"https://www.ecfr.gov/on/2025-12-08/title-41/section-301-10.1","snapshot_sha256":"hex","text":"Later passage."},
  "changes": [{"id":"change-1","category":"wording","summary":"Text revised.","before_evidence":{"start":0,"end":7,"quote":"Earlier"},"after_evidence":{"start":0,"end":5,"quote":"Later"},"needs_review":false,"review_reason":null,"method":"deterministic"}],
  "warnings": [],
  "analysis": {"method":"deterministic","model":null,"prompt_version":null,"generated_at":"ISO8601","latency_ms":0,"input_tokens":0,"output_tokens":0,"cost_usd":0}
}
```

Categories: amount, date, requirement, wording, added, removed, editorial, moved. Each evidence field is either the complete object above or null. One sided added and removed text uses null on the absent side. Empty text with a dated valid source denotes a section absent from that snapshot, not a failed fetch. Fetch failure must stop production of a comparison. Citation validity means the quote equals text[start:end]; it does not certify the semantic explanation.

Editorial findings may also be one sided, for example an added amendment notice. An addition/removal overlapping a complex replacement is flagged for review, not automatically certified from a lexical alignment. Unknown dollar cost is null with an explicit billing_basis. Native batch usage is recorded at batch level; per-case zero placeholders are not measured usage when usage_available or latency_available is false. Render these as unavailable, not free inference.

## catalog.json

```json
{"schema_version":"1.0","title":"Cited Change Analyzer","corpus":"41 CFR Part 301-10","generated_at":"ISO8601","description":"Factual textual changes with source evidence.","comparisons":[{"id":"...","section":"301-10.1","title":"...","before_date":"2025-12-07","after_date":"2025-12-08","change_count":1,"categories":["wording"],"path":"comparisons/ID.json","method":"deterministic"}]}
```

Paths resolve relative to data/. Comparisons are curated valid available date pairs, not arbitrary on demand live inference. Section and date selection must only offer existing combinations and clearly label the curated archive. Evaluation lives at data/evaluation.json, and is never invented if absent.

## Evaluation presentation

The evaluation JSON may contain status, dataset, splits, methods, metrics, latency, cost, failures, methodology, and generated_at. Until actual evaluation exists the viewer must show unavailable, not demo success metrics. UI work may use an explicitly labeled illustrative fixture, kept out of the real public catalog.
