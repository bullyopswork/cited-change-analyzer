import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cited_change.cli import main
from cited_change.model import (BudgetError, BudgetLedger, ModelError, OUTPUT_SCHEMA,
                                PROMPT_VERSION, TokenRates, analyze_openai,
                                apply_model_output, build_model_input)
from cited_change.validation import validate
from test_engine import compare


def output(before="Rate $10.", after="Rate $20.", category="amount"):
    return {"changes": [{"category": category, "summary": "The stated rate changed.",
                         "before_quote": before, "after_quote": after,
                         "needs_review": True, "review_reason": "Review significance."}],
            "warnings": ["Exact citations are not semantic verification."]}


def response(answer=None, **kwargs):
    return {"status": "completed", "model": "caller-model-actual-version",
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "status": "completed", "content": [
                           {"type": "output_text", "text": json.dumps(answer or output())}]}],
            "usage": {"input_tokens": 100, "output_tokens": 50}, **kwargs}


class ImportTests(unittest.TestCase):
    def test_common_native_and_api_input_contract_is_offline(self):
        source = compare("🦉 Old.", "🦉 New.")
        with patch("urllib.request.build_opener") as network:
            contract = build_model_input(source)
        network.assert_not_called()
        self.assertEqual(contract["prompt_version"], "cca-grounded-v1")
        self.assertEqual(contract["output_schema"], OUTPUT_SCHEMA)
        self.assertEqual(contract["input"]["before"], source["before"])
        contract["input"]["before"]["text"] = "mutation"
        self.assertEqual(source["before"]["text"], "🦉 Old.")

    def test_unicode_grounding_preserves_source_and_real_metadata(self):
        original = compare("🦉 Café.\n\nRate €10.", "🦉 Café.\n\nRate €20.")
        saved = copy.deepcopy(original)
        provenance = {"method": "native_codex", "prompt_version": "cca-grounded-v1",
                      "input_tokens": 123, "output_tokens": 45, "latency_ms": 678,
                      "cost_usd": None, "billing_basis": "unpriced existing account credits"}
        result = apply_model_output(original, output("Rate €10.", "Rate €20."),
                                    model="gpt-6.1-sol", provenance=provenance)
        self.assertEqual(original, saved)
        self.assertFalse(validate(result))
        quote = result["changes"][0]["before_evidence"]
        self.assertEqual(quote, {"start": len("🦉 Café.\n\n"),
                                 "end": len("🦉 Café.\n\nRate €10."), "quote": "Rate €10."})
        self.assertEqual(result["analysis"]["prompt_version"], "cca-grounded-v1")
        self.assertEqual(result["analysis"]["input_tokens"], 123)
        self.assertEqual(result["analysis"]["latency_ms"], 678)
        self.assertTrue(result["analysis"]["usage_available"])
        self.assertIsNone(result["analysis"]["cost_usd"])

    def test_unreported_native_usage_not_presented_as_measured(self):
        result = apply_model_output(compare("Rate $10.", "Rate $20."), output(), model="native-model")
        self.assertFalse(result["analysis"]["usage_available"])
        self.assertFalse(result["analysis"]["latency_available"])
        self.assertIsNone(result["analysis"]["cost_usd"])
        self.assertEqual(result["analysis"]["billing_basis"], "unpriced existing account credits")
        result = apply_model_output(compare("Rate $10.", "Rate $20."), output(), model="native-model",
                                    provenance={"input_tokens": 0, "output_tokens": 0,
                                                "latency_ms": 0, "usage_available": False,
                                                "latency_available": False})
        self.assertFalse(result["analysis"]["usage_available"])
        self.assertFalse(result["analysis"]["latency_available"])

    def test_exact_relocation_with_edit_support(self):
        anchor = "This is a much longer stable anchor with many distinct words."
        source = compare("Short.\n\n" + anchor, anchor + "\n\nShort.")
        result = apply_model_output(source, output("Short.", "Short.", "moved"), model="native-model")
        self.assertEqual(result["changes"][0]["category"], "moved")
        self.assertFalse(validate(result))

    def test_reordered_block_and_prefix_shift_are_distinct(self):
        old = 'Keep the receipt.\n\nSubmit the form.'
        new = 'Submit the form.\n\nKeep the receipt.'
        report = apply_model_output(compare(old, new), output(old, new, 'moved'), model='native-model')
        self.assertFalse(validate(report))
        with self.assertRaises(ModelError):
            apply_model_output(compare('Keep.', 'New.\n\nKeep.'), output('Keep.', 'Keep.', 'moved'), model='native-model')

    def test_null_cost_requires_explicit_nonempty_billing_basis(self):
        result = compare("a", "b")
        result["analysis"]["cost_usd"] = None
        for basis in (None, "", " ", 1):
            result["analysis"]["billing_basis"] = basis
            self.assertTrue(validate(result))
        result["analysis"]["billing_basis"] = "unpriced existing account credits"
        self.assertFalse(validate(result))
        self.assertIsNone(result["analysis"]["cost_usd"])
        del result["analysis"]["cost_usd"]
        self.assertTrue(validate(result))

    def test_hallucinated_empty_and_overlapping_duplicate_quotes_rejected(self):
        for before, after, quote in (("Rate $10.", "Rate $20.", "invented"),
                                     ("Rate $10.", "Rate $20.", ""),
                                     ("aaa", "baa", "aa")):
            with self.subTest(quote=quote), self.assertRaises(ModelError):
                apply_model_output(compare(before, after), output(quote, after), model="native-model")
        with self.assertRaisesRegex(ModelError, "ambiguous"):
            apply_model_output(compare("Repeat.\n\nRepeat.", "Revised."),
                               output("Repeat.", "Revised."), model="native-model")

    def test_no_evidence_unchanged_spans_and_false_movement_rejected(self):
        cases = [(compare("a", "b"), output(None, None)),
                 (compare("Same.\n\nOld.", "Same.\n\nNew."), output("Same.", "Same.")),
                 (compare("Alpha.\n\nBeta.\n\nOld.", "Alpha.\n\nBeta.\n\nNew."),
                  output("Alpha.", "Beta.")),
                 (compare("Same.", "Prefix. Same."), output("Same.", "Same.", "moved"))]
        for source, answer in cases:
            with self.subTest(answer=answer), self.assertRaises(ModelError):
                apply_model_output(source, answer, model="native-model")

    def test_category_absent_side_and_false_add_remove(self):
        source = compare("Old.\n\nKept.", "New.\n\nKept.")
        for answer in (output("Old.", "New.", "added"), output("Old.", "New.", "removed"),
                       output(None, "New.", "wording"), output("Old.", None, "amount"),
                       output(None, "Kept.", "added"), output("Kept.", None, "removed")):
            with self.subTest(answer=answer), self.assertRaises(ModelError):
                apply_model_output(source, answer, model="native-model")

    def test_editorial_notice_direction_and_complex_one_sided_review(self):
        source = compare('Keep the receipt.', 'Notice: amendment published.\n\nKeep the receipt.')
        result = apply_model_output(source, output(None, 'Notice: amendment published.', 'editorial'), model='native-model')
        self.assertFalse(validate(result))
        source = compare('Old.\n\nKept.', 'New.\n\nKept.')
        result = apply_model_output(source, output('Old.', None, 'removed'), model='native-model')
        self.assertTrue(result['changes'][0]['needs_review'])
        self.assertIn('replacement', result['changes'][0]['review_reason'])

    def test_packaged_prompt_matches_frozen_generation_prompt(self):
        from cited_change.model import build_model_input
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(build_model_input(compare('Old.', 'New.'))['instructions'],
                         (root/'prompts/cca-grounded-v1.txt').read_text())

    def test_valid_one_sided_absence_and_insertion(self):
        cases = [("", "New.", output(None, "New.", "added")),
                 ("Old.", "", output("Old.", None, "removed")),
                 ("Keep.", "Keep. New.", output(None, "New.", "added"))]
        for before, after, answer in cases:
            with self.subTest(before=before):
                result = apply_model_output(compare(before, after), answer, model="native-model")
                self.assertFalse(validate(result))

    def test_malformed_schema_enum_review_and_duplicate_claims(self):
        bad = []
        for key, value in (("category", "legal"), ("needs_review", 1),
                           ("review_reason", None), ("summary", " "),
                           ("before_quote", ["Rate $10."])):
            answer = output()
            answer["changes"][0][key] = value
            bad.append(answer)
        for mutate in (lambda answer: answer.update(extra=True),
                       lambda answer: answer["changes"][0].update(extra=True),
                       lambda answer: answer["changes"].append(copy.deepcopy(answer["changes"][0]))):
            answer = output()
            mutate(answer)
            bad.append(answer)
        for answer in bad + [{"changes": [], "warnings": [1]}, {"changes": None, "warnings": []}]:
            with self.subTest(answer=answer), self.assertRaises(ModelError):
                apply_model_output(compare("Rate $10.", "Rate $20."), answer, model="native-model")

    def test_offline_cli_import_never_calls_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "report.json").write_text(json.dumps(compare("Rate $10.", "Rate $20.")))
            (root / "answer.json").write_text(json.dumps(output()))
            (root / "metadata.json").write_text(json.dumps({"prompt_version": "cca-grounded-v1"}))
            with patch("urllib.request.build_opener") as network, redirect_stdout(io.StringIO()):
                self.assertEqual(main(["enrich", str(root / "report.json"), "--model-output",
                                       str(root / "answer.json"), "--model", "native-model",
                                       "--provenance", str(root / "metadata.json"),
                                       "--output", str(root / "enriched.json")]), 0)
            network.assert_not_called()
            enriched = json.loads((root / "enriched.json").read_text())
            self.assertIsNone(enriched["analysis"]["cost_usd"])
            self.assertEqual(enriched["analysis"]["method"], "native_codex")

    def test_saved_native_json_rejects_duplicate_keys(self):
        from cited_change.model import parse_model_json
        with self.assertRaisesRegex(ModelError, 'invalid model JSON'):
            parse_model_json('{"changes":[],"changes":[{}],"warnings":[]}')


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.body = body
        self.position = 0

    def read1(self, limit):
        data = self.body[self.position:self.position + limit]
        self.position += len(data)
        return data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = BudgetLedger(Path(self.directory.name) / "budget.sqlite")
        # Synthetic TEST prices only. Not a rate claim for any deployed model.
        self.rates = TokenRates("1", "2")
        self.source = compare("Rate $10.", "Rate $20.")
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret-do-not-log"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def call(self, body=None, **kwargs):
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = FakeResponse(json.dumps(body or response()).encode())
            result = analyze_openai(self.source, model="caller-selected-model", rates=self.rates,
                                    ledger=self.ledger, **kwargs)
            return result, opener.return_value.open.call_args

    def test_mock_api_schema_parse_usage_and_actual_model(self):
        result, call = self.call()
        request = call.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.method, "POST")
        self.assertIs(payload["store"], False)
        self.assertEqual(payload["text"]["format"], {"type": "json_schema", "name": "change_analysis",
                                                    "schema": OUTPUT_SCHEMA, "strict": True})
        self.assertEqual(result["analysis"]["model"], "caller-model-actual-version")
        self.assertEqual(result["analysis"]["method"], "openai_responses")
        self.assertEqual(result["analysis"]["prompt_version"], PROMPT_VERSION)
        self.assertEqual(result["analysis"]["input_tokens"], 100)
        self.assertEqual(result["analysis"]["cost_usd"], 0.0002)
        self.assertEqual(self.ledger.snapshot()["charged_or_reserved_usd"], 0.0002)
        self.assertLessEqual(call.kwargs["timeout"], 30)
        self.assertFalse(validate(result))

    def test_budget_and_request_count_refused_before_network(self):
        self.ledger.reserve(10_000_000_000)
        with patch("urllib.request.build_opener") as opener, self.assertRaises(BudgetError):
            analyze_openai(self.source, model="model", rates=self.rates, ledger=self.ledger)
        opener.assert_not_called()
        capped = BudgetLedger(Path(self.directory.name) / "requests.sqlite", max_requests=1)
        capped.reserve(1)
        capped.settle(1, 0)
        with patch("urllib.request.build_opener") as opener, self.assertRaises(BudgetError):
            analyze_openai(self.source, model="model", rates=self.rates, ledger=capped)
        opener.assert_not_called()

    def test_unknown_failure_retains_reservation_and_redacts_errors(self):
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = RuntimeError("Authorization: Bearer test-secret-do-not-log private body")
            with self.assertRaises(ModelError) as caught:
                analyze_openai(self.source, model="model", rates=self.rates, ledger=self.ledger)
        self.assertNotIn("test-secret", str(caught.exception))
        self.assertNotIn("private body", str(caught.exception))
        state = self.ledger.snapshot()
        self.assertEqual(state["requests"], 1)
        self.assertGreater(state["charged_or_reserved_usd"], self.rates.cost_nano_usd(100, 50) / 1e9)
        reopened = BudgetLedger(self.ledger.path)
        self.assertEqual(reopened.snapshot()["charged_or_reserved_usd"], state["charged_or_reserved_usd"])

    def test_refusal_incomplete_malformed_and_invalid_grounding_retained(self):
        bodies = [response(status="incomplete"), response(status="failed"),
                  response(output=[{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]),
                  response(output=None), response(output=[{"type": "message", "content": None}]),
                  response(output=[{"type": "message", "content": [{"type": "output_text", "text": "not json"}]}]),
                  response(output=[{"type": "message", "content": [{"type": "output_text", "text": '{"changes":[],"changes":[],"warnings":[]}'}]}]),
                  response(usage={"input_tokens": True, "output_tokens": 50}),
                  response(answer=output("hallucinated", "Rate $20."))]
        for body in bodies:
            before = self.ledger.snapshot()["charged_or_reserved_usd"]
            with self.subTest(body=body), self.assertRaises(ModelError):
                self.call(body)
            self.assertGreater(self.ledger.snapshot()["charged_or_reserved_usd"], before)

    def test_output_and_usage_limits_keep_reservation(self):
        with self.assertRaises(ModelError):
            self.call(response(usage={"input_tokens": 100, "output_tokens": 8193}))
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = FakeResponse(b"x" * 2_000_001)
            with self.assertRaises(ModelError):
                analyze_openai(self.source, model="model", rates=self.rates, ledger=self.ledger)

    def test_read_only_accounting_and_missing_key_make_no_calls(self):
        with patch("urllib.request.build_opener") as opener, patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.ledger.snapshot()["requests"], 0)
            with self.assertRaisesRegex(ModelError, "OPENAI_API_KEY"):
                analyze_openai(self.source, model="model", rates=self.rates, ledger=self.ledger)
        opener.assert_not_called()
        self.assertEqual(self.ledger.snapshot()["requests"], 0)

    def test_ledger_cap_deadline_and_configuration_not_resettable(self):
        for kwargs in ({"cap_usd": "10.0001"}, {"max_requests": 101}, {"max_seconds": 601}):
            with self.assertRaises(BudgetError):
                BudgetLedger(Path(self.directory.name) / "invalid.sqlite", **kwargs)
        with self.assertRaises(BudgetError):
            BudgetLedger(self.ledger.path, cap_usd="9")
        with patch("cited_change.model.time.time", return_value=1e20), patch("urllib.request.build_opener") as opener:
            with self.assertRaises(BudgetError):
                analyze_openai(self.source, model="model", rates=self.rates, ledger=self.ledger)
        opener.assert_not_called()

    def test_slow_response_is_rejected_and_reservation_not_refunded(self):
        # Simulate elapsed time after the open call without sleeping or networking.
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = FakeResponse(json.dumps(response()).encode())
            with patch("cited_change.model.time.monotonic", side_effect=[0, 31]), self.assertRaises(ModelError):
                analyze_openai(self.source, model="model", rates=self.rates, ledger=self.ledger)
        self.assertGreater(self.ledger.snapshot()["charged_or_reserved_usd"], 0)


if __name__ == "__main__":
    unittest.main()
