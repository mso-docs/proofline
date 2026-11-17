"""Loopback dashboard server (stdlib only). /api/stream is Server-Sent Events fed
from the store's durable event log, so runs started by the MCP server in another
process show up live."""
import argparse
import errno
import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .service import Proofline

WEB = Path(__file__).resolve().parent.parent / 'web'

def handler(pl):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'Proofline'

        def log_message(self, *a):
            pass

        def respond(self, code, body, ctype='application/json'):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def file(self, base, rel):
            base = base.resolve()
            target = (base / rel).resolve()
            if not target.is_relative_to(base) or not target.is_file():
                return self.respond(404, {'error': 'Not found'})
            self.respond(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'application/octet-stream')

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            try:
                if url.path in ('/', '/index.html'):
                    return self.file(WEB, 'index.html')
                if url.path.startswith('/static/'):
                    return self.file(WEB, url.path[len('/static/'):])
                if url.path.startswith('/artifacts/'):
                    return self.file(pl.root, url.path[len('/artifacts/'):])
                if url.path == '/api/snapshot':
                    return self.respond(200, pl.snapshot())
                if url.path == '/api/acs':
                    return self.respond(200, pl.list_acs())
                if url.path == '/api/manifest':
                    return self.respond(200, pl.store.manifest())
                if url.path == '/api/compare':
                    return self.respond(200, pl.store.compare_runs(q['baseline'][0], q['candidate'][0]))
                if url.path.startswith('/api/runs/'):
                    return self.respond(200, pl.run_status(url.path.rsplit('/', 1)[1]))
                if url.path == '/api/evidence':
                    return self.respond(200, pl.evidence(ac=q.get('ac', [None])[0], run_id=q.get('run', [None])[0]))
                if url.path == '/api/stream':
                    return self.stream(int(q.get('since', [self.headers.get('Last-Event-ID') or pl.store.last_seq()])[0]))
                self.respond(404, {'error': 'Not found'})
            except (ValueError, KeyError) as e:
                self.respond(400, {'error': str(e)})

        def stream(self, seq):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            idle = 0
            try:
                while True:
                    events = pl.store.events_since(seq)
                    for e in events:
                        seq = e['seq']
                        self.wfile.write(f'id: {seq}\nevent: {e["kind"]}\ndata: {json.dumps(e)}\n\n'.encode())
                    if not events:
                        idle += 1
                        if idle % 30 == 0:
                            self.wfile.write(b': keepalive\n\n')
                    else:
                        idle = 0
                    self.wfile.flush()
                    if getattr(self.server, 'once', False):
                        self.close_connection = True
                        return
                    time.sleep(0.5)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
                return
    return Handler

def serve(pl, port=8777, block=True):
    server = ThreadingHTTPServer(('127.0.0.1', port), handler(pl))
    server.daemon_threads = True
    if not block:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
    print(f'Proofline: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=8777)
    p.add_argument('--root')
    a = p.parse_args(argv)
    try:
        serve(Proofline(a.root), a.port)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            p.exit(1, f'Port {a.port} is in use; try --port {a.port + 1}\n')
        raise

if __name__ == '__main__':
    main()
