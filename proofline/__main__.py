"""python3 -m proofline <command>"""
import argparse
import json
import os
import sys
from pathlib import Path

def main(argv=None):
    p = argparse.ArgumentParser(prog='proofline', description='Every requirement, proven live.')
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('serve', help='Run the dashboard on 127.0.0.1'); s.add_argument('--port', type=int, default=8777); s.add_argument('--root')
    sub.add_parser('mcp', help='Run the MCP server on stdio')
    d = sub.add_parser('demo', help='Fixture session through the real pipeline, then serve'); d.add_argument('--port', type=int, default=8777)
    d.add_argument('--root', default='runs/demo'); d.add_argument('--no-serve', action='store_true')
    st = sub.add_parser('status')
    for name in ('ingest', 'maintain'):
        x = sub.add_parser(name); x.add_argument('path')
    x = sub.add_parser('design'); x.add_argument('use_case'); x.add_argument('--max', type=int)
    x = sub.add_parser('run'); x.add_argument('path', nargs='?'); x.add_argument('--url')
    sub.add_parser('acs')
    x = sub.add_parser('manifest'); x.add_argument('--out')
    x = sub.add_parser('export'); x.add_argument('out')
    x = sub.add_parser('pages', help='Redacted static GitHub Pages demo of a run store')
    x.add_argument('out', nargs='?', default='docs/demo'); x.add_argument('--root', default='runs/live')
    a = p.parse_args(argv)
    if a.cmd == 'mcp':
        from .mcp import main as mcp_main
        return mcp_main()
    if a.cmd == 'serve':
        from .server import main as serve_main
        return serve_main(['--port', str(a.port)] + (['--root', a.root] if a.root else []))
    if a.cmd == 'demo':
        from .demo import run_demo
        pl = run_demo(Path(a.root))
        print(json.dumps(pl.export_manifest(), indent=2))
        if not a.no_serve:
            from .server import serve
            serve(pl, a.port)
        return
    if a.cmd == 'pages':
        from .pages import build_pages
        print(json.dumps(build_pages(a.root, a.out), indent=2, default=str))
        return
    from .service import Proofline
    pl = Proofline()
    if a.cmd == 'status': out = pl.status()
    elif a.cmd == 'ingest': out = pl.ingest_prd(a.path)
    elif a.cmd == 'maintain': out = pl.maintain(a.path)
    elif a.cmd == 'design': out = pl.design_tests(a.use_case, a.max)
    elif a.cmd == 'run': out = pl.run_suite(a.path, a.url)
    elif a.cmd == 'acs': out = pl.list_acs()
    elif a.cmd == 'manifest': out = pl.export_manifest(a.out)
    elif a.cmd == 'export':
        from .export_static import export_static
        out = export_static(pl, a.out)
    print(json.dumps(out, indent=2, default=str))

if __name__ == '__main__':
    sys.exit(main())
