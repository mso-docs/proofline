import json
import os
import unittest

from proofline.demo import run_demo
from proofline.pages import Scrubber, build_pages, close_open_runs
from tests.helpers import tmp

FAKE_EMAIL = 'jane.doe@example.org'
FAKE_USER = 'janedoe_kane_42'
FAKE_SHARE = 'https://app.example.test/share/US_ABCDEFGHIJKLMNOPQRSTUV0123456789'

class PagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tmp() / 'runs'
        cls.pl = run_demo(cls.root)
        sid = cls.pl.store.latest_session()
        cls.pl.store.emit(sid, None, 'log', {'line': f'user {FAKE_USER} <{FAKE_EMAIL}> link {FAKE_SHARE} '
                                             'https://test-manager.lambdatest.com/projects/01ABC/test-cases/01DEF "org_id": "3437500"'})
        rid = cls.pl.store.start_run(sid, 'context-extract', 'kane-cli context extract --mode agent')
        cls.pl.store.emit(sid, rid, 'kane', {'type': 'done', 'status': 'complete', 'exit_code': 0})
        cls.out = tmp() / 'site'
        cls.res = build_pages(cls.root, cls.out, kane_version='0.10.5', extra_values={FAKE_USER: '<KANE_USER>'})

    def test_no_private_values(self):
        for p in self.out.rglob('*'):
            if p.is_file() and p.suffix in ('.html', '.json', '.md', '.js'):
                text = p.read_text()
                for bad in (FAKE_EMAIL, FAKE_USER, 'US_ABCDEFGHIJ', 'test-manager.lambdatest.com', '3437500', os.path.expanduser('~')):
                    self.assertNotIn(bad, text, f'{bad} in {p.name}')

    def test_snapshot_shape(self):
        snap = json.loads((self.out / 'snapshot.json').read_text())
        self.assertTrue(snap['static'] and snap['redacted'])
        self.assertFalse([r for r in snap['runs'] if r['status'] == 'running'])
        self.assertTrue(snap['traces'])
        self.assertEqual(snap['status']['kane']['version'], '0.10.5')
        self.assertIn('window.PROOFLINE_SNAPSHOT', (self.out / 'index.html').read_text())

    def test_manifest_and_artifacts(self):
        m = json.loads((self.out / 'manifest.json').read_text())
        self.assertTrue(all(len(a['sha256']) == 64 and a['created_at'] for a in m['artifacts']))
        shots = [a for a in m['artifacts'] if a['kind'] == 'screenshot']
        self.assertTrue(shots and all(a['published'] and a['published_sha256'] == a['sha256'] for a in shots))
        self.assertFalse([a for a in m['artifacts'] if a['kind'] in ('log', 'evidence') and a['published']])
        self.assertFalse(list(self.out.rglob('*.evidence')))

    def test_live_runs_are_closed(self):
        # kane.call closes every non-test command, so a fresh pipeline has no dangling runs
        self.assertEqual(self.res['runs_closed'], 1)
        self.assertFalse([r for r in self.pl.store.runs() if r['status'] == 'running' and r['id'] != self._open()])

    def _open(self):
        return next(r['id'] for r in self.pl.store.runs() if r['status'] == 'running')

    def test_scrubber(self):
        s = Scrubber({FAKE_USER: '<KANE_USER>'})
        self.assertEqual(s.text(f'by {FAKE_USER.upper()}'), 'by <KANE_USER>')
        self.assertNotIn('blob.core', s.text('https://acct.blob.core.windows.net/x/y.png?sig=abc'))

if __name__ == '__main__':
    unittest.main()
