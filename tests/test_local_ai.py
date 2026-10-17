"""Offline-only regression coverage for the local optional AI seam."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cited_change.local_ai import enrich_local_report, get_ai_configuration
from cited_change.model import BudgetLedger, ModelError, apply_model_output
from cited_change.validation import validate
from test_engine import compare


ENV = {"OPENAI_API_KEY": "synthetic-test-key", "OPENAI_MODEL": "caller-model",
       "OPENAI_INPUT_USD_PER_MILLION": "1", "OPENAI_OUTPUT_USD_PER_MILLION": "2"}


def answer(before="Rate €10.", after="Rate €20.", category="amount"):
    return {"changes": [{"category": category, "summary": "The quoted text changed.",
                         "before_quote": before, "after_quote": after,
                         "needs_review": True, "review_reason": "Review the complete source."}], "warnings": []}


def imported(chunk, output=None):
    return apply_model_output(chunk, output or answer(), model="actual-model", provenance={
        "method": "openai_responses", "prompt_version": "cca-grounded-v1",
        "latency_ms": 3, "input_tokens": 100, "output_tokens": 50,
        "cost_usd": 0.0002, "billing_basis": "Synthetic test token rates."})


class FakeResponse:
    status = 200

    def __init__(self, output):
        self.raw = json.dumps({"status": "completed", "model": "actual-model", "output": [
            {"type": "message", "status": "completed", "content": [
                {"type": "output_text", "text": json.dumps(output)}]}],
            "usage": {"input_tokens": 100, "output_tokens": 50}}).encode()

    def read1(self, count):
        piece, self.raw = self.raw[:count], self.raw[count:]
        return piece

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class LocalAIConfigurationTests(unittest.TestCase):
    def test_configuration_is_json_safe_and_default_cap_is_one(self):
        with patch.dict(os.environ, ENV, clear=True):
            public = get_ai_configuration()
        self.assertEqual(public, {"configured": True, "model": "caller-model", "cap_usd": "1", "reason": None})
        self.assertNotIn("synthetic-test-key", json.dumps(public))

    def test_invalid_configuration_makes_no_adapter_call_or_ledger(self):
        cases = [{}, {**ENV, "OPENAI_API_KEY": ""}, {**ENV, "OPENAI_MODEL": ""},
                 {**ENV, "OPENAI_MODEL": "sk-private-must-not-echo"},
                 {**ENV, "OPENAI_INPUT_USD_PER_MILLION": "NaN"},
                 {**ENV, "OPENAI_OUTPUT_USD_PER_MILLION": "0"}]
        cases.extend({**ENV, "CCA_API_CAP_USD": value} for value in ("0", "-1", "NaN", "Infinity", "10.01", "0.0000000001"))
        report = compare("Rate €10.", "Rate €20.")
        with tempfile.TemporaryDirectory() as directory:
            for environment in cases:
                with self.subTest(environment={k: v for k, v in environment.items() if k != "OPENAI_API_KEY"}):
                    path = Path(directory) / "never.sqlite"
                    with patch.dict(os.environ, environment, clear=True), patch("cited_change.local_ai.analyze_openai") as api:
                        configuration = get_ai_configuration()
                        result = enrich_local_report(report, path)
                    self.assertFalse(configuration["configured"])
                    self.assertIsNotNone(configuration["reason"])
                    self.assertNotIn("sk-private", json.dumps(configuration))
                    self.assertEqual(result["changes"], report["changes"])
                    self.assertEqual(result["analysis"]["ai_coverage"]["status"], "unavailable")
                    self.assertFalse(validate(result))
                    self.assertFalse(path.exists())
                    api.assert_not_called()


class LocalAIEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = Path(self.directory.name) / "budget.sqlite"
        environment = patch.dict(os.environ, ENV, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_full_source_success_preserves_input_and_reports_usage(self):
        report = compare("🦉 Café.\n\nRate €10.", "🦉 Café.\n\nRate €20.")
        original = copy.deepcopy(report)
        messages = []
        with patch("cited_change.local_ai.analyze_openai", side_effect=lambda chunk, **kw: imported(chunk)) as api:
            result = enrich_local_report(report, self.ledger, messages.append)
        self.assertEqual(report, original)
        self.assertEqual(result["before"], report["before"])
        self.assertEqual(result["analysis"]["ai_coverage"]["status"], "complete")
        self.assertEqual(result["analysis"]["input_tokens"], 100)
        self.assertEqual(result["analysis"]["model"], "actual-model")
        self.assertEqual(result["changes"][0]["method"], "openai_responses")
        self.assertEqual(api.call_count, 1)
        self.assertEqual(api.call_args.kwargs["timeout_seconds"], 20)
        self.assertTrue(messages)
        self.assertFalse(validate(result))

    def test_unicode_window_offsets_and_pdf_metadata_are_exact(self):
        prefix = "🦉 Café e\u0301 stable. " * 1800 + "\n\n"
        before, after = prefix + "Rate €10.", prefix + "Rate €20."
        report = compare(before, after)
        for side in ("before", "after"):
            report[side].update(source_kind="local", filename=side + ".pdf", format="pdf", url="",
                                extraction_warnings=[], pages=[{"number": 1, "start": 0, "end": len(report[side]["text"])}])
        self.assertFalse(validate(report))
        def call(chunk, **kwargs):
            self.assertLessEqual(len(chunk["before"]["text"]), 20_000)
            self.assertLess(len(chunk["before"]["text"]), len(before))
            self.assertEqual(chunk["before"]["format"], "text")
            self.assertNotIn("pages", chunk["before"])
            return imported(chunk)
        with patch("cited_change.local_ai.analyze_openai", side_effect=call):
            result = enrich_local_report(report, self.ledger)
        self.assertEqual(result["before"], report["before"])
        evidence = result["changes"][0]["before_evidence"]
        self.assertEqual(evidence, {"start": len(prefix), "end": len(before), "quote": "Rate €10."})
        self.assertEqual(result["analysis"]["ai_coverage"]["status"], "complete")
        self.assertTrue(result["changes"][0]["needs_review"])
        self.assertFalse(validate(result))

    def test_asymmetric_unicode_origins_map_each_side_independently(self):
        prefix = "🦉 Café stable. " * 1800 + "\n\n"
        inserted = "A new introductory paragraph.\n\n"
        report = compare(prefix + "Rate €10.", inserted + prefix + "Rate €20.")
        def call(chunk, **kwargs):
            if "Rate €10." in chunk["before"]["text"]:
                return imported(chunk)
            return imported(chunk, answer(None, inserted.rstrip(), "added"))
        with patch("cited_change.local_ai.analyze_openai", side_effect=call):
            result = enrich_local_report(report, self.ledger)
        rate = next(change for change in result["changes"] if change["category"] == "amount")
        self.assertEqual(rate["before_evidence"]["start"], len(prefix))
        self.assertEqual(rate["after_evidence"]["start"], len(inserted + prefix))
        self.assertFalse(validate(result))

    def test_empty_model_answer_never_silently_removes_local_changes(self):
        report = compare("Rate €10.", "Rate €20.")
        with patch("cited_change.local_ai.analyze_openai", side_effect=lambda chunk, **kw: imported(chunk, {"changes": [], "warnings": []})):
            result = enrich_local_report(report, self.ledger)
        self.assertEqual(result["changes"], report["changes"])
        self.assertEqual(result["analysis"]["ai_coverage"]["status"], "partial")
        self.assertEqual(result["analysis"]["ai_coverage"]["retained_local_changes"], 1)
        self.assertTrue(any("not silently removed" in warning for warning in result["warnings"]))

    def test_subset_quotes_cannot_erase_uncovered_local_evidence(self):
        report = compare("The complete rate is €10 per day.", "The complete rate is €20 per week.")
        with patch("cited_change.local_ai.analyze_openai", side_effect=lambda chunk, **kw: imported(chunk, answer("€10", "€20"))):
            result = enrich_local_report(report, self.ledger)
        self.assertTrue(any(item["method"] == "deterministic" for item in result["changes"]))
        self.assertEqual(result["analysis"]["ai_coverage"]["retained_local_changes"], 1)
        self.assertFalse(validate(result))

    def test_oversized_change_stays_local_without_requests(self):
        report = compare("A" * 21_000, "B" * 21_000)
        with patch("cited_change.local_ai.analyze_openai") as api:
            result = enrich_local_report(report, self.ledger)
        api.assert_not_called()
        self.assertEqual(result["changes"], report["changes"])
        self.assertEqual(result["analysis"]["ai_coverage"]["skipped_local_changes"], 1)
        self.assertEqual(result["analysis"]["ai_coverage"]["status"], "unavailable")
        self.assertFalse(validate(result))

    @staticmethod
    def separated_changes(count):
        old, new = [], []
        for i in range(count):
            old.extend([f"Target {i} old.", f"Stable context {i}. " * 15])
            new.extend([f"Target {i} new.", f"Stable context {i}. " * 15])
        return compare("\n\n".join(old), "\n\n".join(new))

    def test_eight_call_limit_retains_excess_changes(self):
        report = self.separated_changes(10)
        def call(chunk, **kwargs):
            index = int(chunk["before"]["text"].split("Target ")[1].split()[0])
            return imported(chunk, answer(f"Target {index} old.", f"Target {index} new.", "wording"))
        with patch("cited_change.local_ai.MAX_WINDOW_CHARACTERS", 70), patch("cited_change.local_ai.analyze_openai", side_effect=call) as api:
            result = enrich_local_report(report, self.ledger)
        self.assertEqual(api.call_count, 8)
        coverage = result["analysis"]["ai_coverage"]
        self.assertEqual(coverage["skipped_local_changes"], 2)
        self.assertEqual(coverage["retained_local_changes"], 2)
        self.assertEqual(coverage["covered_local_changes"], 8)
        self.assertEqual(len(result["changes"]), 10)
        self.assertFalse(validate(result))

    def test_failed_chunk_preserves_local_and_other_success(self):
        report = self.separated_changes(2)
        def call(chunk, **kwargs):
            if "Target 0 old." in chunk["before"]["text"]:
                return imported(chunk, answer("Target 0 old.", "Target 0 new.", "wording"))
            raise RuntimeError("Bearer synthetic-test-key confidential document path")
        with patch("cited_change.local_ai.MAX_WINDOW_CHARACTERS", 70), patch("cited_change.local_ai.analyze_openai", side_effect=call) as api:
            result = enrich_local_report(report, self.ledger)
        self.assertEqual(api.call_count, 2)
        coverage = result["analysis"]["ai_coverage"]
        self.assertEqual(coverage["status"], "partial")
        self.assertEqual(coverage["covered_local_changes"], 1)
        self.assertEqual(coverage["retained_local_changes"], 1)
        self.assertEqual(coverage["failed_chunks"], 1)
        self.assertNotIn("synthetic-test-key", json.dumps(result))
        self.assertNotIn("confidential document path", json.dumps(result))
        self.assertFalse(validate(result))

    def test_global_false_addition_rejected_even_if_outside_window(self):
        prefix = "Unique unchanged notice.\n\n" + "Stable. " * 4000 + "\n\n"
        report = compare(prefix + "Old paragraph.", prefix + "Unique unchanged notice.")
        with patch("cited_change.local_ai.analyze_openai", side_effect=lambda chunk, **kw: imported(chunk, answer(None, "Unique unchanged notice.", "added"))):
            result = enrich_local_report(report, self.ledger)
        self.assertEqual(result["changes"], report["changes"])
        self.assertEqual(result["analysis"]["ai_coverage"]["failed_chunks"], 1)
        self.assertFalse(validate(result))

    def test_no_changes_no_network_and_progress_failure_is_nonfatal(self):
        report = compare("Same.", "Same.")
        with patch("cited_change.local_ai.analyze_openai") as api:
            result = enrich_local_report(report, self.ledger)
        api.assert_not_called()
        self.assertFalse(self.ledger.exists())
        self.assertEqual(result["analysis"]["ai_coverage"]["status"], "complete")
        with patch("cited_change.local_ai.analyze_openai", side_effect=lambda chunk, **kw: imported(chunk)):
            result = enrich_local_report(compare("Rate €10.", "Rate €20."), self.ledger,
                                         lambda message: (_ for _ in ()).throw(RuntimeError("broken UI")))
        self.assertEqual(result["analysis"]["ai_coverage"]["status"], "complete")

    def test_real_adapter_reserves_settles_and_reuses_budget(self):
        report = compare("Rate €10.", "Rate €20.")
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = FakeResponse(answer())
            result = enrich_local_report(report, self.ledger)
        state = result["analysis"]["ai_coverage"]["budget"]
        self.assertEqual(state["requests"], 1)
        self.assertEqual(state["max_requests"], 8)
        self.assertEqual(state["cap_usd"], 1)
        self.assertLessEqual(state["seconds_remaining"], 600)
        self.assertAlmostEqual(state["charged_or_reserved_usd"], 0.0002)
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = RuntimeError("Bearer synthetic-test-key private failure body")
            failed = enrich_local_report(report, self.ledger)
        state = failed["analysis"]["ai_coverage"]["budget"]
        self.assertEqual(state["requests"], 2)
        self.assertGreater(state["charged_or_reserved_usd"], 0.0004)
        self.assertIsNone(failed["analysis"]["cost_usd"])
        self.assertEqual(failed["changes"], report["changes"])
        self.assertNotIn("private failure", json.dumps(failed))
        self.assertEqual(BudgetLedger(self.ledger, cap_usd="1", max_requests=8, max_seconds=600).snapshot()["requests"], 2)

    def test_budget_refusal_precedes_transport_and_does_not_reset(self):
        report = compare("Rate €10.", "Rate €20.")
        ledger = BudgetLedger(self.ledger, cap_usd="1", max_requests=8, max_seconds=600)
        ledger.reserve(1_000_000_000)
        with patch("urllib.request.build_opener") as opener:
            result = enrich_local_report(report, self.ledger)
        opener.assert_not_called()
        self.assertEqual(result["changes"], report["changes"])
        self.assertEqual(result["analysis"]["ai_coverage"]["budget"]["requests"], 1)
        with patch.dict(os.environ, {"CCA_API_CAP_USD": "2"}), patch("urllib.request.build_opener") as opener:
            mismatch = enrich_local_report(report, self.ledger)
        opener.assert_not_called()
        self.assertEqual(mismatch["changes"], report["changes"])
        self.assertTrue(any("ledger" in warning for warning in mismatch["warnings"]))

    def test_existing_eight_request_ledger_never_calls_transport_again(self):
        ledger = BudgetLedger(self.ledger, cap_usd="1", max_requests=8, max_seconds=600)
        for _ in range(8):
            identifier, _ = ledger.reserve(1)
            ledger.settle(identifier, 0)
        with patch("urllib.request.build_opener") as opener:
            result = enrich_local_report(compare("Rate €10.", "Rate €20."), self.ledger)
        opener.assert_not_called()
        self.assertEqual(result["analysis"]["ai_coverage"]["budget"]["requests"], 8)
        self.assertEqual(result["analysis"]["ai_coverage"]["status"], "unavailable")

    def test_expired_ledger_makes_no_transport_request(self):
        BudgetLedger(self.ledger, cap_usd="1", max_requests=8, max_seconds=600)
        with patch("cited_change.model.time.time", return_value=1e20), patch("urllib.request.build_opener") as opener:
            result = enrich_local_report(compare("Rate €10.", "Rate €20."), self.ledger)
        opener.assert_not_called()
        self.assertEqual(result["analysis"]["ai_coverage"]["status"], "unavailable")

    def test_invalid_report_is_redacted_before_network(self):
        with patch("cited_change.local_ai.analyze_openai") as api:
            with self.assertRaisesRegex(ModelError, "validated local comparison"):
                enrich_local_report({"private": "not to echo"}, self.ledger)
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
