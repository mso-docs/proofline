"""Run store. Same contract as Evalboard (traces, scores, settings) plus the
tables Proofline needs: sessions, runs, a durable event log for /api/stream,
screenshot artifacts, and a hashed artifact manifest.

Every row is stamped with created_at (UTC) and the session id that made it.
"""
import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .redact import redact_obj

SCHEMA = '''
CREATE TABLE IF NOT EXISTS traces(id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scores(id TEXT PRIMARY KEY, trace_id TEXT NOT NULL REFERENCES traces(id), metric TEXT NOT NULL,
  value REAL NOT NULL, rationale TEXT NOT NULL, scorer TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, label TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, session_id TEXT NOT NULL, kind TEXT NOT NULL, command TEXT NOT NULL,
  status TEXT NOT NULL, exit_code INTEGER, summary TEXT, created_at TEXT NOT NULL, finished_at TEXT, body TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, run_id TEXT, kind TEXT NOT NULL,
  body TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT, kind TEXT NOT NULL,
  case_id TEXT, step INTEGER, path TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS acs(id TEXT PRIMARY KEY, use_case TEXT, use_case_title TEXT, title TEXT NOT NULL,
  source TEXT, test_path TEXT, session_id TEXT, created_at TEXT NOT NULL);
'''

def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()

def _req(obj, key):
    v = obj.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f'{key} must be a nonempty string')
    return v

