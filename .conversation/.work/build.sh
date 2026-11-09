#!/bin/bash
set -e
cd /tmp/work
export TMPDIR=/home/runner/workspace/.work/tmp
R="timeout 150 soffice -env:UserInstallation=file:///home/runner/workspace/.work/lo_profile --headless --convert-to pdf --outdir render3"
./venv/bin/python fix.py in.docx v3_pass1.docx
rm -f render3/*; $R v3_pass1.docx >/dev/null 2>&1
./hvenv/bin/python fill.py v3_pass1.docx render3/v3_pass1.pdf v3_pass2.docx 2>&1 | grep -v -i warn | head -3
rm -f render3/*; $R v3_pass2.docx >/dev/null 2>&1
./hvenv/bin/python fill.py v3_pass2.docx render3/v3_pass2.pdf check2.docx 2>&1 | grep -v -i warn | head -2
./hvenv/bin/python - <<'PY' 2>&1 | grep -v -i warn
import docx, fitz
from docx.oxml.ns import qn
def vals(path):
    d = docx.Document(path); out=[]
    for p in d.element.body.iter(qn('w:p')):
        if any('PAGEREF' in (x.text or '') for x in p.iter(qn('w:instrText'))):
            ts = list(p.iter(qn('w:t'))); out.append((ts[0].text[:50], ts[-1].text))
    return out
a, b = vals('v3_pass2.docx'), vals('check2.docx')
print('fields', len(a), 'stable-diffs:', [(x, y) for x, y in zip(a, b) if x != y])
doc = fitz.open('render3/v3_pass2.pdf'); print('pages', doc.page_count)
for e in doc.get_toc():
    if e[0] == 1: print(e)
PY
