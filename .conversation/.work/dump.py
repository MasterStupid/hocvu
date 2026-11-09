import docx, sys, re
from docx.document import Document as _D
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
d = docx.Document(sys.argv[1])
body = d.element.body
out = []
for child in body.iterchildren():
    tag = child.tag.split('}')[1]
    if tag == 'p':
        p = Paragraph(child, d)
        sty = p.style.name if p.style is not None else ''
        txt = p.text
        has_img = bool(child.findall('.//' + qn('w:drawing'))) or bool(child.findall('.//' + qn('w:pict')))
        out.append(('P', sty, txt, has_img))
    elif tag == 'tbl':
        t = Table(child, d)
        rows = []
        for r in t.rows:
            cells = []
            for c in r.cells:
                cells.append(c.text.replace('\n',' / '))
            rows.append(' | '.join(cells))
        out.append(('T', '', '\n'.join(rows), False))
    elif tag == 'sectPr':
        out.append(('S','', '', False))
    else:
        out.append(('X', tag, '', False))
import pickle
pickle.dump(out, open('/tmp/work/dump.pkl','wb'))
# print outline
for i,(k,sty,txt,img) in enumerate(out):
    if k=='P' and (sty.lower().startswith('heading') or sty.lower().startswith('title') or 'toc' in sty.lower()[:3]):
        print(i, k, sty, '|', txt[:120])
print('TOTAL blocks', len(out))
