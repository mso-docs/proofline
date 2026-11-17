#!/usr/bin/env python3
"""FIXTURE ONLY: a stand-in for kane-cli that speaks its documented agent-mode
output (NDJSON stream v1, context list --json, sealed .evidence zip packs).
Used by the tests and `python3 -m proofline demo` so everything runs offline.
It never contacts TestMu AI and its verdicts are scripted, not real.
Scripting: a test containing `fixture: fail` fails; `fixture: flaky` alternates.
"""
import json
import re
import struct
import sys
import time
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

def ts():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def out(**e):
    e.setdefault('v', 1); e.setdefault('ts', ts())
    print(json.dumps(e), flush=True)

def png(w, h, rgb, bar):
    rows = b''
    for y in range(h):
        row = bytearray()
        for x in range(w):
            if 14 <= y <= 26:
                c = (40, 44, 52)
            elif 40 <= y <= 52 and 20 <= x <= 20 + bar:
                c = rgb
            elif 70 <= y <= h - 20 and 20 <= x <= w - 20:
                c = (236, 238, 243) if (y // 14) % 2 else (246, 247, 250)
            else:
                c = (250, 250, 252)
            row += bytes(c)
        rows += b'\x00' + bytes(row)
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows, 6)) + chunk(b'IEND', b'')

def prd_acs():
    acs = []
    for p in sorted(Path('.').glob('*.md')):
        if p.name.endswith('_test.md'):
            continue
        uc = None
        for line in p.read_text().splitlines():
            m = re.match(r'#+\s*(UC-\d+)\s*(.*)', line)
            if m: uc = (m.group(1), m.group(2)); continue
            m = re.match(r'#+\s*(AC-[\d.]+)\s*(.*)', line)
            if m and uc: acs.append((uc[0], uc[1], m.group(1), m.group(2)))
    return acs

def main(a):
    if a[:1] in (['--version'], ['-V']):
        print('0.10.5-fixture'); return 0
    if a[:2] == ['context', 'ingest']:
        Path('.context').mkdir(exist_ok=True)
        print(f'created  {Path(a[2]).stem}  source sha256:fixture'); print('landed 1 source(s)'); return 0
    if a[:2] == ['context', 'extract']:
        out(type='stream_start', cli_version='0.10.5-fixture', surface='context', pid=0)
        ucs = sorted({(u, t) for u, t, _, _ in prd_acs()})
        for u, t in ucs:
            out(type='proposal', kind='usecase', id=u.lower(), title=t)
        out(type='done', status='ok', summary=f'{len(ucs)} use-cases found'); return 0
    if a[:2] == ['context', 'list']:
        seen = set()
        for p in Path('.').glob('*.md'):
            if not p.name.endswith('_test.md'):
                print(json.dumps(dict(id=p.stem, cid='sha256:fixture', label='source', title=p.stem, trust='-', fresh='fresh')))
        for u, t, _, _ in prd_acs():
            if u not in seen:
                seen.add(u); print(json.dumps(dict(id=u.lower(), cid='sha256:fixture', label='usecase', title=t, trust='auto', fresh='fresh')))
        return 0
    if a[:2] == ['design', 'tests']:
        uc = a[a.index('--use-case') + 1].upper()
        out(type='stream_start', cli_version='0.10.5-fixture', surface='design', pid=0)
        Path('tests').mkdir(exist_ok=True)
        n = 0
        for u, _, ac, title in prd_acs():
            if u != uc: continue
            mode = 'fail' if ac in ('AC-2.3', 'AC-4.2') else 'flaky' if ac in ('AC-3.3',) else 'pass'
            f = Path('tests') / f'{ac.lower().replace("-", "_").replace(".", "_")}_test.md'
            f.write_text(f'---\nac: {ac}\nurl: https://demo.playwright.dev/todomvc\nfixture: {mode}\n---\n# {ac} {title}\n\n'
                         f'## Open the app\n## Arrange the todos\n## {title}\n## Verify the result\n')
            out(type='test_written', path=f.as_posix(), ac=ac); n += 1
        out(type='done', status='ok', summary=f'{n} tests designed for {uc}'); return 0
    if a[:2] == ['testmd', 'run']:
        path = Path(a[2]); text = path.read_text()
        mode = re.search(r'fixture:\s*(\w+)', text).group(1) if 'fixture:' in text else 'pass'
        counter = Path('.testmuai') / 'fixture-counts.json'; counter.parent.mkdir(exist_ok=True)
        counts = json.loads(counter.read_text()) if counter.exists() else {}
        counts[path.name] = counts.get(path.name, 0) + 1; counter.write_text(json.dumps(counts))
        ok = mode == 'pass' or (mode == 'flaky' and counts[path.name] % 2 == 1)
        steps = re.findall(r'^## (.+)$', text, re.M)
        out(type='stream_start', cli_version='0.10.5-fixture', surface='testmd', pid=0)
        ev = Path('.testmuai/evidence'); ev.mkdir(parents=True, exist_ok=True)
        pack = ev / f'{path.stem}-{int(time.time()*1000)}.evidence'
        with zipfile.ZipFile(pack, 'w') as z:
            for i, s in enumerate(steps, 1):
                failed = not ok and i == len(steps)
                out(type='test_md_step_start', index=i, title=s)
                out(type='run_start'); out(type='step_start', remark=s)
                time.sleep(0.05)
                remark = f'assert failed: {s.lower()} (fixture)' if failed else f'done: {s.lower()}'
                out(type='step_end', status='failed' if failed else 'passed', remark=remark)
                out(type='run_end', status='failed' if failed else 'passed', duration=0.4)
                out(type='test_md_step_end', index=i, status='failed' if failed else 'passed', remark=remark)
                z.writestr(f'steps/step-{i}/screenshot.png', png(320, 200, (255, 90, 95) if failed else (61, 220, 132), 40 + 60 * i))
                if failed:
                    z.writestr(f'steps/step-{i}/failure.json', json.dumps(dict(step=i, remark=remark)))
            z.writestr('result-summary.json', json.dumps(dict(status='passed' if ok else 'failed', steps=len(steps), fixture=True)))
        out(type='test_md_done', overall_status='passed' if ok else 'failed', duration_s=0.4 * len(steps), session_id='fixture-session')
        print(f'evidence: view locally with `kane-cli evidence serve {pack.as_posix()}`', file=sys.stderr)
        return 0 if ok else 1
    if a[:2] == ['maintain', 'reconcile']:
        out(type='stream_start', cli_version='0.10.5-fixture', surface='maintain', pid=0)
        out(type='plan_saved', path='.context/plans/fixture-plan.json', proposals=3)
        out(type='done', status='ok', summary='3 proposals waiting for review'); return 0
    print(f'fixture kane-cli: unsupported command {a[:2]}', file=sys.stderr); return 2

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
