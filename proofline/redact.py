"""Redaction for anything that reaches logs, events, or exported files.

Credentials are read from the environment only. Their values are scrubbed from
every string Proofline stores, together with common token shapes.
"""
import os
import re

SECRET_ENV = ('KANE_USERNAME', 'KANE_ACCESS_KEY', 'LT_USERNAME', 'LT_ACCESS_KEY',
              'LAMBDATEST_USERNAME', 'LAMBDATEST_ACCESS_KEY', 'TESTMU_USERNAME', 'TESTMU_ACCESS_KEY')
PATTERNS = [
    (re.compile(r'(--access-key[ =])\S+'), r'\1[REDACTED]'),
    (re.compile(r'(--username[ =])\S+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{12,}'), r'\1 [REDACTED]'),
    (re.compile(r'(?i)("?(?:access[_-]?key|token|password|secret|authorization|api[_-]?key)"?\s*[:=]\s*"?)[^"\s,}]{4,}'), r'\1[REDACTED]'),
    (re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'), '[REDACTED-JWT]'),
    (re.compile(r'\b(?:LT|lt)_[A-Za-z0-9]{20,}'), '[REDACTED]'),
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'), '[REDACTED-EMAIL]'),
    (re.compile(r'/(?:Users|home)/[^/\s"\']+'), '~'),
]

def secret_values():
    return [v for k in SECRET_ENV if (v := os.environ.get(k)) and len(v) >= 4]

def redact(text):
    if not isinstance(text, str):
        return text
    for value in secret_values():
        text = text.replace(value, '[REDACTED]')
    for pattern, repl in PATTERNS:
        text = pattern.sub(repl, text)
    return text

def redact_obj(obj):
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [redact_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    return obj
