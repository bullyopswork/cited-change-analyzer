# Architecture

The application separates source identity, textual change detection, AI explanation and evaluation. A successful quote check is not a semantic accuracy judgment.

## Installed local application, v0.2

The Python wheel includes the built React interface and public example archive. `cited-change serve` binds only to 127.0.0.1 and injects a fresh session token into its uncached index. API requests require that token and an allowed Host and Origin. The public static Site does not inject a token and exposes no upload or model endpoint.

TXT and PDF bytes cross only the user's loopback connection. An expendable spawned child extracts and compares them. Default comparison installs a Python audit hook that refuses outbound socket connections and DNS resolution. PDF parsing has context local decoder, aggregate content, reference count and work limits before text extraction. The parent watches worker RSS, enforces wall time and reaps a failed child. Linux also applies an address space bound; the RSS watchdog is sampled protection, not an instantaneous OS memory quota on every platform.

Local snapshots preserve original file SHA256, safe basename, UTC import date, canonical displayed text and optional PDF page coordinates. They use source_kind local and an empty URL; the dated public source path retains its existing HTTP(S) validation. A PDF page coordinate refers to extracted text, not a visual annotation on the original page.

Uploaded files and comparisons stay in process memory, capped at four jobs with completed idle expiry. Exports and explicit CLI archives are separate user directed persistence. No automatic document archive, telemetry or update check is added. Process memory may be swapped by the operating system.

Optional own-key AI runs only after explicit consent in the local interface or CLI. The Python process reads OPENAI_API_KEY, explicit model/rates and cap from its local environment. Neither the key nor a substitute owner credential is exposed to browser code. At most eight bounded source windows are sent directly to the fixed OpenAI Responses endpoint. Source offsets are mapped back to the complete local texts; unsupported or uncovered changes remain in the local report and partial coverage is recorded. Persistent ledgers contain accounting only, with unknown requests conservatively reserved and no automatic retries.

The original regulatory archive and frozen evaluation below remain separate from the new synthetic TXT/PDF regression set. Its source supported AI measurements do not establish accuracy on arbitrary user PDFs.

```mermaid
flowchart LR
  A[Dated eCFR XML] --> B[Bounded retrieval and SHA256]
  B --> C[Section extraction and canonical text]
  C --> D[Deterministic alignment]
  C --> E[Structured AI findings]
  E --> F[Exact quote and shape validation]
  D --> G[SQLite provenance]
  F --> G
  F --> H[Immutable comparison JSON]
  H --> I[Static React viewer and exports]
  C --> J[Frozen reference annotations]
  H --> K[Separate source review]
  J --> K
  K --> L[Reproducible evaluation]
  L --> I
```

## Source identity

Raw XML files are retained under `data/raw`. `data/sources.json` records dated URLs and SHA256 digests. Normalization preserves meaningful inline text, emits child tails once and canonicalizes whitespace and Unicode. A quote offset addresses the resulting displayed section text, not a byte offset in XML.

A missing section is represented only after a complete successful XML parse containing section records. A failed fetch or unrecognized document cannot become an empty section. Historical identifiers can change topics, so absence and replacement are described only within the compared snapshots.

## Evidence coordinates

Evidence uses half open Unicode code point ranges. Python slices source strings directly. The viewer uses `Array.from(text)` before slicing so emoji and other non BMP characters do not shift highlights. Every non null quote must equal its recorded slice. Model quotes must be unique on their source side.

## Analysis layers

The deterministic engine aligns paragraphs, matches intact moves before unmatched edits and conservatively classifies textual changes. The model layer authors source grounded explanations and categories. Output is imported through a strict schema and exact quotation checks. Complex one sided revisions are flagged for review instead of being mechanically certified as semantic additions or removals. Paragraph order checks distinguish reordering from simple prefix insertion.

Native model outputs remain unchanged in `data/inference`. The public archive is a separate validated representation. Per case usage and latency are unavailable for batched native generation, so availability flags prevent numeric placeholders from appearing as measurements. Batch totals are recorded separately.

## Persistence and repeatability

SQLite stores snapshot identities, section text hashes and append only comparison records. The CLI reuses an identical stored deterministic result on a repeat invocation. A changed result under the same identity is rejected, not overwritten. `scripts/build_archive.py` caches unchanged reports and creates a provenance archive for the input identity.

The static site needs no database or API credential. Its data comes from the validated archive. JSON and standalone HTML exports carry sources and evidence. A fresh Python and Node installation can reproduce evaluation from the published records without inference charges.

## Evaluation boundaries

The 60 case set contains 40 real pairs with unique section identifiers and 20 synthetic controls. Development and held out cases were separated before inference. Source annotation and source review are separate agent runs, not human expert review. The same model family creates correlated error risk.

Frozen references group edits differently from model findings. The evaluator therefore reports strict complete event matching and collective coverage, with no double credit. Redundant reviewer missed-event fields used mixed conventions; original files are preserved and discrepancies are explicitly recorded. Metrics derive from the underlying finding matches and event coverage records.

Word and paragraph baselines measure evidence location and execution time. Their generic explanations were not independently adjudicated, so location coverage is not presented as semantic accuracy or proof of superiority.

## Deployment

The public GitHub repository contains source, tests, snapshots, prompts and evaluation artifacts. Sites serves the compiled `dist` directory. It makes no model calls. Local operational records, helper conversations, credentials, virtual environments and browser profiles are excluded from public source and deployment.
