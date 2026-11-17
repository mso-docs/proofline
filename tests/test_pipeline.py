import json
import os
import urllib.request
import unittest

from proofline.export_static import export_static
from proofline.server import serve
from proofline.service import Proofline
from tests.helpers import EXAMPLES, fixture_env, tmp

class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_env()
        os.environ['KANE_ACCESS_KEY'] = 'pl-test-secret-xyz'
        cls.pl = Proofline(tmp())
        cls.ingest = cls.pl.ingest_prd(EXAMPLES / 'prd-todomvc-v1.md')
        cls.pl.extract_context()
        for uc in ('uc-1', 'uc-2', 'uc-3'):
            cls.pl.design_tests(uc)
        cls.suites = [cls.pl.run_suite() for _ in range(3)]
        cls.drift = cls.pl.maintain(EXAMPLES / 'prd-todomvc-v2.md')

    @classmethod
    def tearDownClass(cls):
        os.environ.pop('KANE_ACCESS_KEY', None)

    def test_acs_and_verdicts(self):
        self.assertEqual(self.ingest['acs'], 14)
        acs = {a['id']: a for a in self.pl.list_acs()}
        self.assertEqual(acs['AC-1.1']['verdict'], 'pass')
        self.assertEqual(acs['AC-2.3']['verdict'], 'fail')
        self.assertTrue(acs['AC-3.3']['flaky'])
        self.assertFalse(acs['AC-2.3']['flaky'])
        self.assertEqual(acs['AC-4.1']['verdict'], 'idle')

    def test_evidence_and_screenshots(self):
        ev = self.pl.evidence(ac='AC-2.3')
        self.assertEqual(ev['verdict'], 'fail')
        self.assertEqual(len(ev['screenshots']), 4)
        self.assertEqual([s['status'] for s in ev['steps']][-1], 'failed')

    def test_manifest_verified_and_stamped(self):
        m = self.pl.store.manifest()
        self.assertGreater(m['artifact_count'], 20)
        self.assertTrue(all(a['verified'] and a['created_at'] and a['session_id'] for a in m['artifacts']))

    def test_no_secret_on_disk(self):
        for p in self.pl.root.rglob('*'):
            if p.is_file() and p.suffix in ('.ndjson', '.log', '.json', '.sqlite3'):
                self.assertNotIn(b'pl-test-secret-xyz', p.read_bytes(), p.name)

    def test_compare_runs(self):
        a = self.suites[0]['results'][0]['run_id']
        self.assertEqual(self.pl.store.compare_runs(a, a)['mean_delta'], 0)

    def test_drift(self):
        self.assertIn('AC-1.2', self.drift['changed'])
        self.assertEqual(self.drift['kane']['exit_code'], 0)

    def test_server_and_stream(self):
        srv = serve(self.pl, 0, block=False)
        try:
            base = f'http://127.0.0.1:{srv.server_port}'
            snap = json.load(urllib.request.urlopen(base + '/api/snapshot'))
            self.assertEqual(len(snap['acs']), 14)
            srv.once = True
            body = urllib.request.urlopen(base + '/api/stream?since=0', timeout=10).read().decode()
            self.assertIn('event: verdict', body)
            self.assertEqual(urllib.request.urlopen(base + '/').status, 200)
            shot = snap['artifacts'][0]['path']
            self.assertEqual(urllib.request.urlopen(base + '/artifacts/' + shot).read()[:4], b'\x89PNG')
            with self.assertRaises(Exception):
                urllib.request.urlopen(base + '/artifacts/../../etc/passwd')
        finally:
            srv.shutdown()

    def test_export_static(self):
        out = tmp() / 'site'
        export_static(self.pl, out)
        html = (out / 'index.html').read_text()
        self.assertIn('PROOFLINE_SNAPSHOT', html)
        self.assertTrue((out / 'manifest.json').exists())

if __name__ == '__main__':
    unittest.main()
