import hashlib
import io
import unittest
from datetime import datetime, timezone

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from cited_change.documents import (MAX_CHARACTERS, MAX_FILE_BYTES, DocumentError,
                                    extract_document)


def make_pdf(texts, *, encrypted=False):
    """A real selectable-text PDF, or blank/image-only equivalent pages."""
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_reference = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text is None:
            continue
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})})
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class DocumentTests(unittest.TestCase):
    def test_utf8_provenance_basename_and_inspectable_coordinates(self):
        raw = b"\xef\xbb\xbf" + "  🦉 Cafe\u0301\r\n\r\nRate\t$20.\r".encode("utf-8")
        snapshot = extract_document(raw, r"C:\private\earlier.TXT")
        self.assertEqual(snapshot["text"], "  🦉 Cafe\u0301\n\nRate\t$20.\n")
        self.assertEqual(snapshot["filename"], "earlier.TXT")
        self.assertEqual(snapshot["snapshot_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(snapshot["date"], datetime.now(timezone.utc).date().isoformat())
        self.assertEqual(snapshot["url"], "")
        self.assertEqual(snapshot["source_kind"], "local")
        self.assertEqual(snapshot["format"], "text")
        self.assertEqual(snapshot["extraction_warnings"], [])

    def test_txt_fail_closed(self):
        cases = [(b"", "a.txt", "nonempty"), (b" \n\t", "a.txt", "non-whitespace"),
                 (b"\xff", "a.txt", "UTF-8"), (b"a\x00b", "a.txt", "binary"),
                 (b"text", "a.docx", "Unsupported"), (b"text", "a", "Unsupported"),
                 (b"text", "/private/", "basename"), (b"text", "a\n.txt", "control")]
        for raw, filename, message in cases:
            with self.subTest(filename=filename, raw=raw), self.assertRaisesRegex(DocumentError, message):
                extract_document(raw, filename)

    def test_byte_and_extracted_character_bounds_without_truncation(self):
        with self.assertRaisesRegex(DocumentError, "10 MiB"):
            extract_document(b"x" * (MAX_FILE_BYTES + 1), "large.txt")
        snapshot = extract_document(("🦉" * MAX_CHARACTERS).encode("utf-8"), "unicode.txt")
        self.assertEqual(len(snapshot["text"]), MAX_CHARACTERS)
        with self.assertRaisesRegex(DocumentError, "100000"):
            extract_document(b"x" * (MAX_CHARACTERS + 1), "large.txt")
        with self.assertRaisesRegex(DocumentError, "100000"):
            extract_document(make_pdf(["x" * (MAX_CHARACTERS + 1)]), "large.pdf")

    def test_pdf_real_text_and_exact_page_slices(self):
        raw = make_pdf(["Earlier rate $20.", "Keep receipts."])
        snapshot = extract_document(raw, "/private/files/policy.pdf")
        self.assertEqual(snapshot["filename"], "policy.pdf")
        self.assertEqual(snapshot["format"], "pdf")
        self.assertEqual(snapshot["snapshot_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual([p["number"] for p in snapshot["pages"]], [1, 2])
        for page, expected in zip(snapshot["pages"], ["Earlier rate $20.", "Keep receipts."]):
            self.assertEqual(snapshot["text"][page["start"]:page["end"]].strip(), expected)
        self.assertEqual(snapshot["text"][snapshot["pages"][0]["end"]:
                                          snapshot["pages"][1]["start"]], "\n\n")
        self.assertEqual(snapshot["pages"][-1]["end"], len(snapshot["text"]))

    def test_pdf_encrypted_malformed_empty_and_scanned_rejected(self):
        cases = [(make_pdf(["Text"], encrypted=True), "Encrypted"),
                 (b"not a PDF", "Malformed"), (b"%PDF-1.7\ntruncated", "Malformed"),
                 (make_pdf([]), "1 to 50"), (make_pdf([None, None]), "no selectable text")]
        for raw, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(DocumentError, message):
                extract_document(raw, "source.pdf")

    def test_pdf_page_limit_and_mixed_nonselectable_page_warning(self):
        snapshot = extract_document(make_pdf(["Text"] + [None] * 49), "fifty.pdf")
        self.assertEqual(len(snapshot["pages"]), 50)
        self.assertEqual(len(snapshot["extraction_warnings"]), 50)
        self.assertTrue(any("Page 50 has no selectable text" in w for w in snapshot["extraction_warnings"]))
        with self.assertRaisesRegex(DocumentError, "1 to 50"):
            extract_document(make_pdf(["Text"] * 51), "too-many.pdf")


if __name__ == "__main__":
    unittest.main()
