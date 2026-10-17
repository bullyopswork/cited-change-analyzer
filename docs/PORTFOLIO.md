# Portfolio walkthrough

## Short description

Built a Python and TypeScript document comparison tool that explains factual edits with exact dated source evidence. Implemented XML ingestion, Unicode span validation, SQLite provenance, a responsive review interface and a reproducible evaluation with raw AI outputs and independent agent source reviews.

## Demonstration

1. Open a real archived comparison and select a finding.
2. Show its earlier and later quotations, version dates and original sources.
3. Filter findings and download the HTML or JSON report.
4. Switch to the evaluation view and compare strict and collective coverage.
5. Explain one known heading miss and one category ambiguity instead of presenting a benchmark as a universal guarantee.

## Engineering decisions to discuss

1. Kept model inference outside the visitor request path, so the demo works without visitor keys or model charges.
2. Separated source quotation validity from semantic correctness. Exact evidence prevents fabricated quotes, not every unsupported interpretation.
3. Preserved raw model outputs, frozen labels and uncomfortable evaluation results instead of tuning test labels after seeing predictions.
4. Used deterministic alignment for evidence and AI for explanations, while retaining lexical baselines and explicit review states.
5. Made API usage optional and budget reserved. Recorded native account credits as unpriced rather than calling them free.

The project is an AI assisted build. Source annotation and evaluation are agent reviewed, not an independent human legal assessment. No customer adoption, market novelty or production compliance outcome is claimed.
