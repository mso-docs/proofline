"""Export a self-contained static report: the dashboard plus a frozen snapshot,
the screenshots it references, and the artifact manifest."""
import json
import shutil
from pathlib import Path

from .server import WEB

def export_static(pl, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ('style.css', 'app.js'):
        shutil.copy2(WEB / name, out / name)
    snap = pl.snapshot()
    snap['static'] = True
    for a in snap['artifacts']:
        src = pl.root / a['path']
        if src.exists():
            dest = out / 'artifacts' / a['path']
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    (out / 'snapshot.json').write_text(json.dumps(snap))
    (out / 'manifest.json').write_text(json.dumps(pl.store.manifest(), indent=2))
    html = (WEB / 'index.html').read_text().replace('/static/', '')
    html = html.replace('<script src="app.js"></script>',
                        '<script>window.PROOFLINE_SNAPSHOT=' + json.dumps(snap).replace('</', '<\\/') + '</script><script src="app.js"></script>')
    (out / 'index.html').write_text(html)
    return dict(path=str(out.name), files=sum(1 for _ in out.rglob('*') if _.is_file()))
