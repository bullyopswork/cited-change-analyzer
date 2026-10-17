"""CLI routing regressions: real local TXT/PDF and legacy dated XML/text."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cited_change.cli import main
from cited_change.validation import validate
from test_documents import make_pdf


class LocalCLITests(unittest.TestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(arguments)
        self.assertEqual(code, 0, stderr.getvalue())
        return json.loads(stdout.getvalue())

    def test_auto_txt_pdf_and_mixed_use_actual_extraction_and_exact_citations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for before_suffix, after_suffix in [('txt', 'txt'), ('pdf', 'pdf'), ('txt', 'pdf')]:
                with self.subTest(before=before_suffix, after=after_suffix):
                    paths = []
                    for side, amount, suffix in [('before', 100, before_suffix), ('after', 150, after_suffix)]:
                        path = root / f'{side}.{suffix}'
                        text = f'Pay ${amount}.'
                        path.write_bytes(make_pdf([text]) if suffix == 'pdf' else text.encode())
                        paths.append(path)
                    report = self.invoke(['compare', '--before', str(paths[0]), '--after', str(paths[1])])
                    self.assertEqual(validate(report), [])
                    self.assertEqual(len(report['changes']), 1)
                    for side, amount, suffix in [('before', 100, before_suffix), ('after', 150, after_suffix)]:
                        self.assertEqual(report[side]['source_kind'], 'local')
                        self.assertEqual(report[side]['text'], f'Pay ${amount}.')
                        self.assertEqual(report[side]['format'], 'pdf' if suffix == 'pdf' else 'text')
                        evidence = report['changes'][0][side + '_evidence']
                        self.assertEqual(report[side]['text'][evidence['start']:evidence['end']], evidence['quote'])

    def test_dated_text_preserves_explicit_dates_and_urls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for side, amount in [('before', 100), ('after', 150)]:
                (root / (side + '.txt')).write_text(f'Pay ${amount}.', encoding='utf-8')
            report = self.invoke(['compare', '--format', 'text',
                                  '--before', str(root / 'before.txt'), '--after', str(root / 'after.txt'),
                                  '--before-date', '2024-01-01', '--after-date', '2024-02-01',
                                  '--before-url', 'https://example.org/2024-01-01/policy',
                                  '--after-url', 'https://example.org/2024-02-01/policy'])
            self.assertEqual(validate(report), [])
            self.assertEqual(report['before']['date'], '2024-01-01')
            self.assertEqual(report['after']['date'], '2024-02-01')
            self.assertEqual(report['before']['url'], 'https://example.org/2024-01-01/policy')
            self.assertEqual(report['after']['url'], 'https://example.org/2024-02-01/policy')
            self.assertNotEqual(report['before'].get('source_kind'), 'local')

    def test_auto_xml_retains_dated_snapshot_route(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for side, amount in [('before', 100), ('after', 150)]:
                xml = f'<ROOT><DIV8 TYPE="SECTION" N="1.1"><HEAD>Policy</HEAD><P>Pay ${amount}.</P></DIV8></ROOT>'
                (root / (side + '.xml')).write_text(xml, encoding='utf-8')
            with patch('cited_change.local_server.run_isolated', side_effect=AssertionError('XML used local-document route')):
                report = self.invoke(['compare', '--before', str(root / 'before.xml'), '--after', str(root / 'after.xml'),
                                      '--section', '1.1', '--before-date', '2024-01-01', '--after-date', '2024-02-01',
                                      '--before-url', 'https://example.org/2024-01-01/policy.xml',
                                      '--after-url', 'https://example.org/2024-02-01/policy.xml'])
            self.assertEqual(validate(report), [])
            self.assertEqual(report['section'], '1.1')
            self.assertEqual(report['before']['date'], '2024-01-01')
            self.assertEqual(report['after']['url'], 'https://example.org/2024-02-01/policy.xml')
            self.assertIn('Pay $150.', report['after']['text'])


if __name__ == '__main__':
    unittest.main()
