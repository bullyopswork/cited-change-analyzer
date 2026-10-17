# AI execution

## Recorded generation

Original analysis used `gpt-6.1-sol` with high reasoning through verified native Codex runs on the existing authenticated account. Each run received the frozen prompt and only its own source inputs. It did not receive reference labels or the other split's outputs. Separate fresh runs annotated references and reviewed predictions.

The frozen prompt is `prompts/cca-grounded-v1.txt`; an identical packaged copy is included for the Python adapter. The native batch wrapper contains a case ID and result list. The adapter's strict response schema handles one case at a time. Source content rules are shared; execution route and outer transport format are recorded separately.

The repository does not extract, copy or publish agent OAuth credentials. Original native execution depends on the approved Codex environment; it is not a claim that any standalone CLI can automatically reuse a ChatGPT session. Replaying the benchmark uses the published raw outputs and needs no account access.

## Optional Responses adapter

This path is implemented and mock tested, but was not live tested in this build. It sends only the supplied public source material and requires `OPENAI_API_KEY` in the caller's environment. Do not put credentials in source, browser code, output files or shell arguments.

The caller chooses a supported model and verifies its current pricing. No model prices are hard coded or inferred from an account's credit balance.

```python
import json
import os
from cited_change.model import BudgetLedger, TokenRates, analyze_openai

with open("comparison.json") as source:
    comparison = json.load(source)

rates = TokenRates(
    os.environ["OPENAI_INPUT_USD_PER_MILLION"],
    os.environ["OPENAI_OUTPUT_USD_PER_MILLION"],
)
ledger = BudgetLedger("model-budget.sqlite", cap_usd="10")
result = analyze_openai(
    comparison,
    model=os.environ["OPENAI_MODEL"],
    rates=rates,
    ledger=ledger,
    max_output_tokens=2048,
)
```

Use the same persistent ledger throughout a run. Unknown or failed outcomes retain their conservative reservation. A new ledger is a separate budget, not a reset of an existing authorization. Caller supplied rates must be accurate for monetary accounting to be meaningful. Read only replay and cached imports make no requests.

Requests use `store: false`, a strict JSON schema, bounded output, no automatic retries and bounded transport waits. Invalid, incomplete or refused output cannot become a successful comparison. The standard library timeout is not hard process cancellation; the command runner should enforce an outer lifetime bound in unattended use.

## Offline import

```bash
cited-change enrich comparison.json \
  --model-output model-output.json \
  --model gpt-6.1-sol \
  --provenance native-provenance.json \
  --output enriched.json
```

The single case model output contains `changes` and `warnings`, as specified by `OUTPUT_SCHEMA` in `cited_change.model`. Each change contains exact before and after quotes, a category, explanation and review fields. Batch records are split into those single case objects by the archive builder. Saved output parsing rejects duplicate keys as well as malformed JSON.

## Cost record

Additional standalone API spend for this release was USD 0. Native generation consumed existing account credits. No credit to dollar conversion or remaining credit balance was verified. Token totals and batch timestamps come from runtime records, are sanitized before publication and include agent context and file operations. They are not token counts or latencies for isolated per case API requests.
