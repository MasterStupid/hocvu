"""Pass 2: read page numbers from the LibreOffice PDF (outline for headings,
page text for captions) and write them into the cached PAGEREF results.
Usage: python fill.py in.docx in.pdf out.docx   (run with hvenv python: needs fitz + docx)
"""
import re
import sys
import unicodedata

import docx
import fitz
from docx.oxml.ns import qn

src, pdf, dst = sys.argv[1:4]
d = docx.Document(src)
body = d.element.body
doc = fitz.open(pdf)


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()


# PAGEREF fields in order, with their label text (first w:t of the entry
# paragraph) and the cached result (last w:t of the paragraph)
fields = []  # (anchor, label, result_t)
for p in body.iter(qn("w:p")):
    instr = [x.text for x in p.iter(qn("w:instrText")) if x.text and "PAGEREF" in x.text]
    if not instr:
        continue
    anchor = instr[0].split()[1]
    if not (anchor.startswith("_Toc9") or anchor.startswith("_Ref")):
        continue
    ts = list(p.iter(qn("w:t")))
    fields.append((anchor, ts[0].text, ts[-1]))

toc = [(lvl, norm(title), page) for lvl, title, page in doc.get_toc()]
heads = [f for f in fields if f[0].startswith("_Toc9")]
assert len(toc) == len(heads), (len(toc), len(heads))
bad = 0
for (anchor, label, t), (lvl, title, page) in zip(heads, toc):
    if norm(label) != title:
        bad += 1
        print("LABEL MISMATCH:", repr(label), "| pdf:", repr(title))
    t.text = str(page)
print(f"headings: {len(heads)} filled, {bad} label mismatches")

# captions: first page at/after MỞ ĐẦU whose text has the caption label at a line start
start = next(page for lvl, title, page in toc if title == "MỞ ĐẦU")
pages = [norm(doc[i].get_text()) for i in range(doc.page_count)]
lines = [[norm(x) for x in doc[i].get_text().split("\n")] for i in range(doc.page_count)]
caps = [f for f in fields if f[0].startswith("_Ref")]
for anchor, label, t in caps:
    key = label.split(":")[0] + ":"
    found = None
    for i in range(start - 1, doc.page_count):
        if any(line.startswith(key) for line in lines[i]):
            found = i + 1
            break
    assert found, label
    t.text = str(found)
print(f"captions: {len(caps)} filled")
d.save(dst)
for anchor, label, t in fields[:6] + caps[:3]:
    print(t.text, label[:70])
