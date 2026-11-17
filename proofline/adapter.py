"""Kane adapter: kane-cli output -> Evalboard-style traces.

Inputs it understands (documented kane-cli agent-mode contract, stream v1):
  * `testmd run --agent`: typed lines (test_md_step_start/end wrapping run_start,
    step_start, step_event, step_end, run_end) ending with test_md_done
    {overall_status, duration_s, session_id, share_url}
  * `run --agent`: untyped step lines {step,status,remark} and a final run_end
  * `context list --json`: one item per line {id, cid, label, title, trust, fresh}
  * sealed evidence packs (*.evidence, a zip): per-step screenshots, logs,
    a result summary, and failure records
One AC is one case: case_id is the AC id; pass/fail is the `ac_pass` score.
"""
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

from .redact import redact_obj

IMAGE = re.compile(r'\.(png|jpe?g|webp)$', re.I)
STEP_NUM = re.compile(r'(?:step[-_]?)(\d+)', re.I)
# kane-cli 0.10 packs: tests/<test>/steps/<ordinal>-<run>-<sub>/screenshot.jpg
STEP_DIR = re.compile(r'^(\d+)(?:-\d+)*$')

VERIFIES = re.compile(r'@verifies\s+((?:ac-\d+)(?:\s*,\s*ac-\d+)*)', re.I)
STOP = set('a an and the to it is of with that after in on are be its for by as does when'.split())

def verified_refs(text):
    """Kane's own criterion ids a *_test.md checks, from its `## Step N @verifies ac-2, ac-3` headings."""
    refs = []
    for m in VERIFIES.finditer(text):
        for r in re.split(r'\s*,\s*', m.group(1).strip()):
            r = r.lower()
            if r not in refs:
                refs.append(r)
    return refs

def minted_acs(events):
    """[(logical_id, cid)] for the criteria `design tests` committed (its `commit` events)."""
    out = []
    for e in events:
        if e.get('type') == 'commit':
            for m in e.get('minted') or []:
                if str(m.get('logical_id', '')).lower().startswith('ac-') and m.get('cid'):
                    out.append((m['logical_id'].lower(), m['cid']))
    return out

def _words(text):
    out = set()
    for w in re.findall(r'[a-z0-9]+', (text or '').lower()):
        if w in STOP:
            continue
        for suf in ('ing', 'ed', 'es', 's'):
            if len(w) > len(suf) + 2 and w.endswith(suf):
                w = w[:-len(suf)]
                break
        out.add(w)
    return out

def match_prd_ac(kane_text, prd_acs, threshold=0.2):
    """Kane restates criteria in its own words and numbers them itself (ac-1, ac-2, ...), so map each
    one to the PRD criterion it restates by word overlap. Returns (prd_ac_id, score) or (None, best)."""
    kw, best = _words(kane_text), (None, 0.0)
    for a in prd_acs:
        pw = _words(a['title'])
        if kw and pw:
            score = len(kw & pw) / len(kw | pw)
            if score > best[1]:
                best = (a['id'], round(score, 3))
    return best if best[1] >= threshold else (None, best[1])

def context_items(events):
    return [e for e in events if isinstance(e, dict) and 'id' in e and 'label' in e]

def steps_from_stream(events):
    """Normalize either stream shape into [{index, title, status, remark, ts}]."""
    steps, current = [], None
    md = any(e.get('type') == 'test_md_step_start' for e in events)
    for e in events:
        t = e.get('type')
        if md and t in ('step_start', 'step_end'):
            # inner agent steps of a testmd step: keep the assertion (else the latest) summary as the remark
            if t == 'step_end' and current is not None and e.get('summary') and \
                    (e.get('kind') == 'assert' or not current['remark'].startswith('assert')):
                current['remark'] = e['summary']
            continue
        if t in ('test_md_step_start', 'step_start'):
            current = dict(index=len(steps) + 1, title=e.get('title') or e.get('heading') or e.get('step_title') or e.get('remark') or e.get('name') or f'Step {len(steps)+1}',
                           status='running', remark='', started=e.get('ts'))
            steps.append(current)
        elif md and t == 'run_end' and current is not None:
            # testmd: each *_test.md step runs as an inner agent run; its one_liner says what it did
            if not current['remark'].startswith('assert'):
                current['remark'] = e.get('one_liner') or e.get('reason') or current['remark']
        elif t in ('test_md_step_end', 'step_end') and current is not None:
            st = (e.get('status') or e.get('result') or '').lower()
            current['status'] = 'passed' if st in ('passed', 'pass', 'done', 'success', 'ok') else 'failed' if st else current['status']
            current['remark'] = e.get('remark') or e.get('summary') or e.get('reason') or current['remark']
            current['ended'] = e.get('ts')
            if t == 'test_md_step_end':
                current = None
        elif t is None and 'step' in e and e.get('status') in ('done', 'failed'):
            steps.append(dict(index=len(steps) + 1, title=e.get('remark', ''), status='passed' if e['status'] == 'done' else 'failed',
                              remark=e.get('remark', ''), ended=e.get('ts')))
    return steps

