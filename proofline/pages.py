"""Redacted static GitHub Pages demo of a live Proofline run store.

`python3 -m proofline pages docs/demo --root runs/live` copies the run store to a
temporary directory, closes runs that older versions left open, and writes the
dashboard with a frozen snapshot, the step screenshots, the PRDs, tests and drift
report, and the hashed manifest. Every string is scrubbed before it is written:

* account values Kane records in each evidence pack (user name, email, share link,
  org, project, folder and test-case ids) are read locally at build
  time and replaced with placeholders, so they never appear in code or output;
* share links, TestMu test-manager and artifact-store URLs, share and org ids,
  emails, tokens, home paths, this machine's host name and login name.

Raw logs and sealed evidence packs are never copied; the manifest still lists
them with their sha256 so the proof of work is complete. Run
`python3 scripts/scan_pages.py docs` afterwards; it must pass before publishing.
"""
import getpass
import hashlib
import json
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .redact import redact_obj
from .server import WEB
from .store import now, sha256_file

EXTERNAL_KEYS = {
    'user_email': '<EMAIL>', 'user_name': '<KANE_USER>', 'sharable_link': '<KANE_SHARE_LINK>',
    'org_id': '<ORG_ID>', 'project_id': '<PROJECT_ID>',
    'folder_id': '<FOLDER_ID>', 'testcase_id': '<TESTCASE_ID>',
}
URL_END = r'[^\s"\'<>)\]}\\]*'
PATTERNS = [
    (re.compile(r'https?://test-manager\.lambdatest\.com/' + URL_END), '<KANE_TEST_MANAGER_URL>'),
    (re.compile(r'https?://[A-Za-z0-9-]+\.blob\.core\.windows\.net' + URL_END), '<KANE_ARTIFACT_URL>'),
    (re.compile(r'https?://' + URL_END + r'(?:share|sharable)' + URL_END, re.I), '<KANE_SHARE_LINK>'),
    (re.compile(r'(?i)(\\?"?(?:share_id|org_id|project_id|folder_id|testcase_id)\\?"?\s*[:=]\s*\\?"?)[A-Za-z0-9_-]{4,}'), r'\1<REDACTED-ID>'),
    (re.compile(r'(?i)(\\?"?(?:user_name|user_email|username|email)\\?"?\s*[:=]\s*\\?"?)[^"\\\n,}]{2,}'), r'\1<REDACTED>'),
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'), '<EMAIL>'),
    (re.compile(r'\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net\b'), '<HOST>'),
]
PUBLISH_KINDS = ('screenshot', 'prd', 'testmd', 'drift')
TEXT_SUFFIXES = ('.md', '.json', '.ndjson', '.log', '.yaml', '.yml', '.txt', '.html')

def evidence_values(root):
    """Account values Kane writes into result.yaml inside each evidence pack, read locally."""
    found = {}
    for pack in Path(root).rglob('*.evidence'):
        try:
            z = zipfile.ZipFile(pack)
        except (OSError, zipfile.BadZipFile):
            continue
        for name in z.namelist():
            if not name.endswith('result.yaml'):
                continue
            for line in z.read(name).decode(errors='replace').splitlines():
                key, _, val = line.strip().partition(':')
                val = val.strip().strip('"\'')
                if key in EXTERNAL_KEYS and len(val) >= 3:
                    found[val] = EXTERNAL_KEYS[key]
    return found

def local_values(root=None):
    """Values that must never be published, longest first: evidence account values, git email,
    login name, host names. Read at build/scan time; never stored."""
    vals = dict(evidence_values(root)) if root else {}
    try:
        email = subprocess.run(['git', 'config', 'user.email'], capture_output=True, text=True, timeout=10).stdout.strip()
        if email:
            vals[email] = '<EMAIL>'
    except (OSError, subprocess.SubprocessError):
        pass
    host = socket.gethostname()
    for h in {host, host.split('.')[0]}:
        if len(h) >= 4:
            vals[h] = '<HOST>'
    user = getpass.getuser()
    if len(user) >= 4:
        vals['/' + user + '/'] = '/<USER>/'
    return dict(sorted(vals.items(), key=lambda kv: -len(kv[0])))

class Scrubber:
    def __init__(self, values):
        self.values = values

    def text(self, s):
        if not isinstance(s, str):
            return s
        for val, ph in self.values.items():
            if val in s:
                s = s.replace(val, ph)
            if ph in ('<KANE_USER>', '<EMAIL>') and val.lower() in s.lower():
                s = re.sub(re.escape(val), ph, s, flags=re.I)
        for pat, repl in PATTERNS:
            s = pat.sub(repl, s)
        return redact_obj(s)

    def obj(self, o):
        if isinstance(o, str):
            return self.text(o)
        if isinstance(o, list):
            return [self.obj(x) for x in o]
        if isinstance(o, dict):
            return {k: self.obj(v) for k, v in o.items()}
        return o

