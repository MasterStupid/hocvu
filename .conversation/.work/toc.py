import docx
from docx.oxml.ns import qn
d = docx.Document('in.docx')
body = d.element.body
sdt = list(body.iterchildren())[1]
for p in sdt.iter(qn('w:p')):
    sty = p.find(qn('w:pPr'))
    s = ''
    if sty is not None and sty.find(qn('w:pStyle')) is not None:
        s = sty.find(qn('w:pStyle')).get(qn('w:val'))
    t = ''.join(x.text or '' for x in p.iter(qn('w:t')))
    instr = ''.join(x.text or '' for x in p.iter(qn('w:instrText')))
    print(s, '|', t[:110], '|', instr.strip()[:60] if 'TOC' in instr else '')
