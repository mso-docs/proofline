"""Kane CLI runner. Every call shells out to kane-cli, streams its NDJSON into the
run store as events, and keeps the raw (redacted) output as hashed artifacts.

Credentials: never in code or logs. kane-cli's own login profile is used by
default (`kane-cli login`). If KANE_USERNAME / KANE_ACCESS_KEY (or the LT_*
names) are set in the environment, they are passed through for the commands
that accept basic auth, and scrubbed from everything Proofline stores.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from .redact import redact

AUTH_COMMANDS = {('run',), ('testmd', 'run'), ('testrun', 'run')}
EVIDENCE_HINT = re.compile(r'kane-cli evidence serve\s+`?([^`\s]+)')

def kane_bin():
    return shlex.split(os.environ.get('PROOFLINE_KANE_BIN', 'kane-cli'))

def installed():
    exe = kane_bin()[0]
    path = shutil.which(exe) or (exe if Path(exe).exists() else None)
    if not path:
        return dict(installed=False, hint='npm install -g @testmuai/kane-cli && kane-cli login')
    try:
        out = subprocess.run(kane_bin() + ['--version'], capture_output=True, text=True, timeout=30)
        return dict(installed=True, version=out.stdout.strip().splitlines()[-1] if out.stdout.strip() else None,
                    fixture=bool(os.environ.get('PROOFLINE_KANE_BIN')))
    except (OSError, subprocess.SubprocessError) as e:
        return dict(installed=False, error=str(e))

def auth_args(args):
    user = os.environ.get('KANE_USERNAME') or os.environ.get('LT_USERNAME')
    key = os.environ.get('KANE_ACCESS_KEY') or os.environ.get('LT_ACCESS_KEY')
    if user and key and (tuple(args[:1]) in AUTH_COMMANDS or tuple(args[:2]) in AUTH_COMMANDS):
        return ['--username', user, '--access-key', key]
    return []

def parse_lines(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out

class Kane:
    def __init__(self, store, workdir):
        self.store = store
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)

    def call(self, session_id, kind, args, timeout=1800, on_event=None):
        """Run one kane-cli command. Returns dict(run_id, exit_code, events, stderr, evidence)."""
        argv = kane_bin() + list(args) + auth_args(list(args))
        shown = 'kane-cli ' + ' '.join(shlex.quote(a) for a in args)
        run_id = self.store.start_run(session_id, kind, shown)
        rdir = self.store.session_dir(session_id) / 'runs' / run_id
        rdir.mkdir(parents=True, exist_ok=True)
        events, started = [], time.time()
        env = {**os.environ, 'CI': os.environ.get('CI', '1'), 'NO_COLOR': '1', 'KANE_CLI_USER_AGENT': os.environ.get('KANE_CLI_USER_AGENT') or 'proofline'}
        with open(rdir / 'stdout.ndjson', 'w') as out, open(rdir / 'stderr.log', 'w') as err:
            try:
                proc = subprocess.Popen(argv, cwd=self.workdir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=err, text=True, env=env, bufsize=1)
            except OSError as e:
                err.write(redact(str(e)))
                self.store.finish_run(run_id, 'error', 127, f'kane-cli could not start: {e}')
                return dict(run_id=run_id, exit_code=127, events=[], stderr=str(e), evidence=None)
            for line in proc.stdout:
                clean = redact(line)
                out.write(clean)
                for ev in parse_lines(clean):
                    events.append(ev)
                    self.store.emit(session_id, run_id, 'kane', ev)
                    if on_event:
                        on_event(ev)
                if time.time() - started > timeout:
                    proc.kill()
                    break
            code = proc.wait()
        stderr = redact((rdir / 'stderr.log').read_text(errors='replace'))
        (rdir / 'stderr.log').write_text(stderr)
        for line in stderr.splitlines()[-40:]:
            if line.strip():
                self.store.emit(session_id, run_id, 'log', {'line': line[:400]})
        for name in ('stdout.ndjson', 'stderr.log'):
            self.store.add_artifact(session_id, rdir / name, kind='log', run_id=run_id)
        if kind != 'testmd-run':
            # testmd runs get their verdict from run_suite; every other command is closed here
            done = next((e for e in reversed(events) if e.get('type') == 'done'), None)
            summary = (done or {}).get('status') or (f'exit code {code}' if code else 'complete')
            self.store.finish_run(run_id, 'done' if code == 0 else 'error', code, summary)
        hint = EVIDENCE_HINT.search(stderr)
        evidence = self._resolve(hint.group(1)) if hint else None
        return dict(run_id=run_id, exit_code=code, events=events, stderr=stderr, evidence=evidence,
                    duration_s=round(time.time() - started, 2), run_dir=rdir)

    def _resolve(self, p):
        p = Path(os.path.expanduser(p))
        return p if p.is_absolute() else self.workdir / p

    def newest_evidence(self, since):
        d = self.workdir / '.testmuai' / 'evidence'
        packs = [p for p in d.glob('*.evidence')] if d.exists() else []
        packs = [p for p in packs if p.stat().st_mtime >= since - 1]
        return max(packs, key=lambda p: p.stat().st_mtime) if packs else None
