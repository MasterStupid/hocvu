import docx, sys
from lxml import etree
d = docx.Document('in.docx')
body = d.element.body
kids = list(body.iterchildren())
for i in [0,1,2,3]:
    s = etree.tostring(kids[i], encoding='unicode')
    print(i, len(s))
    print(s[:3000])
    print('...')
    print(s[-1500:])
    print('==========')
