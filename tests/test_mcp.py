"""MCP round-trip over real stdio with the fixture kane-cli."""
import json
import os
import subprocess
import sys
import unittest

from tests.helpers import EXAMPLES, FAKE, ROOT, tmp

class McpRoundTrip(unittest.TestCase):
    def test_round_trip(self):
        home = tmp()
        env = {**os.environ, 'PROOFLINE_HOME': str(home), 'PROOFLINE_KANE_BIN': f'{sys.executable} {FAKE}'}
        p = subprocess.Popen([sys.executable, '-m', 'proofline', 'mcp'], cwd=ROOT, env=env, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
        n = [0]
        def rpc(method, params=None):
            n[0] += 1
            p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': n[0], 'method': method, 'params': params or {}}) + '\n')
            p.stdin.flush()
            return json.loads(p.stdout.readline())
        def call(name, **args):
            r = rpc('tools/call', {'name': name, 'arguments': args})['result']
            self.assertFalse(r['isError'], r['content'][0]['text'])
            return json.loads(r['content'][0]['text'])
        try:
            self.assertEqual(rpc('tools/list')['error']['code'], -32002)
            init = rpc('initialize', {'protocolVersion': '2025-06-18'})
            self.assertEqual(init['result']['serverInfo']['name'], 'proofline')
            names = {t['name'] for t in rpc('tools/list')['result']['tools']}
            self.assertTrue({'ingest_prd', 'extract_context', 'list_context', 'design_tests', 'run_suite', 'maintain_drift',
                             'get_run', 'get_evidence', 'list_acs', 'export_manifest', 'export_dashboard', 'open_dashboard'} <= names)
            self.assertTrue(call('proofline_status')['kane']['installed'])
            sid = call('ingest_prd', path=str(EXAMPLES / 'prd-todomvc-v1.md'))['session_id']
            self.assertTrue(any(i['label'] == 'usecase' for i in call('extract_context')['items']))
            self.assertEqual(len(call('design_tests', use_case='uc-2')['tests']), 3)
            suite = call('run_suite')
            self.assertEqual((suite['passed'], suite['failed']), (2, 1))
            run = call('get_run', run_id=suite['results'][0]['run_id'])
            self.assertEqual(run['session_id'], sid)
            self.assertEqual(call('get_evidence', ac='AC-2.3')['verdict'], 'fail')
            self.assertEqual(len(call('list_acs')), 14)
            self.assertIn('AC-1.2', call('maintain_drift', new_prd=str(EXAMPLES / 'prd-todomvc-v2.md'))['changed'])
            self.assertTrue(call('export_manifest')['all_verified'])
            call('export_dashboard', out=str(home / 'site'))
            self.assertTrue((home / 'site' / 'index.html').exists())
            bad = rpc('tools/call', {'name': 'get_run', 'arguments': {'run_id': 'nope'}})['result']
            self.assertTrue(bad['isError'])
        finally:
            p.stdin.close()
            p.wait(timeout=10)

if __name__ == '__main__':
    unittest.main()
