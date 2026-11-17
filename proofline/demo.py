"""Fixture demo: drives the real Proofline pipeline with the fixture kane-cli.
Verdicts are scripted (see fixtures/fake_kane.py) and the UI labels them as fixture data."""
import os
import shutil
import sys
from pathlib import Path

from .service import Proofline

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent / 'examples'

def run_demo(root):
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    os.environ['PROOFLINE_KANE_BIN'] = f'{sys.executable} {HERE / "fixtures" / "fake_kane.py"}'
    pl = Proofline(root)
    pl.store.save_setting('target', dict(name='TodoMVC (example)', url='https://demo.playwright.dev/todomvc', fixture=True))
    pl.ingest_prd(EXAMPLES / 'prd-todomvc-v1.md', label='todomvc demo')
    pl.extract_context()
    for uc in ('uc-1', 'uc-2', 'uc-3', 'uc-4', 'uc-5'):
        pl.design_tests(uc)
    for _ in range(3):
        pl.run_suite()
    pl.maintain(EXAMPLES / 'prd-todomvc-v2.md')
    return pl