def validate_trace(trace):
    if not isinstance(trace, dict):
        raise ValueError('Each trace must be an object')
    trace = dict(trace)
    for key in ('id', 'run_id', 'case_id', 'model'):
        _req(trace, key)
    trace.setdefault('created_at', now())
    trace.setdefault('status', 'ok')
    if trace['status'] not in ('ok', 'error', 'unknown'):
        raise ValueError('status must be ok, error, or unknown')
    for f in ('duration_ms', 'cost_usd'):
        v = trace.setdefault(f, 0)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            raise ValueError(f'{f} must be a finite nonnegative number')
    for f in ('messages', 'spans'):
        trace.setdefault(f, [])
        if not isinstance(trace[f], list):
            raise ValueError(f'{f} must be an array')
    for ev in trace.get('evaluations', []):
        for k in ('metric', 'scorer', 'rationale'):
            _req(ev, k)
        v = ev.get('value')
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
            raise ValueError('evaluation value must be in [0, 1]')
    return trace

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = str(self.root / 'proofline.sqlite3')
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA journal_mode=WAL')
            with db:
                yield db
        finally:
            db.close()

    # sessions and runs
    def new_session(self, label=None):
        sid = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:6]
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (sid, label, now()))
        self.emit(sid, None, 'session', {'label': label})
        return sid

    def latest_session(self):
        with self.connect() as db:
            row = db.execute('SELECT id FROM sessions ORDER BY rowid DESC LIMIT 1').fetchone()
        return row['id'] if row else None

    def session_dir(self, session_id):
        d = self.root / 'sessions' / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def start_run(self, session_id, kind, command, body=None):
        rid = f'{kind}-{uuid4().hex[:8]}'
        with self.connect() as db:
            db.execute('INSERT INTO runs(id,session_id,kind,command,status,created_at,body) VALUES (?,?,?,?,?,?,?)',
                       (rid, session_id, kind, redact_obj(command), 'running', now(), json.dumps(redact_obj(body or {}))))
        self.emit(session_id, rid, 'run_start', {'kind': kind, 'command': command})
        return rid

    def finish_run(self, run_id, status, exit_code, summary='', body=None):
        with self.connect() as db:
            row = db.execute('SELECT session_id, body FROM runs WHERE id=?', (run_id,)).fetchone()
            merged = {**json.loads(row['body']), **(body or {})}
            db.execute('UPDATE runs SET status=?, exit_code=?, summary=?, finished_at=?, body=? WHERE id=?',
                       (status, exit_code, redact_obj(summary), now(), json.dumps(redact_obj(merged)), run_id))
        self.emit(row['session_id'], run_id, 'run_end', {'status': status, 'exit_code': exit_code, 'summary': summary})

    def run(self, run_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise ValueError('Unknown run_id')
        r = dict(row)
        r['body'] = json.loads(r['body'])
        return r

    def runs(self, session_id=None):
        q, a = 'SELECT * FROM runs', ()
        if session_id:
            q, a = q + ' WHERE session_id=?', (session_id,)
        with self.connect() as db:
            rows = [dict(r) for r in db.execute(q + ' ORDER BY rowid', a)]
        for r in rows:
            r['body'] = json.loads(r['body'])
        return rows

    # events (durable, so the MCP process and the dashboard process share one stream)
    def emit(self, session_id, run_id, kind, body):
        with self.connect() as db:
            cur = db.execute('INSERT INTO events(session_id,run_id,kind,body,created_at) VALUES (?,?,?,?,?)',
                             (session_id, run_id, kind, json.dumps(redact_obj(body)), now()))
            return cur.lastrowid

    def last_seq(self):
        with self.connect() as db:
            row = db.execute('SELECT MAX(seq) AS m FROM events').fetchone()
        return row['m'] or 0

    def events_since(self, seq=0, limit=500):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?', (seq, limit)).fetchall()
        return [{**dict(r), 'body': json.loads(r['body'])} for r in rows]

    # acceptance criteria
    def upsert_acs(self, session_id, acs):
        with self.connect() as db:
            for a in acs:
                db.execute('''INSERT INTO acs VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    use_case=excluded.use_case, use_case_title=excluded.use_case_title, title=excluded.title,
                    source=excluded.source, test_path=COALESCE(excluded.test_path, acs.test_path)''',
                           (a['id'], a.get('use_case'), a.get('use_case_title'), a['title'], a.get('source'),
                            a.get('test_path'), session_id, now()))
        return len(acs)

    def acs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM acs ORDER BY rowid')]

    # traces and scores (Evalboard contract)
    def ingest(self, traces):
        if not isinstance(traces, list) or not traces:
            raise ValueError('traces must be a nonempty array')
        validated = [validate_trace(redact_obj(t)) for t in traces]
        with self.connect() as db:
            for t in validated:
                if db.execute('SELECT 1 FROM traces WHERE id=?', (t['id'],)).fetchone():
                    continue
                db.execute('INSERT INTO traces VALUES (?,?)', (t['id'], json.dumps(t)))
                for ev in t.get('evaluations', []):
                    db.execute('INSERT INTO scores VALUES (?,?,?,?,?,?,?)', (str(uuid4()), t['id'], ev['metric'],
                               ev['value'], ev['rationale'], ev['scorer'], now()))
        return len(validated)

    def traces(self):
        with self.connect() as db:
            return [json.loads(r['body']) for r in db.execute('SELECT body FROM traces ORDER BY rowid')]

    def scores(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM scores ORDER BY rowid')]

    def compare_runs(self, baseline, candidate, metric='ac_pass'):
        latest = {s['trace_id']: s['value'] for s in self.scores() if s['metric'] == metric}
        runs = {}
        for t in self.traces():
            if t['run_id'] in (baseline, candidate):
                runs.setdefault(t['run_id'], {})[t['case_id']] = latest.get(t['id'])
        a, b = runs.get(baseline, {}), runs.get(candidate, {})
        paired = [dict(case_id=k, baseline=a[k], candidate=b[k], delta=b[k] - a[k])
                  for k in sorted(a.keys() & b.keys()) if a[k] is not None and b[k] is not None]
        return dict(metric=metric, baseline=baseline, candidate=candidate, paired=paired,
                    regressions=[p['case_id'] for p in paired if p['delta'] < 0],
                    fixes=[p['case_id'] for p in paired if p['delta'] > 0],
                    mean_delta=sum(p['delta'] for p in paired) / len(paired) if paired else None)

    def save_setting(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT body FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row['body']) if row else default

    # artifacts and manifest
    def add_artifact(self, session_id, path, kind='file', run_id=None, case_id=None, step=None):
        p = Path(path).resolve()
        rel = p.relative_to(self.root.resolve()).as_posix()
        aid = hashlib.sha1(rel.encode()).hexdigest()[:16]
        digest = sha256_file(p)
        with self.connect() as db:
            db.execute('''INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                sha256=excluded.sha256, bytes=excluded.bytes''',
                       (aid, session_id, run_id, kind, case_id, step, rel, digest, p.stat().st_size, now()))
        if kind == 'screenshot':
            self.emit(session_id, run_id, 'screenshot', {'case_id': case_id, 'step': step, 'path': rel})
        return dict(id=aid, path=rel, sha256=digest)

    def artifacts(self, kind=None, case_id=None, run_id=None):
        q, a = 'SELECT * FROM artifacts WHERE 1=1', []
        for col, val in (('kind', kind), ('case_id', case_id), ('run_id', run_id)):
            if val is not None:
                q += f' AND {col}=?'
                a.append(val)
        with self.connect() as db:
            return [dict(r) for r in db.execute(q + ' ORDER BY rowid', a)]

    def manifest(self, verify=True):
        items = []
        for a in self.artifacts():
            entry = dict(path=a['path'], sha256=a['sha256'], bytes=a['bytes'], created_at=a['created_at'],
                         session_id=a['session_id'], run_id=a['run_id'], kind=a['kind'])
            if verify:
                p = self.root / a['path']
                entry['verified'] = p.exists() and sha256_file(p) == a['sha256']
            items.append(entry)
        with self.connect() as db:
            sessions = [dict(r) for r in db.execute('SELECT * FROM sessions ORDER BY rowid')]
        body = json.dumps(items, sort_keys=True).encode()
        return dict(generated_at=now(), tool='proofline', sessions=sessions, artifact_count=len(items),
                    manifest_sha256=hashlib.sha256(body).hexdigest(), artifacts=items)

    # derived views
    def verdicts(self):
        """Latest verdict per AC, the full sequence of verdicts, and flaky detection."""
        traces = {t['id']: t for t in self.traces()}
        seqs = {}
        for s in self.scores():
            if s['metric'] != 'ac_pass' or s['trace_id'] not in traces:
                continue
            t = traces[s['trace_id']]
            seqs.setdefault(t['case_id'], []).append(dict(value=s['value'], trace_id=t['id'], run_id=t['run_id'], suite=t.get('suite'),
                                                         at=t.get('created_at'), fingerprint=t.get('fingerprint'),
                                                         rationale=s['rationale']))
        out = {}
        for ac in self.acs():
            seq = seqs.get(ac['id'], [])
            out[ac['id']] = dict(ac, verdict=('pass' if seq[-1]['value'] >= 1 else 'fail') if seq else 'idle',
                                 history=seq, flips=flips(seq), flaky=is_flaky(seq))
        for case_id, seq in seqs.items():
            out.setdefault(case_id, dict(id=case_id, title=case_id, use_case=None, verdict='pass' if seq[-1]['value'] >= 1 else 'fail',
                                         history=seq, flips=flips(seq), flaky=is_flaky(seq)))
        return out

def flips(seq):
    vals = [s['value'] >= 1 for s in seq]
    return sum(1 for a, b in zip(vals, vals[1:]) if a != b)

def is_flaky(seq):
    """Flaky = the verdict changed at least twice while the test and source fingerprint stayed the same."""
    groups = {}
    for s in seq:
        groups.setdefault(s.get('fingerprint'), []).append(s)
    return any(flips(g) >= 2 for g in groups.values())
