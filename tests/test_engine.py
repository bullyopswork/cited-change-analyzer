import copy
import gzip
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cited_change import (FetchError, compare_texts, export_html, export_json,
                          extract_snapshot, fetch_bytes, normalize, section_source, validate)
from cited_change.cli import main
from cited_change.provenance import connect, record_comparison


BEFORE_XML = b'''<ECFR><DIV5 TYPE="PART" N="301-10">
<DIV8 TYPE="SECTION" N="301-10.1"><HEAD>General <I>travel</I> policy</HEAD>
<P>You <I>must</I> retain <B>all</B> receipts.</P>
<P>The rate is $100 on 2025-12-07.</P></DIV8>
<DIV8 TYPE="SECTION" N="301-10.2"><HEAD>Other rule</HEAD><P>Keep this.</P></DIV8>
</DIV5></ECFR>'''
AFTER_XML = BEFORE_XML.replace(b"$100", b"$125")


def metadata(text="snapshot", date="2025-12-07"):
    return {"date": date, "url": f"https://www.ecfr.gov/on/{date}/title-41",
            "snapshot_sha256": hashlib.sha256(text.encode()).hexdigest()}


def compare(before, after, **kwargs):
    return compare_texts(before, after, section="301-10.1", corpus="41 CFR Part 301-10",
                         before_metadata=metadata(before),
                         after_metadata=metadata(after, "2025-12-08"), **kwargs)


class ExtractionTests(unittest.TestCase):
    def test_inline_text_heading_and_nested_tails_once(self):
        snapshot = extract_snapshot(BEFORE_XML, date="2025-12-07", url=metadata()["url"])
        text = snapshot["sections"]["301-10.1"]["text"]
        self.assertEqual(text, "General travel policy\n\nYou must retain all receipts.\n\nThe rate is $100 on 2025-12-07.")
        self.assertEqual(text.count("receipts."), 1)
        self.assertEqual(snapshot["snapshot_sha256"], hashlib.sha256(BEFORE_XML).hexdigest())

    def test_namespaced_section_elements(self):
        xml = '<c:ROOT xmlns:c="urn:cfr"><c:SECTION><c:SECTNO>§ 1.2</c:SECTNO><c:SUBJECT>A <c:I>title</c:I></c:SUBJECT><c:P>See <c:A>this</c:A> now.</c:P></c:SECTION></c:ROOT>'
        snapshot = extract_snapshot(xml, date="2025-12-07", url=metadata()["url"])
        self.assertEqual(snapshot["sections"]["1.2"]["title"], "A title")
        self.assertIn("See this now.", snapshot["sections"]["1.2"]["text"])

    def test_canonical_utf8_normalization(self):
        self.assertEqual(normalize("Cafe\u0301  costs\t€5.\r\n\r\n Next  line. "), "Café costs €5.\n\nNext line.")

    def test_absent_section_not_failed_snapshot(self):
        before = extract_snapshot(BEFORE_XML, date="2025-12-07", url=metadata()["url"])
        after = extract_snapshot(b'<ROOT><SECTION N="301-10.2"><P>Keep this.</P></SECTION></ROOT>', date="2025-12-08", url=metadata()["url"])
        left, right = section_source(before, "301-10.1"), section_source(after, "301-10.1")
        self.assertEqual(right["text"], "")
        result = compare_texts(left["text"], right["text"], section="301-10.1", before_metadata=left, after_metadata=right)
        self.assertTrue(result["changes"])
        self.assertEqual({change["category"] for change in result["changes"]}, {"removed"})
        self.assertFalse(validate(result))

    def test_invalid_or_unrecognized_xml_never_implies_absence(self):
        for xml in (b"", b"<ROOT>", b"<html><body>failure</body></html>",
                    b'<!DOCTYPE x [<!ENTITY a "boom">]><ROOT/>'):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                extract_snapshot(xml, date="2025-12-07", url=metadata()["url"])

    def test_duplicate_identifiers_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            extract_snapshot(b'<ROOT><SECTION N="1"/><SECTION N="1"/></ROOT>', date="2025-12-07", url=metadata()["url"])

    def test_encoding_and_depth_do_not_bypass_parser_limits(self):
        xml = '<!DOCTYPE ROOT [<!ENTITY x "expanded">]><ROOT><SECTION N="1"><P>&x;</P></SECTION></ROOT>'
        with self.assertRaises(ValueError):
            extract_snapshot(xml.encode("utf-16"), date="2025-12-07", url=metadata()["url"])
        deep = '<ROOT><SECTION N="1">' + '<I>' * 150 + 'word' + '</I>' * 150 + '</SECTION></ROOT>'
        with self.assertRaisesRegex(ValueError, "nesting"):
            extract_snapshot(deep, date="2025-12-07", url=metadata()["url"])


