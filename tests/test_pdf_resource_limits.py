"""Regressions for tiny compressed PDFs with excessive decoded page content."""
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject

from cited_change.documents import DocumentError, extract_document
from cited_change.local_server import MAX_WORKER_RSS, run_isolated


def expansion_pdf(characters=1_000_000, repetitions=16):
    writer=PdfWriter()
    page=writer.add_blank_page(width=612,height=792)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),
                           NameObject('/Subtype'):NameObject('/Type1'),
                           NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 10 20 Td ('+b'A'*characters+b') Tj ET')
    reference=writer._add_object(stream.flate_encode())
    page[NameObject('/Contents')]=ArrayObject([reference]*repetitions)
    output=io.BytesIO();writer.write(output)
    return output.getvalue()


class ResourceLimitTests(unittest.TestCase):
    def test_repeated_stream_bomb_is_rejected_before_text_extraction(self):
        raw=expansion_pdf()
        self.assertLess(len(raw),5000)
        with patch('pypdf._page.PageObject.extract_text') as extract:
            with self.assertRaisesRegex(DocumentError,'complexity|unsupported'):
                extract_document(raw,'expansion.pdf')
            extract.assert_not_called()

    def test_single_oversize_decode_is_rejected_before_text_extraction(self):
        raw=expansion_pdf(characters=3_000_000,repetitions=1)
        self.assertLess(len(raw),10000)
        with patch('pypdf._page.PageObject.extract_text') as extract:
            with self.assertRaises(DocumentError):
                extract_document(raw,'expansion.pdf')
            extract.assert_not_called()

    def test_worker_memory_watchdog_terminates_and_reaps_owned_child(self):
        meter=SimpleNamespace(memory_info=lambda:SimpleNamespace(rss=MAX_WORKER_RSS+1))
        with patch('cited_change.local_server.psutil.Process',return_value=meter):
            with self.assertRaisesRegex(ValueError,'memory limit'):
                run_isolated('compare',{'before_raw':b'Before','before_filename':'before.txt',
                                        'after_raw':b'After','after_filename':'after.txt'})


if __name__=='__main__':unittest.main()
