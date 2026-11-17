"""Proofline MCP server (stdio, JSON-RPC 2.0, newline-delimited).

Lets any MCP client (Cursor, Claude Code, Codex) drive Kane CLI through
Proofline. Each tool shells out to kane-cli, records outputs and evidence in
the run store with a creation time and session id, and streams progress to the
dashboard through the shared event log.
"""
import json
import sys
import webbrowser

from . import __version__
from .export_static import export_static
from .service import Proofline

VERSIONS = ['2025-06-18', '2025-03-26', '2024-11-05']

def tool(name, description, props=None, required=()):
    return dict(name=name, description=description,
                inputSchema=dict(type='object', properties=props or {}, required=list(required), additionalProperties=False))

S = lambda d: {'type': 'string', 'description': d}
TOOLS = [
    tool('proofline_status', 'Is kane-cli installed, which session is current, and where each pipeline stage stands.'),
    tool('ingest_prd', 'Start a session: add a PRD (Markdown) as a Kane context source (kane-cli context ingest) and read its acceptance criteria.',
         {'path': S('Path to the PRD file'), 'label': S('Optional session label')}, ['path']),
    tool('extract_context', 'Find the use-cases in the ingested sources (kane-cli context extract --mode agent), then list them.',
         {'session_id': S('Session id; defaults to the latest')}),
    tool('list_context', 'List sources, use-cases and designed items (kane-cli context list --json).', {'session_id': S('Session id')}),
    tool('design_tests', 'Design acceptance criteria, scenarios and *_test.md tests for one use-case (kane-cli design tests).',
         {'use_case': S('Use-case id, e.g. uc-1'), 'max_scenarios': {'type': 'integer', 'minimum': 1, 'maximum': 50},
          'session_id': S('Session id')}, ['use_case']),
    tool('run_suite', 'Run one *_test.md or every test in the workspace (kane-cli testmd run --agent), ingest verdicts and evidence packs.',
         {'path': S('One test file relative to the workspace; omit for all'), 'url': S('Start URL override'),
          'headless': {'type': 'boolean'}, 'session_id': S('Session id')}),
    tool('maintain_drift', 'Diff a new PRD version against the last one, flag stale tests, and run kane-cli maintain reconcile (plan by default).',
         {'new_prd': S('Path to the new PRD version'), 'source_id': S('Kane source id from list_context'),
          'apply': {'type': 'boolean', 'description': 'Apply the saved plan instead of only planning'}, 'session_id': S('Session id')}, ['new_prd']),
    tool('get_run', 'Status, command, artifacts and trace for one run.', {'run_id': S('Run id')}, ['run_id']),
    tool('get_evidence', 'Latest evidence for an AC or a run: verdict, steps, screenshots, evidence pack.',
         {'ac': S('AC id, e.g. AC-2.3'), 'run_id': S('Run id')}),
    tool('list_acs', 'Every acceptance criterion with its latest verdict, run count and flaky flag.'),
    tool('compare_runs', 'Paired AC verdict deltas between two runs.', {'baseline': S('Run id'), 'candidate': S('Run id')}, ['baseline', 'candidate']),
    tool('export_manifest', 'Write the artifact manifest (path, sha256, created_at, session) and verify every hash.', {'out': S('Output path')}),
    tool('export_dashboard', 'Export the dashboard as a static folder with its snapshot, screenshots and manifest.', {'out': S('Output folder')}, ['out']),
    tool('open_dashboard', 'Return the dashboard URL and optionally open it in a browser.',
         {'port': {'type': 'integer'}, 'launch': {'type': 'boolean'}}),
]

class Server:
    def __init__(self, pl=None):
        self.pl = pl or Proofline()
        self.initialized = False

    def call(self, name, a):
        pl = self.pl
        if name == 'proofline_status': return pl.status()
        if name == 'ingest_prd': return pl.ingest_prd(a['path'], label=a.get('label'))
        if name == 'extract_context': return pl.extract_context(a.get('session_id'))
        if name == 'list_context': return pl.list_context(a.get('session_id'))
        if name == 'design_tests': return pl.design_tests(a['use_case'], a.get('max_scenarios'), a.get('session_id'))
        if name == 'run_suite': return pl.run_suite(a.get('path'), a.get('url'), a.get('headless', True), a.get('session_id'))
        if name == 'maintain_drift': return pl.maintain(a['new_prd'], a.get('source_id'), a.get('apply', False), a.get('session_id'))
        if name == 'get_run': return pl.run_status(a['run_id'])
        if name == 'get_evidence': return pl.evidence(a.get('ac'), a.get('run_id'))
        if name == 'list_acs': return pl.list_acs()
        if name == 'compare_runs': return pl.store.compare_runs(a['baseline'], a['candidate'])
        if name == 'export_manifest': return pl.export_manifest(a.get('out'))
        if name == 'export_dashboard': return export_static(pl, a['out'])
        if name == 'open_dashboard':
            url = f'http://127.0.0.1:{int(a.get("port", 8777))}/'
            if a.get('launch'):
                webbrowser.open(url)
            return dict(url=url, hint='Start it with: python3 -m proofline serve')
        raise ValueError(f'Unknown tool: {name}')

    def handle(self, msg):
        if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0' or not isinstance(msg.get('method'), str):
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}}
        if 'id' not in msg:
            return None
        reply, method, params = {'jsonrpc': '2.0', 'id': msg['id']}, msg['method'], msg.get('params') or {}
        if method == 'initialize':
            self.initialized = True
            v = params.get('protocolVersion')
            return {**reply, 'result': dict(protocolVersion=v if v in VERSIONS else VERSIONS[0], capabilities={'tools': {}},
                    serverInfo={'name': 'proofline', 'version': __version__},
                    instructions='Drive Kane CLI through Proofline: ingest_prd -> extract_context -> design_tests -> run_suite -> '
                                 'maintain_drift. Every artifact is hashed into the manifest. Never invent verdicts.')}
        if method == 'ping':
            return {**reply, 'result': {}}
        if not self.initialized:
            return {**reply, 'error': {'code': -32002, 'message': 'Initialize the server first'}}
        if method == 'tools/list':
            return {**reply, 'result': {'tools': TOOLS}}
        if method == 'tools/call':
            try:
                value = self.call(params.get('name'), params.get('arguments') or {})
                return {**reply, 'result': {'content': [{'type': 'text', 'text': json.dumps(value, default=str)}], 'isError': False}}
            except (ValueError, TypeError, KeyError, OSError) as e:
                return {**reply, 'result': {'content': [{'type': 'text', 'text': str(e)}], 'isError': True}}
        return {**reply, 'error': {'code': -32601, 'message': f'Unknown method: {method}'}}

def main(stdin=sys.stdin, stdout=sys.stdout):
    server = Server()
    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
        else:
            out = server.handle(msg)
        if out is not None:
            stdout.write(json.dumps(out) + '\n')
            stdout.flush()

if __name__ == '__main__':
    main()
