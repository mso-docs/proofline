"""Read acceptance criteria out of a PRD written in Markdown.

Recognized shape (headings at any level):
    ## UC-1 Search the docs
    ### AC-1.1 Query returns ranked results in under 2 s
Bullets like "- AC-1.2: ..." are accepted too.
"""
import re

UC_RE = re.compile(r'^#{1,6}\s*(UC-\d+)\b[\s:.\-–—]*(.*)$', re.I)
AC_RE = re.compile(r'^(?:#{1,6}|[-*])\s*\**(AC-\d+(?:\.\d+)*)\**\b[\s:.\-–—]*(.*)$', re.I)
AC_ID = re.compile(r'\bAC-\d+(?:\.\d+)*\b', re.I)

def parse_prd(text, source=None):
    acs, uc, uc_title = [], None, None
    for line in text.splitlines():
        s = line.strip()
        m = UC_RE.match(s)
        if m:
            uc, uc_title = m.group(1).upper(), m.group(2).strip()
            continue
        m = AC_RE.match(s)
        if m:
            acs.append(dict(id=m.group(1).upper(), title=m.group(2).strip() or m.group(1).upper(),
                            use_case=uc, use_case_title=uc_title, source=source))
    return acs

def ac_for_test(path, text):
    """Which AC a *_test.md proves: frontmatter `ac:` first, then the file name, then the first AC id in the body."""
    fm = re.search(r'^---\s*\n(.*?)\n---', text, re.S)
    if fm:
        m = re.search(r'^\s*(?:ac|proofline_ac|acceptance_criterion)\s*:\s*["\']?(AC-[\d.]+)', fm.group(1), re.I | re.M)
        if m:
            return m.group(1).upper()
    m = re.search(r'ac[-_](\d+)[-_](\d+)', str(path), re.I)
    if m:
        return f'AC-{m.group(1)}.{m.group(2)}'
    m = AC_ID.search(text)
    return m.group(0).upper() if m else None
