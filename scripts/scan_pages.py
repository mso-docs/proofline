#!/usr/bin/env python3
"""Pre-publish gate for the GitHub Pages demo. Exit 0 only when every check passes.

  python3 scripts/scan_pages.py [docs] [--root runs/live]

1. redaction scan  ~/.config/git/hooks/redaction_scan.py tree <dir>   (skipped with a warning if absent)
2. gitleaks        gitleaks dir <dir>                                  (required)
3. literal check   account values from the local evidence packs, git user.email, login name and
                   host name, plus share-link / test-manager / artifact-store URL, id and email shapes.

Never prints a matched value: only the file, line and kind.
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proofline.pages import local_values  # noqa: E402

SHAPES = {
    'email': re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
    'share link': re.compile(r'https?://\S*(?:share|sharable)\S*', re.I),
    'test-manager url': re.compile(r'test-manager\.lambdatest\.com/'),
    'artifact-store url': re.compile(r'\.blob\.core\.windows\.net'),
    'share/org id': re.compile(r'(?i)(?:share_id|org_id|project_id|folder_id|testcase_id)\\?"?\s*[:=]\s*\\?"?(?!<)[A-Za-z0-9_-]{4,}'),
    'tailnet host': re.compile(r'\.ts\.net\b'),
    'home path': re.compile(r'/(?:Users|home)/(?!<)[A-Za-z0-9._-]+/'),
    'bearer/jwt': re.compile(r'(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.'),
}

def literal_check(target, root):
    values = local_values(root)
    hits = 0
    for p in sorted(target.rglob('*')):
        if not p.is_file():
            continue
        data = p.read_bytes()
        low = data.lower()
        for val, ph in values.items():
            needle = val.encode()
            found = needle.lower() in low if ph in ('<KANE_USER>', '<EMAIL>') else needle in data
            if found:
                hits += 1
                print(f'  FAIL {p.relative_to(target)}: private value ({ph.strip("<>/").lower()})')
        if b'\0' in data[:4096]:
            continue
        for n, line in enumerate(data.decode(errors='replace').splitlines(), 1):
            for kind, pat in SHAPES.items():
                if pat.search(line):
                    hits += 1
                    print(f'  FAIL {p.relative_to(target)}:{n}: {kind}')
    return hits, len(values)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('target', nargs='?', default='docs')
    ap.add_argument('--root', default='runs/live')
    a = ap.parse_args()
    target, failed = Path(a.target), False
    scan = Path.home() / '.config/git/hooks/redaction_scan.py'
    print('1/3 redaction scan')
    if scan.exists():
        r = subprocess.run([sys.executable, str(scan), 'tree', str(target)], capture_output=True, text=True)
        print('  ' + ((r.stdout + r.stderr).strip().replace('\n', '\n  ') or 'no output'))
        failed |= r.returncode != 0
        print('  ' + ('PASS' if r.returncode == 0 else f'FAIL (exit {r.returncode})'))
    else:
        print('  skipped: redaction_scan.py not installed on this machine')
    print('2/3 gitleaks')
    gl = shutil.which('gitleaks')
    if gl:
        r = subprocess.run([gl, 'dir', str(target), '--no-banner', '--redact', '--exit-code', '1'], capture_output=True, text=True)
        tail = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()][-2:]
        print('  ' + ' | '.join(tail))
        failed |= r.returncode != 0
        print('  ' + ('PASS' if r.returncode == 0 else f'FAIL (exit {r.returncode})'))
    else:
        failed = True
        print('  FAIL: gitleaks not found')
    print('3/3 literal and shape check')
    hits, n = literal_check(target, Path(a.root))
    failed |= hits > 0
    print(f'  {n} private values checked, {len(SHAPES)} shapes, {hits} findings: ' + ('FAIL' if hits else 'PASS'))
    print('RESULT: ' + ('FAIL' if failed else 'PASS'))
    return 1 if failed else 0

if __name__ == '__main__':
    sys.exit(main())
