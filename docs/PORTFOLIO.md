# Portfolio walkthrough

## Short description

Built an installable Python and TypeScript tool for comparing local TXT and selectable text PDF documents, with exact source highlights, PDF page provenance and report exports. Packaged the complete browser interface in a Python wheel, added bounded offline processing and optional user owned API integration, and retained a separate reproducible regulatory AI evaluation. Live provider verification of the optional v0.2 API path is still pending access to a developer credential.

## Local application demonstration

1. Install the released wheel in a clean Python environment, without Node or Docker.
2. Launch the local browser interface and select two synthetic TXT or PDF files.
3. Compare without an API key, inspect the extracted sources and select a cited change.
4. Show PDF page references and export the report.
5. Explain the explicit optional own-key API boundary and its current verification status.

## Archive demonstration

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
