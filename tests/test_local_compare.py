import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from cited_change.engine import compare_texts
from cited_change.extraction import check_metadata, extract_snapshot, section_source
from cited_change.local_compare import compare_documents
from cited_change.reports import export_html, export_json
from cited_change.validation import validate
from test_documents import make_pdf


class LocalCompareTests(unittest.TestCase):
    def test_txt_citations_are_exact_displayed_code_points_and_ids_hash_bytes(self):
        before = "🦉 unchanged.\r\n\r\n  Rate $20. ".encode("utf-8")
        after = "🦉 unchanged.\n\n  Rate $30. ".encode("utf-8")
        with patch("urllib.request.build_opener", side_effect=AssertionError("No network allowed")):
            report = compare_documents(before, "/private/earlier.txt", after, "revised.txt")
        self.assertEqual(report["id"], f"local__{hashlib.sha256(before).hexdigest()}__{hashlib.sha256(after).hexdigest()}")
        self.assertFalse(validate(report))
        self.assertEqual(report["before"]["filename"], "earlier.txt")
        self.assertEqual(report["after"]["url"], "")
        self.assertEqual(report["analysis"]["method"], "deterministic")
        self.assertEqual(report["changes"][0]["category"], "amount")
        for side in ("before", "after"):
            evidence = report["changes"][0][f"{side}_evidence"]
            self.assertEqual(evidence["start"], len("🦉 unchanged.\n\n  "))
            self.assertEqual(report[side]["text"][evidence["start"]:evidence["end"]], evidence["quote"])
        self.assertEqual(report, json.loads(export_json(report)))

    def test_pdf_page_metadata_survives_engine_and_escaped_html_has_local_labels(self):
        report = compare_documents(make_pdf(["Stable paragraph.", "Rate $20."]), "earlier.pdf",
                                   make_pdf(["Stable paragraph.", "Rate $30."]), "revised.pdf")
        self.assertFalse(validate(report))
        self.assertEqual(report["before"]["pages"][1]["number"], 2)
        evidence = report["changes"][0]["before_evidence"]
        self.assertEqual(evidence["start"], report["before"]["pages"][1]["start"])
        markup = export_html(report)
        self.assertIn("Local file: earlier.pdf", markup)
        self.assertIn("earlier.pdf — Page 2", markup)
        self.assertIn("not a publication or effective date", markup)
        self.assertNotIn("Dated source", markup)
        self.assertNotIn('href=""', markup)
        self.assertNotIn("https://", markup)
        unsafe = compare_documents(b"<script>old</script>", "<unsafe>.txt", b"new", "new.txt")
        self.assertNotIn("<script>old", export_html(unsafe))
        self.assertIn("&lt;unsafe&gt;.txt", export_html(unsafe))

    def test_metadata_validation_rejects_malformed_pages_paths_and_fake_urls(self):
        report = compare_documents(make_pdf(["Rate $20.", "Keep."]), "old.pdf", b"Rate $30.", "new.txt")
        mutations = [{"url": "https://example.com/fake"}, {"filename": "/private/old.pdf"},
                     {"filename": r"C:\private\old.pdf"}, {"filename": "bad\n.pdf"},
                     {"format": "xml"}, {"source_kind": "invented"}, {"extraction_warnings": [1]},
                     {"pages": [{"number": True, "start": 0, "end": 5}]},
                     {"pages": [{"number": 1, "start": -1, "end": 5}]},
                     {"pages": [{"number": 1, "start": 0, "end": 5}]},
                     {"pages": [{"number": 1, "start": 0, "end": 100001}]},
                     {"pages": [{"number": 1, "start": 0, "end": 5},
                                {"number": 2, "start": 7, "end": len(report["before"]["text"])}]}]
        for mutation in mutations:
            broken = copy.deepcopy(report)
            broken["before"].update(mutation)
            with self.subTest(mutation=mutation):
                self.assertTrue(validate(broken))
        broken = copy.deepcopy(report)
        broken["before"]["text"] += "invented uncited appendix"
        self.assertTrue(validate(broken))

    def test_local_metadata_is_not_aliased_and_quote_tampering_is_rejected(self):
        report = compare_documents(make_pdf(["Rate $20."]), "old.pdf", b"Rate $30.", "new.txt")
        metadata = copy.deepcopy(report["before"])
        again = compare_texts(metadata["text"], report["after"]["text"], section="document",
                              before_metadata=metadata, after_metadata=report["after"])
        metadata["pages"][0]["end"] = 1
        self.assertFalse(validate(again))
        again["changes"][0]["before_evidence"]["quote"] = "invented"
        self.assertTrue(validate(again))

    def test_local_text_imported_reports_must_be_nonempty_and_bounded(self):
        report = compare_documents(b"old", "old.txt", b"new", "new.txt")
        for text in ("", " \n\t", "x" * 100001):
            broken = copy.deepcopy(report)
            broken["before"]["text"] = text
            broken["changes"] = []
            with self.subTest(length=len(text)):
                self.assertTrue(validate(broken))

    def test_external_url_checks_and_xml_schema_stay_unchanged(self):
        xml = b'<ROOT><SECTION N="1"><P>Rate $20.</P></SECTION></ROOT>'
        snapshot = extract_snapshot(xml, date="2025-01-01", url="https://example.org/source")
        source = section_source(snapshot, "1")
        self.assertEqual(set(source), {"date", "url", "snapshot_sha256", "text"})
        for bad_url in ("", "file:///private/document.txt", "relative.txt", "https://user:pass@example.org"):
            metadata = dict(source, url=bad_url)
            with self.subTest(url=bad_url), self.assertRaises(ValueError):
                check_metadata(metadata)
        for kind in (None, "external", "typo", []):
            metadata = dict(source, url="", source_kind=kind)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                check_metadata(metadata)

    def test_unchanged_documents_and_existing_paragraph_limit(self):
        report = compare_documents(b"Same.", "one.txt", b"Same.", "two.txt")
        self.assertEqual(report["changes"], [])
        self.assertFalse(validate(report))
        with self.assertRaisesRegex(ValueError, "paragraph"):
            compare_documents(b"x\n\n" * 2001, "one.txt", b"new", "two.txt")


if __name__ == "__main__":
    unittest.main()