class AlignmentTests(unittest.TestCase):
    def test_amount_date_negation_categories_and_exact_slices(self):
        cases = [("Rate $100.", "Rate $120.", "amount"),
                 ("Effective 2025-12-07.", "Effective 2025-12-08.", "date"),
                 ("Effective January 1, 2025.", "Effective January 2, 2025.", "date"),
                 ("You must retain receipts.", "You must not retain receipts.", "requirement")]
        for before, after, category in cases:
            with self.subTest(category=category):
                report = compare(before, after)
                self.assertEqual(report["changes"][0]["category"], category)
                self.assertTrue(report["changes"][0]["needs_review"])
                self.assertFalse(validate(report))
                for side in ("before", "after"):
                    evidence = report["changes"][0][f"{side}_evidence"]
                    self.assertEqual(report[side]["text"][evidence["start"]:evidence["end"]], evidence["quote"])

    def test_relocation_not_false_removal(self):
        report = compare("Alpha.\n\nBeta.\n\nGamma.", "Beta.\n\nGamma.\n\nAlpha.")
        self.assertEqual([c["category"] for c in report["changes"]], ["moved"])
        self.assertFalse(validate(report))

    def test_repeated_paragraphs_preserve_multiplicity(self):
        report = compare("Same.\n\nSame.\n\nOther.", "Same.\n\nOther.")
        self.assertEqual([c["category"] for c in report["changes"]], ["removed"])

    def test_whitespace_only_control(self):
        report = compare("Alpha  beta.\n\nGamma\t delta.", " Alpha beta. \n\nGamma delta.\n")
        self.assertEqual(report["changes"], [])
        self.assertEqual(compare("Alpha beta.\nGamma delta.", "Alpha beta.\n\nGamma delta.")["changes"], [])

    def test_inline_xml_formatting_only_control(self):
        one = extract_snapshot(BEFORE_XML, date="2025-12-07", url=metadata()["url"])
        two = extract_snapshot(BEFORE_XML.replace(b"<I>", b"").replace(b"</I>", b""), date="2025-12-08", url=metadata()["url"])
        self.assertEqual(compare(one["sections"]["301-10.1"]["text"], two["sections"]["301-10.1"]["text"])["changes"], [])

    def test_unicode_offsets_are_code_points(self):
        report = compare("🦉 Café.\n\nRate $2.", "🦉 Café.\n\nRate $3.")
        evidence = report["changes"][0]["before_evidence"]
        self.assertEqual(evidence["start"], len("🦉 Café.\n\n"))
        self.assertFalse(validate(report))

    def test_two_unrelated_edit_regions_not_cross_paired(self):
        report = compare("Delete me.\n\nKeep anchor.", "Keep anchor.\n\nAdd me.")
        self.assertEqual({c["category"] for c in report["changes"]}, {"removed", "added"})

    def test_source_metadata_required(self):
        with self.assertRaises(ValueError):
            compare_texts("old", "new", section="1", before_metadata={}, after_metadata={})

    def test_comparison_limits_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "code-point"):
            compare("x" * 1_000_001, "x")
        with self.assertRaisesRegex(ValueError, "paragraph"):
            compare("\n\n".join(["x"] * 2001), "x")


