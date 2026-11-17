"""Drift: what changed between two PRD versions, and which tests it makes stale."""
import difflib
import re

from .prd import parse_prd

MARK = re.compile(r'(\S+)')

def word_marks(old, new):
    """Return (old_html, new_html) with changed words wrapped in <mark>."""
    a, b = old.split(' '), new.split(' ')
    sm = difflib.SequenceMatcher(a=a, b=b)
    oa, ob = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        x, y = ' '.join(a[i1:i2]), ' '.join(b[j1:j2])
        if op == 'equal':
            oa.append(esc(x)); ob.append(esc(y))
        else:
            if x: oa.append(f'<mark>{esc(x)}</mark>')
            if y: ob.append(f'<mark>{esc(y)}</mark>')
    return ' '.join(oa), ' '.join(ob)

def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def prd_drift(old_text, new_text, tests_by_ac=None, old_name='old', new_name='new'):
    tests_by_ac = tests_by_ac or {}
    old = {a['id']: a for a in parse_prd(old_text)}
    new = {a['id']: a for a in parse_prd(new_text)}
    changed = [k for k in old if k in new and old[k]['title'] != new[k]['title']]
    added = [k for k in new if k not in old]
    removed = [k for k in old if k not in new]
    lines = []
    ol, nl = old_text.splitlines(), new_text.splitlines()
    for group in difflib.SequenceMatcher(a=ol, b=nl).get_grouped_opcodes(1):
        lines.append(dict(kind='hunk', text=f'@@ -{group[0][1]+1} +{group[0][3]+1} @@'))
        for op, i1, i2, j1, j2 in group:
            if op == 'equal':
                lines += [dict(kind='ctx', old=i1 + k + 1, new=j1 + k + 1, html=esc(ol[i1 + k])) for k in range(i2 - i1)]
                continue
            pairs = max(i2 - i1, j2 - j1)
            for k in range(pairs):
                o = ol[i1 + k] if i1 + k < i2 else None
                n = nl[j1 + k] if j1 + k < j2 else None
                if o is not None and n is not None:
                    oh, nh = word_marks(o, n)
                else:
                    oh, nh = esc(o or ''), esc(n or '')
                if o is not None:
                    lines.append(dict(kind='del', old=i1 + k + 1, new=None, html=oh))
                if n is not None:
                    lines.append(dict(kind='add', old=None, new=j1 + k + 1, html=nh))
    stale = []
    for ac in changed + removed:
        for test in tests_by_ac.get(ac, []):
            stale.append(dict(ac=ac, test=test, reason='criterion removed' if ac in removed else 'criterion text changed',
                              was=old[ac]['title'], now=new.get(ac, {}).get('title')))
    untested = [k for k in added if not tests_by_ac.get(k)]
    return dict(old=old_name, new=new_name, changed=changed, added=added, removed=removed, stale=stale,
                untested_new=untested, lines=lines, plus=sum(1 for l in lines if l['kind'] == 'add'),
                minus=sum(1 for l in lines if l['kind'] == 'del'))
