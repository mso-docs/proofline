"""Shapes captured from a live kane-cli 0.10.5 run against the TodoMVC demo (Nov 17, 2026),
trimmed and redacted: ids, share links, user names, emails and local paths are replaced."""
import io
import os
import shutil
import sys
import unittest
import zipfile
from pathlib import Path

from proofline import adapter
from proofline.prd import parse_prd
from proofline.service import Proofline
from tests.helpers import EXAMPLES, tmp

DESIGN_EVENTS = [
    {"type": "run_start", "v": 1, "verb": "design", "mode": "agent", "use_case": "uc-1", "session": "as-REDACTED"},
    {"type": "usage", "v": 1, "verb": "design", "credits": 2.25, "total_credits": 2.25},
    {"type": "commit", "v": 1, "verb": "design", "acs": 1, "scenarios": 0, "tests": 0,
     "minted": [{"temp_ref": "a1", "cid": "sha256:aaaa01", "logical_id": "ac-1"}]},
    {"type": "commit", "v": 1, "verb": "design", "acs": 0, "scenarios": 2, "tests": 0,
     "minted": [{"temp_ref": "s1", "cid": "sha256:cccc01", "logical_id": "sc-1"}]},
    {"type": "commit", "v": 1, "verb": "design", "acs": 2, "scenarios": 0, "tests": 0,
     "minted": [{"temp_ref": "a2", "cid": "sha256:aaaa02", "logical_id": "ac-2"},
                {"temp_ref": "a3", "cid": "sha256:aaaa03", "logical_id": "ac-3"}]},
    {"type": "commit", "v": 1, "verb": "design", "acs": 0, "scenarios": 0, "tests": 2,
     "awaiting_approval": [{"test": "t-1", "criterion": "ac-1"}],
     "minted": [{"temp_ref": "t1", "cid": "sha256:dddd01", "logical_id": "t-1"}]},
    {"type": "done", "v": 1, "verb": "design", "status": "complete", "exit_code": 0},
]
KANE_AC_TEXT = {
    "ac-1": "Submitting an empty title does not add an empty-titled todo to the list.",
    "ac-2": "Entering a nonempty title and pressing Enter adds a todo with that title to the list.",
    "ac-3": "After the first todo is added, the remaining-items counter displays \"1 item left\".",
}
TEST_MD = """---
assurance:
  id: t-2
  base: sha256:REDACTED
---
# First titled todo appears with one item left

## Step 1

Open https://demo.playwright.dev/todomvc and establish an empty todo list.

## Step 2 @verifies ac-2, ac-3

Enter A in the todo title entry field and submit with Enter, then assert the counter reads "1 item left".
"""
TESTMD_EVENTS = [
    {"type": "stream_start", "cli_version": "0.10.5", "surface": "testmd", "v": 1},
    {"type": "test_md_step_start", "step_index": 1, "heading": "Step 1", "ref": None, "v": 1},
    {"type": "run_start", "v": 1},
    {"type": "step_start", "v": 1},
    {"type": "step_end", "status": "passed", "v": 1},
    {"type": "run_end", "status": "passed", "one_liner": "reached the to-do title entry field on TodoMVC",
     "reason": "Objective completed", "duration": 16.5, "credits_consumed": 9.19},
    {"type": "test_md_step_end", "step_index": 1, "status": "passed", "duration_s": 16.5, "v": 1},
    {"type": "test_md_step_start", "step_index": 2, "heading": "Step 2", "ref": None, "v": 1},
    {"type": "step_end", "index": 1, "status": "passed", "summary": "press_key: PRIMARY: submit with Enter", "kind": "press_key"},
    {"type": "step_end", "index": 2, "status": "failed", "summary": "assert: counter read 2 items left", "kind": "assert"},
    {"type": "test_md_step_end", "step_index": 2, "status": "failed", "duration_s": 29.9, "v": 1},
    {"type": "test_md_step_start", "step_index": 3, "heading": "Step 3", "ref": None, "v": 1},
    {"type": "run_end", "status": "failed", "one_liner": "could not remove the todo", "reason": "Assertion failed"},
    {"type": "test_md_step_end", "step_index": 3, "status": "failed", "duration_s": 3.1, "v": 1},
    {"type": "test_md_done", "overall_status": "failed", "duration_s": 184, "session_id": "REDACTED",
     "share_url": "https://example.invalid/share/REDACTED", "coverage": {"status": "written", "pct": 5}, "v": 1},
]

