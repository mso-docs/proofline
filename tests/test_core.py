import io
import json
import os
import unittest
import zipfile

from proofline import adapter
from proofline.drift import prd_drift
from proofline.prd import ac_for_test, parse_prd
from proofline.redact import redact
from tests.helpers import EXAMPLES, tmp

TESTMD_STREAM = [
    {'type': 'stream_start', 'surface': 'testmd'},
    {'type': 'test_md_step_start', 'title': 'Open the app'}, {'type': 'step_start'}, {'type': 'step_end', 'status': 'passed'},
    {'type': 'test_md_step_end', 'status': 'passed', 'remark': 'opened'},
    {'type': 'test_md_step_start', 'title': 'Verify'}, {'type': 'test_md_step_end', 'status': 'failed', 'remark': 'not found'},
    {'type': 'test_md_done', 'overall_status': 'failed', 'duration_s': 3.5, 'session_id': 'x'},
]

class AdapterTests(unittest.TestCase):
    def test_testmd_stream(self):
        steps = adapter.steps_from_stream(TESTMD_STREAM)
        self.assertEqual([s['status'] for s in steps], ['passed', 'failed'])
        t = adapter.trace_for_ac(ac='AC-1.1', run_id='r1', session_id='s', test_path='a_test.md', events=TESTMD_STREAM, exit_code=1)
        self.assertEqual(t['case_id'], 'AC-1.1')
        self.assertEqual(t['evaluations'][0]['value'], 0.0)
        self.assertEqual(t['evaluations'][0]['rationale'], 'not found')
        self.assertEqual(t['duration_ms'], 3500)

    def test_run_stream(self):
        ev = [{'step': 2, 'status': 'running', 'remark': 'Step 1'}, {'step': 2, 'status': 'done', 'remark': 'navigate'},
              {'type': 'run_end', 'status': 'passed', 'duration': 20.5, 'one_liner': 'ok'}]
        self.assertEqual(len(adapter.steps_from_stream(ev)), 1)
        self.assertTrue(adapter.passed(adapter.final_result(ev), 0))

    def test_context_list_shape(self):
        line = {"id": "prd", "cid": "sha256:ee", "label": "source", "title": "prd", "trust": "-", "fresh": "fresh"}
        self.assertEqual(adapter.context_items([line, {'type': 'done'}]), [line])

    def test_evidence_pack(self):
        d = tmp()
        pack = d / 'x.evidence'
        with zipfile.ZipFile(pack, 'w') as z:
            z.writestr('steps/step-2/screenshot.png', b'\x89PNG2')
            z.writestr('steps/step-1/screenshot.png', b'\x89PNG1')
            z.writestr('../evil.png', b'no')
            z.writestr('result-summary.json', json.dumps({'status': 'passed'}))
        out = adapter.unpack_evidence(pack, d / 'shots')
        self.assertEqual([s['step'] for s in out['screenshots']], [1, 2])
        self.assertEqual(out['summary'], {'status': 'passed'})
        self.assertFalse((d / 'evil.png').exists())

class PrdDriftTests(unittest.TestCase):
    def test_parse(self):
        acs = parse_prd((EXAMPLES / 'prd-todomvc-v1.md').read_text())
        self.assertEqual(len(acs), 14)
        self.assertEqual(acs[0]['use_case'], 'UC-1')

    def test_ac_for_test(self):
        self.assertEqual(ac_for_test('t_test.md', '---\nac: AC-2.3\n---\n'), 'AC-2.3')
        self.assertEqual(ac_for_test('tests/ac_4_1_test.md', ''), 'AC-4.1')

    def test_drift(self):
        d = prd_drift((EXAMPLES / 'prd-todomvc-v1.md').read_text(), (EXAMPLES / 'prd-todomvc-v2.md').read_text(),
                      {'AC-1.2': ['tests/ac_1_2_test.md'], 'AC-5.2': ['tests/ac_5_2_test.md']})
        self.assertEqual(d['changed'], ['AC-1.2', 'AC-3.3'])
        self.assertEqual(d['added'], ['AC-2.4'])
        self.assertEqual(d['removed'], ['AC-5.2'])
        self.assertEqual({s['ac'] for s in d['stale']}, {'AC-1.2', 'AC-5.2'})
        self.assertIn('<mark>', ''.join(l.get('html', '') for l in d['lines']))

class RedactTests(unittest.TestCase):
    def test_env_and_patterns(self):
        os.environ['KANE_ACCESS_KEY'] = 'supersecretvalue123'
        try:
            s = redact('kane-cli run --access-key supersecretvalue123 token=abcdef12345 user me@example.com /Users/someone/x')
        finally:
            del os.environ['KANE_ACCESS_KEY']
        self.assertNotIn('supersecretvalue123', s)
        self.assertNotIn('abcdef12345', s)
        self.assertNotIn('me@example.com', s)
        self.assertNotIn('someone', s)

if __name__ == '__main__':
    unittest.main()