def _copy_store(src, dst):
    """Copy the database (via the sqlite backup API) and session files; never the Kane workspace."""
    dst.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(src / 'proofline.sqlite3') as a, sqlite3.connect(dst / 'proofline.sqlite3') as b:
        a.backup(b)
    if (src / 'sessions').exists():
        shutil.copytree(src / 'sessions', dst / 'sessions')

def close_open_runs(db_path):
    """Runs recorded before kane.call closed non-test commands stay 'running'. Close them from the
    `done` event kane-cli emitted, or mark them 'unknown' when there is none."""
    db = sqlite3.connect(db_path)
    closed = 0
    for rid, kind in db.execute("SELECT id, kind FROM runs WHERE status='running'").fetchall():
        done = None
        for body, at in db.execute("SELECT body, created_at FROM events WHERE run_id=? ORDER BY seq", (rid,)):
            try:
                b = json.loads(body)
            except ValueError:
                continue
            # ingest and list print a result line or items, with no closing `done` event
            if b.get('type') == 'done' or kind in ('context-ingest', 'context-list'):
                done = ({} if b.get('type') != 'done' else b, at)
        if done:
            b, at = done
            code = b.get('exit_code', 0)
            db.execute('UPDATE runs SET status=?, exit_code=?, summary=?, finished_at=? WHERE id=?',
                       ('done' if code == 0 else 'error', code, b.get('status') or 'complete', at, rid))
        else:
            db.execute("UPDATE runs SET status='unknown' WHERE id=?", (rid,))
        closed += 1
    db.commit()
    db.close()
    return closed

def build_pages(root='runs/live', out='docs/demo', kane_version=None, target=None, extra_values=None):
    from .service import Proofline
    root, out = Path(root), Path(out)
    if not (root / 'proofline.sqlite3').exists():
        raise ValueError(f'No run store at {root.name}')
    scrub = Scrubber({**local_values(root), **(extra_values or {})})
    tmp = Path(tempfile.mkdtemp(prefix='proofline-pages-'))
    try:
        store = tmp / 'store'
        _copy_store(root, store)
        closed = close_open_runs(store / 'proofline.sqlite3')
        pl = Proofline(store, workdir=root / 'workspace' if (root / 'workspace').exists() else tmp / 'workspace')
        manifest = pl.store.manifest(verify=True)
        if kane_version is None:
            from .kane import installed
            kane_version = (installed() or {}).get('version')
        snap = pl.snapshot()
        snap.update(static=True, redacted=True, exported_at=now())
        snap['status'] = dict(snap['status'], root='live', kane=dict(installed=True, version=kane_version, fixture=False))
        snap['target'] = target or snap.get('target') or dict(name='TodoMVC (public Playwright demo)', url='https://demo.playwright.dev/todomvc', fixture=False)
        snap['traces'] = {t['id']: dict(spans=t.get('spans') or []) for t in pl.store.traces()}
        acs = pl.list_acs()
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        published = {}
        for a in pl.store.artifacts():
            if a['kind'] not in PUBLISH_KINDS:
                continue
            src = store / a['path']
            if not src.exists():
                continue
            dest = out / 'artifacts' / a['path']
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix.lower() in TEXT_SUFFIXES:
                raw = src.read_text(errors='replace')
                clean = scrub.text(raw)
                dest.write_text(clean)
                published[a['path']] = clean != raw
            else:
                shutil.copy2(src, dest)
                published[a['path']] = False
        for e in manifest['artifacts']:
            e['published'] = e['path'] in published
            if e['published']:
                e['published_redacted'] = published[e['path']]
                e['published_sha256'] = sha256_file(out / 'artifacts' / e['path'])
        manifest['note'] = ('sha256 and created_at are recorded at capture time by the local run store. Screenshots are published '
                            'byte-for-byte (published_sha256 == sha256). Text artifacts are published redacted, so their '
                            'published_sha256 differs. Raw kane-cli logs and sealed evidence packs stay private; their hashes are listed.')
        manifest = scrub.obj(manifest)
        snap = scrub.obj(snap)
        acs = scrub.obj(acs)
        for name in ('style.css', 'app.js'):
            shutil.copy2(WEB / name, out / name)
        (out / 'snapshot.json').write_text(json.dumps(snap, indent=1))
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        (out / 'acs.json').write_text(json.dumps(acs, indent=2))
        html = (WEB / 'index.html').read_text().replace('/static/', '')
        html = html.replace('<script src="app.js"></script>',
                            '<script>window.PROOFLINE_SNAPSHOT=' + json.dumps(snap).replace('</', '<\\/') + '</script><script src="app.js"></script>')
        (out / 'index.html').write_text(html)
        files = sorted(p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file())
        return dict(out=out.as_posix(), files=len(files), runs_closed=closed, artifacts=manifest['artifact_count'],
                    published=len(published), manifest_sha256=manifest['manifest_sha256'],
                    all_verified=all(e.get('verified') for e in manifest['artifacts']))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