class LiveShapeTests(unittest.TestCase):
    def test_verifies_refs(self):
        self.assertEqual(adapter.verified_refs(TEST_MD), ['ac-2', 'ac-3'])

    def test_minted_acs(self):
        self.assertEqual(adapter.minted_acs(DESIGN_EVENTS), [('ac-1', 'sha256:aaaa01'), ('ac-2', 'sha256:aaaa02'), ('ac-3', 'sha256:aaaa03')])

    def test_kane_criteria_map_to_prd(self):
        prd = parse_prd((EXAMPLES / 'prd-todomvc-v1.md').read_text())
        got = {k: adapter.match_prd_ac(v, prd)[0] for k, v in KANE_AC_TEXT.items()}
        self.assertEqual(got, {'ac-1': 'AC-1.2', 'ac-2': 'AC-1.1', 'ac-3': 'AC-1.3'})
        self.assertIsNone(adapter.match_prd_ac('Upload a profile photo from the camera roll', prd)[0])

    def test_testmd_steps_and_result(self):
        steps = adapter.steps_from_stream(TESTMD_EVENTS)
        self.assertEqual([(s['title'], s['status']) for s in steps], [('Step 1', 'passed'), ('Step 2', 'failed'), ('Step 3', 'failed')])
        self.assertEqual(steps[0]['remark'], 'reached the to-do title entry field on TodoMVC')
        self.assertEqual(steps[1]['remark'], 'assert: counter read 2 items left')
        self.assertEqual(steps[2]['remark'], 'could not remove the todo')
        res = adapter.final_result(TESTMD_EVENTS)
        self.assertFalse(adapter.passed(res, 1))
        trace = adapter.trace_for_ac(ac='AC-1.3', run_id='r1', session_id='s', test_path='t', events=TESTMD_EVENTS, exit_code=1)
        self.assertEqual(trace['evaluations'][0]['rationale'], 'assert: counter read 2 items left')

    def test_evidence_pack_layout(self):
        d = tmp()
        pack = d / 'x.evidence'
        with zipfile.ZipFile(pack, 'w') as z:
            for step in ('1-0-1', '2-0-2', '3-1-1'):
                z.writestr(f'tests/first-titled-todo-751ca4f2/steps/{step}/screenshot.jpg', b'\xff\xd8' + step.encode())
                z.writestr(f'tests/first-titled-todo-751ca4f2/steps/{step}/step.json', '{"status": "passed"}')
            z.writestr('tests/first-titled-todo-751ca4f2/v16-trajectory/0-run_summary.json',
                       '{"objective": "x", "user_email": "someone@example.com"}')
            z.writestr('run.yaml', 'status: finalized\n')
        out = adapter.unpack_evidence(pack, d / 'shots')
        self.assertEqual([s['step'] for s in out['screenshots']], [1, 2, 3])
        self.assertEqual(len({Path(s['path']).name for s in out['screenshots']}), 3)
        self.assertNotIn('someone@example.com', str(out['summary']))

RECONCILE_EVENTS = [
    {"type": "run_start", "v": 1, "verb": "reconcile", "session": "as-REDACTED"},
    {"type": "validate_failed", "v": 1, "verb": "reconcile", "source_id": "prd-todomvc-v1", "codes": ["UNKNOWN_MATCH"], "repairing": True},
    {"type": "reconcile_plan", "v": 1, "verb": "reconcile", "source_id": "prd-todomvc-v1",
     "plan_path": "~/proofline/runs/live/workspace/.context/reconcile/plans/2026-11-17T22-55-07-387Z-prd-todomvc-v1.json",
     "rows": [{"kind": "ADD", "ref": "uc-10", "why": "new use-case extracted from prd-todomvc-v1"},
              {"kind": "MODIFY", "ref": "uc-1", "why": "updated: description, criteria (staged \u2014 commits on approval)"},
              {"kind": "MODIFY", "ref": "uc-3", "why": "stale (structural)"}], "archive": []},
    {"type": "reconcile_summary", "v": 1, "verb": "reconcile", "applied": 0, "skipped": 0, "deferred": 0, "plan_only": 0, "failed": 0},
    {"type": "done", "v": 1, "verb": "reconcile", "status": "complete", "exit_code": 0},
]