class ValidationExportTests(unittest.TestCase):
    def test_mismatched_malformed_and_negative_evidence_rejected(self):
        original = compare("Rate $10.", "Rate $20.")
        for evidence in ({"start": 0, "end": 4, "quote": "fake"},
                         {"start": -1, "end": 4, "quote": "Rate"},
                         {"start": True, "end": 4, "quote": "ate"},
                         {"start": 0, "end": 100, "quote": "Rate"},
                         "not an object", None):
            report = copy.deepcopy(original)
            report["changes"][0]["before_evidence"] = evidence
            with self.subTest(evidence=evidence):
                self.assertTrue(validate(report))

    def test_semantic_claim_not_certified_by_exact_quote(self):
        report = compare("Rate $10.", "Rate $20.")
        report["changes"][0]["summary"] = "An unsupported semantic assertion."
        self.assertFalse(validate(report))  # Explicitly ONLY grounding/shape.

    def test_invalid_category_and_nonfinite_cost_rejected(self):
        report = compare("a", "b")
        report["changes"][0]["category"] = "invented"
        report["analysis"]["cost_usd"] = float("nan")
        self.assertEqual(len(validate(report)), 2)
        report["changes"][0]["category"] = ["malformed"]
        self.assertTrue(validate(report))

    def test_safe_html_and_utf8_json_roundtrip(self):
        report = compare('<script>alert("old")</script> 🦉', '<img src=x onerror="bad"> 🦉', title="<unsafe>")
        content = export_html(report)
        self.assertNotIn("<script>", content)
        self.assertNotIn("<img src=x", content)
        self.assertIn("&lt;script&gt;", content)
        self.assertIn("Content-Security-Policy", content)
        self.assertEqual(json.loads(export_json(report)), report)

    def test_sqlite_append_only_and_provenance_conflicts(self):
        report = compare("Rate $10.", "Rate $20.")
        connection = connect(":memory:")
        try:
            record_comparison(connection, report)
            record_comparison(connection, report)
            self.assertEqual(connection.execute("SELECT count(*) FROM snapshots").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT count(*) FROM comparisons").fetchone()[0], 1)
            changed = copy.deepcopy(report)
            changed["before"]["text"] = "Conflicting source."
            changed["changes"] = []
            with self.assertRaisesRegex(ValueError, "conflicting section"):
                record_comparison(connection, changed)
        finally:
            connection.close()

    def test_cli_xml_compare_validate_and_html(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "before.xml").write_bytes(BEFORE_XML)
            (root / "after.xml").write_bytes(AFTER_XML)
            argv = ["compare", "--before", str(root / "before.xml"), "--after", str(root / "after.xml"),
                    "--before-date", "2025-12-07", "--after-date", "2025-12-08",
                    "--before-url", metadata()["url"], "--after-url", metadata()["url"],
                    "--section", "301-10.1", "--output", str(root / "report.json"),
                    "--html", str(root / "report.html"), "--database", str(root / "provenance.sqlite")]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(argv), 0)
                first_output = (root / 'report.json').read_bytes()
                self.assertEqual(main(argv), 0)
                self.assertEqual((root / 'report.json').read_bytes(), first_output)
                self.assertEqual(main(["validate", str(root / "report.json")]), 0)
            self.assertEqual(json.loads((root / "report.json").read_text())["changes"][0]["category"], "amount")
            self.assertTrue((root / "report.html").exists())


class FakeResponse:
    def __init__(self, body, headers=None, status=200):
        self.body, self.headers, self.status = body, headers or {}, status
    def read(self, amount):
        return self.body[:amount]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class FetchTests(unittest.TestCase):
    def fetch(self, body, headers=None, limit=1024, status=200):
        with patch("cited_change.fetch._check_url"), patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = FakeResponse(body, headers, status)
            return fetch_bytes(metadata()["url"], max_bytes=limit)

    def test_gzip_complete_and_bounded(self):
        self.assertEqual(self.fetch(gzip.compress(BEFORE_XML), {"Content-Encoding": "gzip"}), BEFORE_XML)
        with self.assertRaises(FetchError):
            self.fetch(gzip.compress(b"x" * 10000), {"Content-Encoding": "gzip"}, limit=200)

    def test_failures_never_return_empty_document(self):
        for body, headers, status in [(b"", {}, 200), (b"error", {}, 500),
                                      (b"abc", {"Content-Length": "5"}, 200),
                                      (b"not gzip", {"Content-Encoding": "gzip"}, 200)]:
            with self.subTest(body=body), self.assertRaises(FetchError):
                self.fetch(body, headers, status=status)

    def test_transport_limit_and_truncated_gzip(self):
        with self.assertRaises(FetchError):
            self.fetch(b"a" * 201, limit=200)
        with self.assertRaises(FetchError):
            self.fetch(gzip.compress(BEFORE_XML)[:-8], {"Content-Encoding": "gzip"})

    def test_private_hosts_and_http_rejected(self):
        for url in ("http://www.ecfr.gov/", "https://127.0.0.1/", "https://www.ecfr.gov@localhost/"):
            with self.subTest(url=url), self.assertRaises(FetchError):
                fetch_bytes(url)

    def test_private_dns_and_redirect_rejected(self):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaisesRegex(FetchError, "public IP"):
                fetch_bytes("https://www.ecfr.gov/title-41")
        from cited_change.fetch import _SafeRedirect
        handler = _SafeRedirect(("www.ecfr.gov",))
        with self.assertRaises(FetchError):
            handler.redirect_request(None, None, 302, "redirect", {}, "https://localhost/private")

    def test_failed_cli_fetch_does_not_write_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.xml"
            with patch("cited_change.cli.fetch_bytes", side_effect=FetchError("network failed")), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["fetch", "--url", metadata()["url"], "--date", "2025-12-07", "--output", str(path)]), 1)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
