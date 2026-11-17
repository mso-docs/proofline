import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKE = ROOT / 'proofline' / 'fixtures' / 'fake_kane.py'
EXAMPLES = ROOT / 'examples'

def fixture_env():
    os.environ['PROOFLINE_KANE_BIN'] = f'{sys.executable} {FAKE}'

def tmp():
    return Path(tempfile.mkdtemp(prefix='proofline-test-'))
