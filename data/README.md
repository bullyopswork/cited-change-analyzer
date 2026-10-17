# Data and provenance

`raw/` contains dated XML and public version metadata retrieved from the eCFR API for 41 CFR Part 301-10. `sources.json` identifies URLs, requested snapshot dates, SHA256 hashes and source sizes. The first release uses 14 snapshots, with 1,352,990 decoded XML bytes.

1. `benchmark/real-inputs-v2.json`: the final 40 real source pairs. An initial source notice heavy selection was superseded before inference; the final curation is explicit in the file.
2. `benchmark/controlled-inputs.json`: 20 clearly synthetic controls, not actual regulations.
3. `benchmark/gold-real.json` and `gold-controlled.json`: reference events and annotation notes.
4. `benchmark/freeze.json`: hashes, split and prompt recorded before prediction generation.
5. `inference/`: source only model inputs, unchanged raw outputs and sanitized runtime provenance.
6. `evaluation/`: separate agent review records and replayed metrics.
7. `archive/`: validated comparisons and evaluation data used to build the viewer.

Dates identify the requested historical eCFR version, not a legal effective date inferred by this application. Amendment notices and source citations are kept separate from changes to substantive requirements. Some historical XML contains malformed placeholders; these are retained rather than silently repaired. An absent section at an identifier does not establish repeal or global absence of its provisions.

Federal regulatory text is attributed to eCFR and the issuing agencies. The MIT license covers this project's code, not ownership of government source text or any separately protected material. Review the [government information policies](https://www.govinfo.gov/about/policies), [eCFR date guidance](https://www.ecfr.gov/reader-aids/ecfr-developer-resources/understanding-ecfr-dates) and original sources when reusing data.

The fetch script uses a bounded corpus and local caching. After an initial throttled request batch, retrieval was serialized; no service challenge or access restriction was bypassed. Historical snapshots remain pinned in this release. There is no recurring crawler.
