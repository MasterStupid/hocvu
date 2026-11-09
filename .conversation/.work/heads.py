import docx
from docx.oxml.ns import qn
d = docx.Document('in.docx')
body = d.element.body
for i, el in enumerate(body.iterchildren()):
    if el.tag != qn('w:p'): continue
    pPr = el.find(qn('w:pPr'))
    if pPr is None: continue
    ps = pPr.find(qn('w:pStyle'))
    if ps is None or not ps.get(qn('w:val')).startswith('Heading'): continue
    num = pPr.find(qn('w:numPr'))
    numinfo = ''
    if num is not None:
        il = num.find(qn('w:ilvl')); ni = num.find(qn('w:numId'))
        numinfo = f"numPr ilvl={il.get(qn('w:val')) if il is not None else '-'} numId={ni.get(qn('w:val')) if ni is not None else '-'}"
    ind = pPr.find(qn('w:ind'))
    t = ''.join(x.text or '' for x in el.iter(qn('w:t')))
    print(i, ps.get(qn('w:val')), numinfo or 'style-num', '|', t[:70])
