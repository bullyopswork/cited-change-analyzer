import unittest
import io
import json
from pathlib import Path
import tempfile
from contextlib import redirect_stdout
from unittest.mock import patch
from cited_change.local_compare import compare_documents
from cited_change.cli import main


class LocalClassificationRegression(unittest.TestCase):
    def test_permission_may_is_not_a_calendar_month(self):
        result=compare_documents(b'Employees may submit receipts.','earlier.txt',
                                 b'Employees must submit receipts.','revised.txt')
        self.assertEqual(result['changes'][0]['category'],'requirement')
        self.assertTrue(result['changes'][0]['needs_review'])

    def test_actual_may_calendar_date_remains_a_date(self):
        result=compare_documents(b'Effective May 1, 2025.','earlier.txt',
                                 b'Effective May 2, 2025.','revised.txt')
        self.assertEqual(result['changes'][0]['category'],'date')

    def test_unavailable_cli_ai_preserves_report_but_is_not_success(self):
        report=compare_documents(b'Pay $100.','earlier.txt',b'Pay $150.','revised.txt')
        result=json.loads(json.dumps(report))
        result['analysis']['ai_coverage']={'status':'unavailable'}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'comparison.json';out=root/'preserved.json'
            source.write_text(json.dumps(report))
            with patch('cited_change.local_server.run_isolated',return_value=result),redirect_stdout(io.StringIO()) as output:
                code=main(['explain',str(source),'--consent','--budget-ledger',str(root/'ledger.sqlite'),'--output',str(out)])
            self.assertEqual(code,1)
            self.assertFalse(json.loads(output.getvalue())['ok'])
            self.assertEqual(json.loads(out.read_text())['before'],report['before'])


if __name__=='__main__':unittest.main()