class ReconcileShapeTests(unittest.TestCase):
    def test_reconcile_plan_rows(self):
        plan = adapter.reconcile_plan(RECONCILE_EVENTS)
        self.assertEqual(plan['counts'], {'add': 1, 'modify': 2})
        self.assertEqual(plan['summary'], '3 proposals (1 add, 2 modify)')
        self.assertEqual(plan['plan'], '2026-11-17T22-55-07-387Z-prd-todomvc-v1.json')
        self.assertEqual(adapter.final_result(RECONCILE_EVENTS)['status'], 'complete')
        self.assertIsNone(adapter.reconcile_plan(DESIGN_EVENTS))

class LiveWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.get('PROOFLINE_KANE_BIN')
        self.root = tmp()

    def tearDown(self):
        if self.old is None:
            os.environ.pop('PROOFLINE_KANE_BIN', None)
        else:
            os.environ['PROOFLINE_KANE_BIN'] = self.old

    def test_tests_found_under_testmuai_and_mapped(self):
        pl = Proofline(self.root)
        pl.store.upsert_acs(pl.store.new_session('t'), parse_prd((EXAMPLES / 'prd-todomvc-v1.md').read_text()))
        tdir = pl.workdir / '.testmuai' / 'tests'
        (tdir / 'output-first').mkdir(parents=True)
        (tdir / 'first_test.md').write_text(TEST_MD)
        (tdir / 'output-first' / 'copy_test.md').write_text(TEST_MD)
        (pl.workdir / '.testmuai' / 'evidence').mkdir()
        (pl.workdir / '.testmuai' / 'evidence' / 'stray_test.md').write_text(TEST_MD)
        self.assertEqual([p.name for p in pl.tests()], ['first_test.md'])
        for ref, text in KANE_AC_TEXT.items():
            digest = 'ab' + ref.replace('-', '') * 8
            node = pl.workdir / '.context' / 'derived' / 'nodes' / digest[:2] / (digest[2:] + '.json')
            node.parent.mkdir(parents=True, exist_ok=True)
            node.write_text('{"label": "ac", "content": {"text": %s}}' % __import__('json').dumps(text))
        events = [{"type": "commit", "minted": [{"cid": 'sha256:ab' + r.replace('-', '') * 8, "logical_id": r} for r in KANE_AC_TEXT]}]
        pl._map_kane_acs(events)
        self.assertEqual(pl.tests_by_ac(), {'AC-1.1': ['.testmuai/tests/first_test.md'], 'AC-1.3': ['.testmuai/tests/first_test.md']})

    def test_kane_that_cannot_start_a_browser_is_an_error_not_a_failure(self):
        script = self.root / 'nochrome.py'
        script.write_text('import sys\nprint(\'{"type":"stream_start","cli_version":"0.10.5","surface":"testmd","v":1}\')\n'
                          'sys.stderr.write("error: Chrome launch failed: Google Chrome is required but was not found\\n")\n'
                          'sys.exit(2)\n')
        os.environ['PROOFLINE_KANE_BIN'] = f'{sys.executable} {script}'
        pl = Proofline(self.root)
        pl.store.new_session('t')
        (pl.workdir / 'ac-1-2_test.md').write_text('# t\n\n## Step 1\n\nOpen the page\n')
        out = pl.run_suite()
        self.assertEqual((out['passed'], out['failed'], out['errors']), (0, 0, 1))
        self.assertTrue(out['results'][0]['error'].startswith('error: Chrome launch failed'))
        self.assertEqual(pl.store.traces(), [])
        self.assertEqual(pl.store.run(out['results'][0]['run_id'])['status'], 'error')

if __name__ == '__main__':
    unittest.main()