def final_result(events):
    for e in reversed(events):
        if e.get('type') == 'test_md_done':
            return dict(status=e.get('overall_status'), duration_s=e.get('duration_s'), kane_session=e.get('session_id'),
                        share_url=e.get('share_url'), summary=e.get('summary', ''))
    for e in reversed(events):
        if e.get('type') == 'run_end':
            return dict(status=e.get('status'), duration_s=e.get('duration'), summary=e.get('one_liner') or e.get('summary', ''),
                        reason=e.get('reason'), credits=e.get('credits_consumed', e.get('credits')), share_url=e.get('test_url'))
    for e in reversed(events):
        if e.get('type') == 'done':
            return dict(status=e.get('status', 'done'), summary=e.get('summary', ''))
    return None

def reconcile_plan(events):
    """`maintain reconcile --plan` (kane-cli 0.10): a `reconcile_plan` event with rows {kind, ref, why}.
    Older builds (and the fixture) emit `plan_saved` {path, proposals}."""
    for e in reversed(events):
        if e.get('type') == 'reconcile_plan':
            rows = [dict(kind=r.get('kind'), ref=r.get('ref'), why=r.get('why', '')) for r in e.get('rows') or []]
            counts = {}
            for r in rows:
                counts[str(r['kind']).lower()] = counts.get(str(r['kind']).lower(), 0) + 1
            parts = ', '.join(f'{n} {k}' for k, n in counts.items())
            return dict(rows=rows, counts=counts, archive=len(e.get('archive') or []),
                        plan=PurePosixPath(str(e.get('plan_path') or '')).name or None,
                        summary=f'{len(rows)} proposals' + (f' ({parts})' if parts else ''))
        if e.get('type') == 'plan_saved':
            n = e.get('proposals')
            return dict(rows=[], counts={}, archive=0, plan=PurePosixPath(str(e.get('path') or '')).name or None,
                        summary=f'{n} proposals' if n is not None else '')
    return None

def passed(result, exit_code):
    status = (result or {}).get('status')
    if isinstance(status, str):
        return status.lower() in ('passed', 'pass', 'success')
    return exit_code == 0

def unpack_evidence(pack, dest):
    """Copy screenshots and the result summary out of a sealed evidence pack."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shots, summary, failures = [], None, []
    with zipfile.ZipFile(pack) as z:
        for info in z.infolist():
            name = PurePosixPath(info.filename)
            if info.is_dir() or '..' in name.parts or name.is_absolute():
                continue
            if IMAGE.search(name.name):
                d = STEP_DIR.match(name.parent.name)
                m = d or STEP_NUM.search(str(name))
                target = dest / (f'step-{name.parent.name}-{name.name}' if d else name.name)
                if target.exists():
                    target = dest / f'{name.parent.name}-{name.name}'
                target.write_bytes(z.read(info))
                shots.append(dict(path=target, step=int(m.group(1)) if m else None, annotated='annot' in str(name).lower()))
            elif name.suffix == '.json' and ('summary' in name.name or 'result' in name.name):
                try:
                    summary = redact_obj(json.loads(z.read(info)))
                except ValueError:
                    pass
            elif name.suffix == '.json' and 'fail' in name.name:
                try:
                    failures.append(json.loads(z.read(info)))
                except ValueError:
                    pass
    shots.sort(key=lambda s: (s['step'] is None, s['step'] or 0, s['annotated']))
    return dict(screenshots=shots, summary=summary, failures=failures)

def trace_for_ac(*, ac, run_id, session_id, test_path, events, exit_code, evidence=None, fingerprint=None, created_at=None):
    result = final_result(events) or {}
    ok = passed(result, exit_code)
    steps = steps_from_stream(events)
    failing = next((s for s in steps if s['status'] == 'failed'), None)
    rationale = (failing or {}).get('remark') or result.get('summary') or ('passed' if ok else f'exit code {exit_code}')
    spans = [dict(id=f's{s["index"]}', name=s['title'] or f'Step {s["index"]}', status=s['status'], remark=s.get('remark', ''))
             for s in steps]
    trace = dict(id=f'{run_id}:{ac}', run_id=run_id, case_id=ac, model='kane-cli', session_id=session_id,
                 status='ok' if exit_code in (0, 1) else 'error', duration_ms=int((result.get('duration_s') or 0) * 1000),
                 test_path=test_path, spans=spans, result=result, fingerprint=fingerprint,
                 evidence=evidence, evaluations=[dict(metric='ac_pass', value=1.0 if ok else 0.0, scorer='kane-cli',
                                                      rationale=str(rationale)[:500])])
    if created_at:
        trace['created_at'] = created_at
    return trace
