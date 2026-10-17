"""Local server boundary tests. Synthetic documents only, no model requests."""
import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cited_change.local_compare import compare_documents
from cited_change.local_server import LocalApplication, LocalHTTPServer


def offline_runner(mode, payload, **_kwargs):
    if mode == 'ai':
        raise ValueError('Simulated AI failure, local output must survive.')
    return compare_documents(payload['before_raw'], payload['before_filename'],
                             payload['after_raw'], payload['after_filename'])


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'index.html').write_text('<html><head></head><body>Local</body></html>')
        self.state = self.root/'uncreated-state'
        self.app = LocalApplication(web_root=self.root, state_root=self.state, runner=offline_runner)
        self.server = LocalHTTPServer(('127.0.0.1', 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.tmp.cleanup()

    def request(self, method, path, value=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        h = {'X-CCA-Token': self.app.token, 'Content-Type': 'application/json'}
        h.update(headers or {})
        body = None if value is None else json.dumps(value).encode()
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        result = (r.status, dict(r.headers), r.read())
        c.close()
        return result

    def payload(self):
        return {side: {'filename':side+'.txt', 'content_base64':base64.b64encode(text).decode()}
                for side,text in [('before', b'Pay $100.\n'),('after', b'Pay $150.\n')]}

    def completed_job(self):
        status, _, raw = self.request('POST', '/api/compare', self.payload())
        self.assertEqual(status,202)
        identifier=json.loads(raw)['job_id']
        for _ in range(50):
            status,_,raw=self.request('GET','/api/jobs/'+identifier)
            result=json.loads(raw)
            if result['status']!='running': return identifier,result
            time.sleep(.01)
        self.fail('job did not complete')

    def test_index_injects_only_session_token_no_key_and_is_not_cached(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY':'private-key-not-for-html'}):
            status,headers,body=self.request('GET','/')
        self.assertEqual(status,200)
        self.assertIn(self.app.token.encode(),body)
        self.assertNotIn(b'private-key-not-for-html',body)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertIn("connect-src 'self'",headers['Content-Security-Policy'])

    def test_api_rejects_absent_token_foreign_origin_and_host(self):
        for headers in [{'X-CCA-Token':''},{'Origin':'https://evil.invalid'},
                        {'Host':'evil.invalid'},{'Sec-Fetch-Site':'cross-site'}]:
            status,_,_=self.request('GET','/api/bootstrap',headers=headers)
            self.assertEqual(status,403,headers)

    def test_no_cors_and_no_path_traversal(self):
        self.assertEqual(self.request('OPTIONS','/api/compare')[0],403)
        self.assertEqual(self.request('GET','/%2e%2e/pyproject.toml')[0],404)

    def test_real_local_report_remains_memory_only(self):
        _,job=self.completed_job()
        self.assertEqual(job['status'],'succeeded')
        self.assertEqual(job['report']['before']['source_kind'],'local')
        self.assertEqual(job['report']['after']['text'],'Pay $150.\n')
        self.assertFalse(self.state.exists())
        self.assertNotIn('before_raw',job)

    def test_ai_requires_consent_and_failure_preserves_local(self):
        identifier,job=self.completed_job()
        url='/api/jobs/'+identifier+'/ai'
        self.assertEqual(self.request('POST',url,{'consent':False})[0],400)
        with patch.object(self.app,'configuration',return_value={'ai':{'configured':True}}):
            self.assertEqual(self.request('POST',url,{'consent':True})[0],202)
        for _ in range(50):
            _,_,raw=self.request('GET','/api/jobs/'+identifier)
            result=json.loads(raw)
            if result['status']!='running': break
            time.sleep(.01)
        self.assertEqual(result['status'],'error')
        self.assertEqual(result['report'],job['report'])
        with patch.object(self.app,'configuration',return_value={'ai':{'configured':True}}):
            self.assertEqual(self.request('POST',url,{'consent':True})[0],400)

    def test_bad_upload_does_not_schedule_any_job(self):
        for value in [{}, {'before':{'filename':'secret.txt','content_base64':'invalid !!!'}}]:
            self.assertEqual(self.request('POST','/api/compare',value)[0],400)
        self.assertFalse(self.app.jobs)

    def test_busy_gate_refuses_second_job(self):
        self.app.busy=True
        self.assertEqual(self.request('POST','/api/compare',self.payload())[0],429)

    def test_idle_expiry_uses_last_access_not_original_import(self):
        identifier,_=self.completed_job()
        self.app.jobs[identifier]['created']-=3600
        self.assertIsNotNone(self.app.job(identifier))
        self.app.jobs[identifier]['last_access']-=3600
        self.assertIsNone(self.app.job(identifier))


class LocalStartupTests(unittest.TestCase):
    def test_numeric_loopback_startup_never_uses_dns(self):
        app = LocalApplication(web_root=Path(__file__).parent)
        with patch('socket.getfqdn', side_effect=AssertionError('Startup must not resolve DNS.')), \
                patch('socket.getaddrinfo', side_effect=AssertionError('Startup must not resolve DNS.')):
            server = LocalHTTPServer(('127.0.0.1', 0), app)
        try:
            self.assertEqual(server.server_name, 'localhost')
            self.assertGreater(server.server_port, 0)
        finally:
            server.server_close()


if __name__=='__main__': unittest.main()
