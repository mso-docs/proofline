"""Proofline operations. The MCP server, the CLI, and the dashboard all call these."""
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from . import adapter, kane as kanemod
from .drift import prd_drift
from .prd import ac_for_test, parse_prd
from .store import Store, now

PIPELINE = ['context ingest', 'context extract', 'context list', 'design tests', 'testmd run', 'maintain']

def default_root():
    return Path(os.environ.get('PROOFLINE_HOME') or Path.cwd() / 'runs')

class Proofline:
    def __init__(self, root=None, workdir=None):
        self.root = Path(root or default_root())
        self.store = Store(self.root)
        self.workdir = Path(workdir or os.environ.get('PROOFLINE_WORKDIR') or self.root / 'workspace')
        self.kane = kanemod.Kane(self.store, self.workdir)

    # helpers
    def session(self, session_id=None, label=None):
        return session_id or self.store.latest_session() or self.store.new_session(label)

    def stage(self, session_id, name, state, detail=''):
        stages = self.store.setting('pipeline', {})
        stages[name] = dict(state=state, detail=detail, at=now(), session_id=session_id)
        self.store.save_setting('pipeline', stages)
        self.store.emit(session_id, None, 'stage', dict(name=name, state=state, detail=detail))

    def tests(self):
        found = []
        for p in sorted(self.workdir.rglob('*_test.md')):
            parts = p.relative_to(self.workdir).parts
            # kane-cli design writes tests to .testmuai/tests/; the rest of .testmuai is its own state
            if any(x.startswith('output-') or x in ('.context', 'node_modules') for x in parts) or \
                    ('.testmuai' in parts and parts[:2] != ('.testmuai', 'tests')):
                continue
            found.append(p)
        return found

    def acs_for_test(self, p, text=None):
        """PRD AC ids a test proves: Kane's `@verifies ac-N` refs mapped through kane_acs, else ac_for_test."""
        text = p.read_text(errors='replace') if text is None else text
        amap = self.store.setting('kane_acs', {})
        mapped = []
        for ref in adapter.verified_refs(text):
            prd = (amap.get(ref) or {}).get('prd_ac')
            if prd and prd not in mapped:
                mapped.append(prd)
        if mapped:
            return mapped
        ac = ac_for_test(p, text)
        known = {a['id'] for a in self.store.acs()}
        return [ac] if ac and (ac in known or not known) else []

    def _map_kane_acs(self, events):
        """Record Kane's criterion ids (ac-N) against the PRD AC each one restates."""
        amap = self.store.setting('kane_acs', {})
        prd_acs = self.store.acs()
        for ref, cid in adapter.minted_acs(events):
            digest = cid.split(':', 1)[-1]
            node = self.workdir / '.context' / 'derived' / 'nodes' / digest[:2] / (digest[2:] + '.json')
            try:
                text = json.loads(node.read_text())['content']['text']
            except (OSError, ValueError, KeyError, TypeError):
                continue
            prd, score = adapter.match_prd_ac(text, prd_acs)
            amap[ref] = dict(cid=cid, text=text, prd_ac=prd, score=score)
        self.store.save_setting('kane_acs', amap)
        return amap

    def tests_by_ac(self):
        out = {}
        for p in self.tests():
            for ac in self.acs_for_test(p):
                out.setdefault(ac, []).append(p.relative_to(self.workdir).as_posix())
        return out

    def _result(self, res, **extra):
        return dict(run_id=res['run_id'], exit_code=res['exit_code'], ok=res['exit_code'] == 0,
                    final=adapter.final_result(res['events']), **extra)

    # tools
    def status(self):
        return dict(kane=kanemod.installed(), root=str(self.root.name), session=self.store.latest_session(),
                    pipeline=self.store.setting('pipeline', {}), tests=len(self.tests()), acs=len(self.store.acs()))

    def ingest_prd(self, path, session_id=None, label=None):
        src = Path(path).expanduser()
        if not src.is_file():
            raise ValueError(f'PRD not found: {src.name}')
        sid = session_id or self.store.new_session(label or src.stem)
        self.stage(sid, 'context ingest', 'run', src.name)
        copy = self.store.session_dir(sid) / 'prd' / src.name
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, copy)
        self.store.add_artifact(sid, copy, kind='prd')
        work = self.workdir / src.name
        shutil.copy2(src, work)
        res = self.kane.call(sid, 'context-ingest', ['context', 'ingest', src.name, '--mode', 'ci', '--local'])
        text = src.read_text(errors='replace')
        acs = parse_prd(text, source=src.name)
        self.store.upsert_acs(sid, acs)
        prds = self.store.setting('prds', [])
        prds.append(dict(name=src.name, path=copy.relative_to(self.root).as_posix(), sha256=hashlib.sha256(text.encode()).hexdigest(), at=now(), session_id=sid))
        self.store.save_setting('prds', prds)
        self.stage(sid, 'context ingest', 'done' if res['exit_code'] == 0 else 'fail', f'{src.name} · {res["duration_s"]} s')
        return self._result(res, session_id=sid, acs=len(acs), use_cases=sorted({a['use_case'] for a in acs if a['use_case']}))

    def extract_context(self, session_id=None):
        sid = self.session(session_id)
        self.stage(sid, 'context extract', 'run')
        res = self.kane.call(sid, 'context-extract', ['context', 'extract', '--mode', 'agent'])
        listed = self.list_context(sid)
        n = len([i for i in listed['items'] if i.get('label') == 'usecase'])
        self.stage(sid, 'context extract', 'done' if res['exit_code'] == 0 else 'fail', f'{len(self.store.acs())} ACs · {n} use cases')
        return self._result(res, session_id=sid, items=listed['items'])

    def list_context(self, session_id=None):
        sid = self.session(session_id)
        res = self.kane.call(sid, 'context-list', ['context', 'list', '--json'])
        items = adapter.context_items(res['events'])
        self.store.save_setting('context', items)
        self.stage(sid, 'context list', 'done' if res['exit_code'] == 0 else 'fail', f'{len(items)} items')
        return self._result(res, session_id=sid, items=items)

    def design_tests(self, use_case, max_scenarios=None, session_id=None):
        sid = self.session(session_id)
        self.stage(sid, 'design tests', 'run', use_case)
        args = ['design', 'tests', '--use-case', use_case, '--mode', 'agent', '--allow-unreviewed']
        if max_scenarios:
            args += ['--max', str(int(max_scenarios))]
        res = self.kane.call(sid, 'design-tests', args)
        self._map_kane_acs(res['events'])
        tests = self.tests()
        for p in tests:
            self.store.add_artifact(sid, self._snap(sid, p), kind='testmd')
        self._link_tests()
        self.stage(sid, 'design tests', 'done' if res['exit_code'] == 0 else 'fail', f'{len(tests)} tests in workspace')
        return self._result(res, session_id=sid, tests=[p.relative_to(self.workdir).as_posix() for p in tests])

    def _snap(self, sid, p):
        dest = self.store.session_dir(sid) / 'tests' / p.relative_to(self.workdir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        return dest

    def _link_tests(self):
        for ac, paths in self.tests_by_ac().items():
            for a in self.store.acs():
                if a['id'] == ac and a.get('test_path') != paths[0]:
                    self.store.upsert_acs(a['session_id'], [dict(a, test_path=paths[0])])

    def run_suite(self, path=None, url=None, headless=True, session_id=None):
        sid = self.session(session_id)
        targets = [self.workdir / path] if path else self.tests()
        if not targets:
            raise ValueError('No *_test.md files yet; run design_tests first')
        self._link_tests()
        prd_hash = (self.store.setting('prds', [{}]) or [{}])[-1].get('sha256', '')
        results, suite = [], 'suite-' + now().replace(':', '').replace('-', '')[:15] + '-' + os.urandom(2).hex()
        for i, test in enumerate(targets, 1):
            rel = test.relative_to(self.workdir).as_posix()
            text = test.read_text(errors='replace')
            acs = self.acs_for_test(test, text) or [rel]
            ac = acs[0]
            self.stage(sid, 'testmd run', 'run', f'{i - 1} / {len(targets)} · {", ".join(acs)}')
            args = ['testmd', 'run', rel, '--agent']
            if headless:
                args.append('--headless')
            if url:
                args += ['--url', url]
            started = time.time()
            res = self.kane.call(sid, 'testmd-run', args)
            pack = res['evidence'] if res['evidence'] and Path(res['evidence']).exists() else self.kane.newest_evidence(started)
            evidence = None
            if pack:
                dest = self.store.session_dir(sid) / 'evidence' / res['run_id']
                dest.mkdir(parents=True, exist_ok=True)
                sealed = dest / Path(pack).name
                shutil.copy2(pack, sealed)
                self.store.add_artifact(sid, sealed, kind='evidence', run_id=res['run_id'], case_id=ac)
                unpacked = adapter.unpack_evidence(sealed, dest / 'shots')
                for shot in unpacked['screenshots']:
                    self.store.add_artifact(sid, shot['path'], kind='screenshot', run_id=res['run_id'], case_id=ac, step=shot['step'])
                evidence = dict(pack=sealed.relative_to(self.root).as_posix(), summary=unpacked['summary'], failures=unpacked['failures'],
                                screenshots=[Path(s['path']).relative_to(self.root).as_posix() for s in unpacked['screenshots']])
            if adapter.final_result(res['events']) is None and res['exit_code'] not in (0, 1):
                # kane-cli never ran the test (no browser, not logged in, bad flag): no verdict, not an AC failure
                why = next((l.strip() for l in res['stderr'].splitlines() if l.strip().lower().startswith('error')), f'exit code {res["exit_code"]}')
                self.store.finish_run(res['run_id'], 'error', res['exit_code'], why[:500], dict(ac=ac, acs=acs))
                self.store.emit(sid, res['run_id'], 'run_error', dict(acs=acs, error=why[:500]))
                results += [dict(ac=a, test=rel, run_id=res['run_id'], verdict='error', exit_code=res['exit_code'], error=why[:300]) for a in acs]
                continue
            fp = hashlib.sha256((text + prd_hash).encode()).hexdigest()[:16]
            # one Kane test can verify several criteria (`@verifies ac-2, ac-3`): one trace per AC
            traces = [adapter.trace_for_ac(ac=a, run_id=res['run_id'], session_id=sid, test_path=rel, events=res['events'],
                                           exit_code=res['exit_code'], evidence=evidence, fingerprint=fp) for a in acs]
            for trace in traces:
                trace['suite'] = suite
            self.store.ingest(traces)
            trace = traces[0]
            verdict = 'pass' if trace['evaluations'][0]['value'] else 'fail'
            self.store.finish_run(res['run_id'], verdict, res['exit_code'], trace['evaluations'][0]['rationale'], dict(ac=ac, acs=acs))
            for a in acs:
                self.store.emit(sid, res['run_id'], 'verdict', dict(ac=a, verdict=verdict, rationale=trace['evaluations'][0]['rationale']))
                results.append(dict(ac=a, test=rel, run_id=res['run_id'], verdict=verdict, exit_code=res['exit_code']))
        p = sum(r['verdict'] == 'pass' for r in results)
        f = sum(r['verdict'] == 'fail' for r in results)
        errors = len(results) - p - f
        self.stage(sid, 'testmd run', 'fail' if errors and not (p or f) else 'done',
                   f'{p} / {p + f} pass' + (f' · {errors} could not run' if errors else ''))
        return dict(session_id=sid, suite=suite, results=results, passed=p, failed=f, errors=errors)

    def maintain(self, new_prd, source_id=None, apply=False, session_id=None):
        sid = self.session(session_id)
        new = Path(new_prd).expanduser()
        if not new.is_file():
            raise ValueError(f'PRD not found: {new.name}')
        prds = self.store.setting('prds', [])
        if not prds:
            raise ValueError('Ingest a PRD first')
        old_path = self.root / prds[-1]['path']
        self.stage(sid, 'maintain', 'run', new.name)
        drift = prd_drift(old_path.read_text(errors='replace'), new.read_text(errors='replace'), self.tests_by_ac(),
                          old_name=old_path.name, new_name=new.name)
        copy = self.store.session_dir(sid) / 'prd' / ('next-' + new.name)
        shutil.copy2(new, copy)
        self.store.add_artifact(sid, copy, kind='prd')
        shutil.copy2(new, self.workdir / new.name)
        args = ['maintain', 'reconcile', '--from', new.name, '--mode', 'agent']
        if source_id:
            args += ['--source-id', source_id]
        args.append('--apply' if apply else '--plan')
        res = self.kane.call(sid, 'maintain', args)
        final, plan = adapter.final_result(res['events']), adapter.reconcile_plan(res['events'])
        if final is not None and plan and not final.get('summary'):
            final['summary'] = plan['summary']
        drift['kane'] = dict(run_id=res['run_id'], exit_code=res['exit_code'], final=final, plan=plan,
                             command='kane-cli ' + ' '.join(args))
        out = self.store.session_dir(sid) / 'drift.json'
        out.write_text(json.dumps(drift, indent=2))
        self.store.add_artifact(sid, out, kind='drift')
        self.store.save_setting('drift', drift)
        self.stage(sid, 'maintain', 'done' if res['exit_code'] == 0 else 'fail', f'{len(drift["stale"])} stale · {len(drift["untested_new"])} new')
        return dict(session_id=sid, **{k: drift[k] for k in ('changed', 'added', 'removed', 'stale', 'untested_new')}, kane=drift['kane'])

    def run_status(self, run_id):
        run = self.store.run(run_id)
        run['artifacts'] = self.store.artifacts(run_id=run_id)
        run['trace'] = next((t for t in self.store.traces() if t['run_id'] == run_id), None)
        return run

    def evidence(self, ac=None, run_id=None):
        traces = [t for t in self.store.traces() if (ac is None or t['case_id'] == ac) and (run_id is None or t['run_id'] == run_id)]
        if not traces:
            raise ValueError('No evidence for that AC or run yet')
        t = traces[-1]
        return dict(ac=t['case_id'], run_id=t['run_id'], verdict='pass' if t['evaluations'][0]['value'] else 'fail',
                    rationale=t['evaluations'][0]['rationale'], steps=t['spans'], evidence=t.get('evidence'),
                    screenshots=self.store.artifacts(kind='screenshot', run_id=t['run_id']), history=len(traces))

    def list_acs(self):
        return [dict(id=v['id'], title=v['title'], use_case=v.get('use_case'), verdict=v['verdict'], flaky=v['flaky'],
                     runs=len(v['history']), test=v.get('test_path')) for v in self.store.verdicts().values()]

    def snapshot(self):
        v = self.store.verdicts()
        return dict(generated_at=now(), status=self.status(), target=self.store.setting('target'), acs=list(v.values()), runs=self.store.runs()[-200:],
                    pipeline_order=PIPELINE, drift=self.store.setting('drift'), prds=self.store.setting('prds', []),
                    context=self.store.setting('context', []), artifacts=self.store.artifacts(kind='screenshot')[-300:],
                    events=self.store.events_since(max(0, self._last_seq() - 300)), manifest_count=len(self.store.artifacts()))

    def _last_seq(self):
        return self.store.last_seq()

    def export_manifest(self, out=None):
        m = self.store.manifest()
        out = Path(out) if out else self.root / 'manifest.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(m, indent=2))
        return dict(path=str(out.name), artifact_count=m['artifact_count'], manifest_sha256=m['manifest_sha256'],
                    all_verified=all(a['verified'] for a in m['artifacts']))
