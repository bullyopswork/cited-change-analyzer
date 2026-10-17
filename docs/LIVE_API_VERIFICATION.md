# Live API verification, v0.2.0

On October 17, 2026, the published v0.2.0 package passed a bounded OpenAI Responses smoke check with `gpt-6.1-sol`. The existing wheel and source tag were not rebuilt or replaced.

## Results

1. A synthetic TXT policy pair produced three explanations: reimbursement increased from $100 to $150, the claim period changed from 30 to 45 days, and attaching receipts changed from optional to mandatory. All three explanations matched their cited source passages.
2. A synthetic selectable text PDF pair produced two explanations: a fee changed from $75 to $90 and the payment deadline changed from 30 to 15 days. Both matched the source. The result remained marked partial because the narrower AI quotes did not cover the full spans of the broader lexical finding. That local finding was retained.
3. Identical text supplied as TXT and PDF produced no changes and made no API request.
4. A deliberately invalid model returned a real HTTP 404. The application retained all local findings, reported AI unavailable and did not retry.
5. A reservation above the proof's USD 1 cap was rejected before any network request.

Source text, file hashes and PDF page metadata were unchanged. Every published evidence quote passed exact source slice validation. JSON and standalone HTML exports completed for both successful cases.

These are controlled development smoke checks reviewed by the implementing agent, not an independent accuracy study. They do not establish correctness for arbitrary documents, layouts or legal interpretations. The existing frozen regulatory benchmark is unchanged.

## Execution boundary

The tested installation was outside the source checkout. Its model adapter SHA256 was `d180f47e6d422fff796a95d95389dc34c68799ac11b9712e779095f82fcd21da`. The released wheel SHA256 remains `0590a40d4c8945c18ba05765125d402d845cb4c84d0cc38bcbb4aba73d76144a`.

The test used a destination restricted protected credential proxy. A test harness routed the published adapter's unchanged HTTPS requests through that proxy instead of its normal direct connection. It did not substitute provider responses or change the prompt, schema, source alignment or response validation. The credential itself was not available to the test process or included in the saved proof. This is a provider integration check of the installed package, not a new browser interaction test; installed browser flows and cross platform installation were verified separately.

All three outgoing requests targeted `https://api.openai.com/v1/responses`, used `store: false` and required the strict response schema. Only synthetic sources were sent. The successful requests returned the default service tier. No credentials, account balance, organization identifiers or private documents are included here.

## Usage and bounds

The successful requests used 1,806 input tokens and 520 output tokens, with no cache discount or cache write charges in the returned usage. At the [official standard prices](https://developers.openai.com/api/docs/pricing), USD 2 per million input tokens and USD 10 per million output tokens, the usage estimate is USD 0.008812. Request times were approximately 9.7 and 6.6 seconds.

One persistent ledger limited this proof to USD 1, inside the approved USD 10 development allowance. The harness permitted at most three requests. The final ledger retains USD 0.06655 because a rejected request keeps its full conservative reservation. That amount is an upper accounting reservation, not a provider invoice. No retries, credit purchases, paid hosting or visitor access to the development key were added.

## Saved evidence

The [verification JSON](verification/v02-live-api.json) records the requests, provider usage, source checks and budget. The [TXT result](verification/v02-text-policy.json), [PDF result](verification/v02-pdf-fee.json) and [rejected request result](verification/v02-provider-rejection.json) contain only synthetic sources and saved application output.

The saved reports can be validated locally without an API key or charge:

```bash
cited-change validate docs/verification/v02-text-policy.json
cited-change validate docs/verification/v02-pdf-fee.json
cited-change validate docs/verification/v02-provider-rejection.json
```

New AI analysis requires the installer's own key and current model pricing. No secret is included in the release, and the public demo still has no live AI endpoint.
