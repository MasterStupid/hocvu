"""Pass 1: fix heading numbering/styles, rebuild TOC + figure/table lists,
apply verified text edits, table/caption pagination flags.
Usage: python fix.py in.docx out.docx
"""
import re
import sys
from xml.sax.saxutils import escape

import docx
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
src, dst = sys.argv[1], sys.argv[2]
d = docx.Document(src)
body = d.element.body
report = []


def text(el):
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def pstyle(p):
    ppr = p.find(qn("w:pPr"))
    if ppr is None or ppr.find(qn("w:pStyle")) is None:
        return "Normal"
    return ppr.find(qn("w:pStyle")).get(qn("w:val"))


def X(xml):
    return parse_xml(xml.replace("<ROOT", "<ROOT"))


# ---------------------------------------------------------------- styles
styles = d.styles.element
TNR = ('<w:rFonts %s w:ascii="Times New Roman" w:eastAsia="Times New Roman" '
       'w:hAnsi="Times New Roman" w:cs="Times New Roman"/>' % nsdecls("w"))


def style_el(sid):
    return styles.find(f"w:style[@w:styleId='{sid}']", NS)


for sid in ("Heading1", "Heading2", "Heading3", "Heading1Char", "Heading2Char", "Heading3Char"):
    st = style_el(sid)
    if st is None:
        continue
    rpr = st.find(qn("w:rPr"))
    if rpr is None:
        continue
    old = rpr.find(qn("w:rFonts"))
    if old is not None:
        new = parse_xml(TNR)
        old.addprevious(new)
        rpr.remove(old)
    col = rpr.find(qn("w:color"))
    if col is not None:
        for a in list(col.attrib):
            del col.attrib[a]
        col.set(qn("w:val"), "000000")
report.append("styles: Heading1-3 (+Char) -> Times New Roman, black")

toch = style_el("TOCHeading")
for tag in ("w:pPr", "w:rPr"):
    old = toch.find(qn(tag))
    if old is not None:
        toch.remove(old)
toch.append(parse_xml(
    f'<w:pPr {nsdecls("w")}><w:numPr><w:numId w:val="0"/></w:numPr>'
    '<w:spacing w:before="0" w:after="240"/><w:ind w:left="0" w:firstLine="0"/>'
    '<w:jc w:val="center"/><w:outlineLvl w:val="9"/></w:pPr>'))
toch.append(parse_xml(
    f'<w:rPr {nsdecls("w")}><w:b/><w:color w:val="000000"/><w:kern w:val="0"/>'
    '<w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr>'))

# numbering: level sizes match heading text; chapter title truly centred
numbering = d.part.numbering_part.element
num1 = numbering.find("w:num[@w:numId='1']", NS)
absid = num1.find(qn("w:abstractNumId")).get(qn("w:val"))
absn = numbering.find(f"w:abstractNum[@w:abstractNumId='{absid}']", NS)
for lvl in absn.findall(qn("w:lvl")):
    il = lvl.get(qn("w:ilvl"))
    if il == "0":
        ind = lvl.find(qn("w:pPr")).find(qn("w:ind"))
        ind.set(qn("w:left"), "0")
        ind.set(qn("w:firstLine"), "0")
    sz = lvl.find(qn("w:rPr")).find(qn("w:sz")) if lvl.find(qn("w:rPr")) is not None else None
    if sz is not None and il in ("1", "2"):
        sz.set(qn("w:val"), {"1": "28", "2": "24"}[il])
report.append("numbering: H2 number 14pt, H3 number 12pt, chapter title centred")

# ---------------------------------------------------------------- headings
children = list(body.iterchildren())
heads = [p for p in children if p.tag == qn("w:p") and pstyle(p) in ("Heading1", "Heading2", "Heading3")]


def set_unnumbered(p, style):
    pPr = p.get_or_add_pPr()
    numPr = pPr.get_or_add_numPr()
    numPr.get_or_add_ilvl().val = 0
    numPr.get_or_add_numId().val = 0
    ind = pPr.get_or_add_ind()
    for a in list(ind.attrib):
        del ind.attrib[a]
    ind.set(qn("w:left"), {"Heading1": "0", "Heading2": "284", "Heading3": "568"}[style])
    ind.set(qn("w:firstLine"), "0")


ch = sec = sub = 0
in_back = False
entries = []  # (level, label, paragraph)
for p in heads:
    s = pstyle(p)
    t = text(p).strip()
    pPr = p.find(qn("w:pPr"))
    numPr = pPr.find(qn("w:numPr")) if pPr is not None else None
    explicit0 = numPr is not None and numPr.find(qn("w:numId")) is not None and \
        numPr.find(qn("w:numId")).get(qn("w:val")) == "0"
    if s == "Heading1" and t in ("PHỤ LỤC", "TÀI LIỆU THAM KHẢO"):
        in_back = True
    level = int(s[-1])
    if in_back or explicit0:
        set_unnumbered(p, s)
        entries.append((level, t, p))
        continue
    # numbered by the multilevel list
    if s == "Heading1":
        ch += 1; sec = sub = 0
        label = f"CHƯƠNG {ch}: {t}"
    elif s == "Heading2":
        sec += 1; sub = 0
        auto = f"{ch}.{sec}"
        m = re.match(r"^(\d+\.\d+)\.?\s+", t)
        if m:
            if m.group(1) != auto:
                report.append(f"!! manual {m.group(1)} != auto {auto}: {t}")
            t = t[m.end():]
        label = f"{auto}. {t}"
    else:
        sub += 1
        auto = f"{ch}.{sec}.{sub}"
        m = re.match(r"^(\d+\.\d+\.\d+)\.?\s+", t)
        if m:
            if m.group(1) != auto:
                report.append(f"!! manual {m.group(1)} != auto {auto}: {t}")
            t = t[m.end():]
        label = f"{auto}. {t}"
    # rewrite heading text without the typed number (single-run headings)
    ts = list(p.iter(qn("w:t")))
    full = "".join(x.text or "" for x in ts)
    if full.strip() != t:
        assert len(ts) == 1, ("multi-run heading", full)
        ts[0].text = t
    entries.append((level, label, p))
report.append(f"headings: {len(entries)} TOC entries, {ch} chapters")

# every Heading 1 starts on a new page: add pageBreakBefore where the
# preceding paragraph carries no explicit page break (Chương 1, PHỤ LỤC)
for p in heads:
    if pstyle(p) != "Heading1":
        continue
    prev = p.getprevious()
    if prev is None or prev.tag != qn("w:p"):
        continue
    if any(b.get(qn("w:type")) == "page" for b in prev.iter(qn("w:br"))):
        continue
    p.get_or_add_pPr().get_or_add_pageBreakBefore()
    report.append(f"pageBreakBefore: {text(p)[:40]}")

# ---------------------------------------------------------------- bookmarks
all_ids = [int(b.get(qn("w:id"))) for b in body.iter(qn("w:bookmarkStart"))]
old_ids = set()
for b in list(body.iter(qn("w:bookmarkStart"))):
    if b.get(qn("w:name"), "").startswith("_Toc"):
        old_ids.add(b.get(qn("w:id")))
        b.getparent().remove(b)
for b in list(body.iter(qn("w:bookmarkEnd"))):
    if b.get(qn("w:id")) in old_ids:
        b.getparent().remove(b)
next_id = max(all_ids + [0]) + 100


def add_bookmark(p, name):
    global next_id
    next_id += 1
    bs = parse_xml(f'<w:bookmarkStart {nsdecls("w")} w:id="{next_id}" w:name="{name}"/>')
    be = parse_xml(f'<w:bookmarkEnd {nsdecls("w")} w:id="{next_id}"/>')
    pPr = p.find(qn("w:pPr"))
    p.insert(1 if pPr is not None else 0, bs)
    p.append(be)


RP = "<w:rPr><w:noProof/><w:webHidden/></w:rPr>"


def link_runs(anchor, label, page="0"):
    return (
        f'<w:hyperlink w:anchor="{anchor}" w:history="1">'
        f'<w:r><w:rPr><w:noProof/></w:rPr><w:t xml:space="preserve">{escape(label)}</w:t></w:r>'
        f'<w:r>{RP}<w:tab/></w:r>'
        f'<w:r>{RP}<w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r>{RP}<w:instrText xml:space="preserve"> PAGEREF {anchor} \\h </w:instrText></w:r>'
        f'<w:r>{RP}<w:fldChar w:fldCharType="separate"/></w:r>'
        f'<w:r>{RP}<w:t>{page}</w:t></w:r>'
        f'<w:r>{RP}<w:fldChar w:fldCharType="end"/></w:r>'
        '</w:hyperlink>'
    )


def plain_runs(anchor, label, page="0"):
    """Entry for the figure/table lists: text, tab, PAGEREF (no hyperlink
    wrapper; LibreOffice drops hyperlinks that contain fields outside a TOC)."""
    return (
        f'<w:r><w:rPr><w:noProof/></w:rPr><w:t xml:space="preserve">{escape(label)}</w:t></w:r>'
        f'<w:r><w:rPr><w:noProof/></w:rPr><w:tab/></w:r>'
        f'<w:r><w:rPr><w:noProof/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:rPr><w:noProof/></w:rPr><w:instrText xml:space="preserve"> PAGEREF {anchor} \\h </w:instrText></w:r>'
        f'<w:r><w:rPr><w:noProof/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r>'
        f'<w:r><w:rPr><w:noProof/></w:rPr><w:t>{page}</w:t></w:r>'
        f'<w:r><w:rPr><w:noProof/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>'
    )


# ---------------------------------------------------------------- TOC
sdt = children[1]
assert sdt.tag == qn("w:sdt")
content = sdt.find(qn("w:sdtContent"))
for c in list(content):
    content.remove(c)
content.append(parse_xml(
    f'<w:p {nsdecls("w")}><w:pPr><w:pStyle w:val="TOCHeading"/></w:pPr>'
    '<w:r><w:t>MỤC LỤC</w:t></w:r></w:p>'))
TOC_IND = {1: "0", 2: "260", 3: "520"}
for n, (level, label, p) in enumerate(entries):
    name = f"_Toc9{n + 1:07d}"
    add_bookmark(p, name)
    field_start = ""
    if n == 0:
        field_start = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                       '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
                       '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
    content.append(parse_xml(
        f'<w:p {nsdecls("w")}><w:pPr><w:pStyle w:val="TOC{level}"/>'
        '<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9061"/></w:tabs>'
        f'<w:ind w:left="{TOC_IND[level]}" w:firstLine="0"/><w:rPr><w:noProof/></w:rPr></w:pPr>'
        f'{field_start}{link_runs(name, label)}</w:p>'))
content.append(parse_xml(
    f'<w:p {nsdecls("w")}><w:pPr><w:ind w:firstLine="0"/></w:pPr>'
    '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'))

# ---------------------------------------------------------------- captions + lists
children = list(body.iterchildren())
start_body = next(i for i, c in enumerate(children) if c.tag == qn("w:p") and text(c).strip() == "MỞ ĐẦU")
cap_re = re.compile(r"^(Hình|Bảng) ([0-9]+|[A-E])\.(\d+):")
captions = {}
for c in children[start_body:]:
    if c.tag != qn("w:p"):
        continue
    m = cap_re.match(text(c))
    if m:
        key = f"{m.group(1)} {m.group(2)}.{m.group(3)}"
        assert key not in captions, key
        name = ("_RefHinh" if m.group(1) == "Hình" else "_RefBang") + f"{m.group(2)}_{m.group(3)}"
        add_bookmark(c, name)
        captions[key] = (name, text(c).strip())
        pPr = c.get_or_add_pPr()
        if m.group(1) == "Bảng" and pPr.find(qn("w:keepNext")) is None:
            pPr.get_or_add_keepNext()
report.append(f"captions bookmarked: {sum(k.startswith('Hình') for k in captions)} figures, "
              f"{sum(k.startswith('Bảng') for k in captions)} tables")

list_seen = set()
for c in children[:start_body]:
    if c.tag != qn("w:p"):
        continue
    m = cap_re.match(text(c))
    if not m:
        continue
    key = f"{m.group(1)} {m.group(2)}.{m.group(3)}"
    name, cap_text = captions[key]
    if text(c).strip() != cap_text:
        report.append(f"list text differs from caption, using caption: {key}")
    new = parse_xml(
        f'<w:p {nsdecls("w")}><w:pPr>'
        '<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9061"/></w:tabs>'
        '<w:spacing w:after="40"/><w:ind w:left="0" w:firstLine="0"/><w:rPr><w:noProof/></w:rPr></w:pPr>'
        f'{plain_runs(name, cap_text)}</w:p>')
    c.addprevious(new)
    body.remove(c)
    list_seen.add(key)
missing = sorted(set(captions) - list_seen)
if missing:
    report.append(f"!! captions missing from front lists: {missing}")

# ---------------------------------------------------------------- code captions keepNext
for c in body.iterchildren(qn("w:p")):
    if re.match(r"^Đoạn mã [0-9A-E]+\.\d+:", text(c)):
        pPr = c.get_or_add_pPr()
        if pPr.find(qn("w:keepNext")) is None:
            pPr.get_or_add_keepNext()


# ---------------------------------------------------------------- text edits
def edit(prefix, old, new):
    hits = [c for c in body.iterchildren(qn("w:p")) if text(c).startswith(prefix)]
    assert len(hits) == 1, (prefix, len(hits))
    ts = list(hits[0].iter(qn("w:t")))
    assert len(ts) == 1, (prefix, "runs", len(ts))
    assert old in ts[0].text, (prefix, old)
    ts[0].text = ts[0].text.replace(old, new)


edit("Các thực nghiệm được chạy trên mã nguồn phiên bản d196445",
     "Cấu hình lai được kiểm tra riêng bằng encoder multilingual-e5-small thay thế tương thích NumPy do môi trường "
     "thiếu bộ nhớ để nạp PyTorch; vì vậy kết quả lai là phép thử trên cùng bộ ca, không phải kết quả triển khai sản "
     "xuất. Chi tiết và giới hạn được nêu ở mục 4.5.1.",
     "Cấu hình lai dùng mô hình multilingual-e5-small; do máy thực nghiệm không đủ bộ nhớ để nạp PyTorch, bộ mã hóa "
     "của mô hình được chạy bằng một bản cài đặt trên NumPy, nên kết quả lai chỉ dùng để so sánh độ chính xác trên "
     "cùng bộ câu hỏi, không phản ánh hiệu năng khi triển khai (mục 4.5.1).")
edit("Các thực nghiệm được chạy trên mã nguồn phiên bản d196445",
     "được tái lập bằng kịch bản run_exp.py (Phụ lục B, mục B.2);",
     "được tái lập bằng kịch bản run_exp.py (Phụ lục B, mục B.2), được bổ sung vào kho mã nguồn ở phiên bản 3f35189 "
     "mà không thay đổi mã nguồn của hệ thống;")

old534 = [c for c in body.iterchildren(qn("w:p")) if text(c).startswith("Cấu hình lai được chạy trên cùng bộ câu hỏi")]
assert len(old534) == 1
edit("Cấu hình lai được chạy trên cùng bộ câu hỏi", text(old534[0]),
     "Cấu hình lai được chạy bằng lệnh python run_exp.py --semantic trên cùng bộ câu hỏi và ngày tra cứu, với mô hình "
     "multilingual-e5-small. Do máy thực nghiệm không đủ bộ nhớ để nạp PyTorch, bộ mã hóa của mô hình được chạy bằng "
     "một bản cài đặt trên NumPy, dùng nguyên trọng số và bộ tách từ của mô hình. Kết quả được kiểm tra lại bằng một "
     "bản cài đặt NumPy thứ hai viết độc lập: mọi chỉ số độ chính xác và xếp hạng trong Bảng 4.11 trùng khớp giữa hai "
     "lần chạy. So với BM25, cấu hình lai không cải thiện độ chính xác trên bộ câu hỏi hiện có: Nhóm A giảm một câu "
     "đúng cấp điều (câu Q035 \u201c75 điểm rèn luyện xếp loại gì?\u201d được trả lời bằng một điều khác của cùng văn "
     "bản) và hai câu đứng hạng nhất khi truy xuất, Nhóm C giảm một hội thoại, các chỉ số còn lại giữ nguyên. Thời "
     "gian xử lý của cấu hình lai không được đưa vào so sánh vì tốc độ của bản cài đặt NumPy không đại diện cho cấu "
     "hình triển khai dùng PyTorch.")

edit("Ghi chú: Nhóm A xếp hạng chỉ gồm 40 câu hỏi",
     " ** Trung vị thời gian lấy từ các lần chạy ghi nhận, với số lượt đo khác nhau; không dùng để kết luận cấu hình "
     "lai nhanh/chậm hơn trong điều kiện tương đương.", "")

edit("Các phụ lục dưới đây gồm bộ câu hỏi kiểm thử",
     "kịch bản run_exp.py ở mục B.2 được viết cho phiên bản này để tái lập các thực nghiệm và được trình bày toàn văn.",
     "kịch bản run_exp.py ở mục B.2 dùng để tái lập các thực nghiệm, nằm ở thư mục gốc kho mã nguồn từ phiên bản "
     "3f35189 (phiên bản này chỉ bổ sung tệp run_exp.py so với d196445) và được trình bày toàn văn.")

edit("Kịch bản run_exp.py chạy lại các thực nghiệm tự động của Chương 4",
     "Đặt tệp ở thư mục gốc kho mã nguồn (cùng cấp với manage.py).",
     "Tệp nằm ở thư mục gốc kho mã nguồn, cùng cấp với manage.py.")

edit("Các lệnh ở Đoạn mã B.9 chạy từ thư mục gốc",
     "kết quả lai ở mục 4.5.1 được đo bằng encoder NumPy tương thích do máy thực nghiệm thiếu bộ nhớ.",
     "kết quả lai ở mục 4.5.1 được chạy bằng bộ mã hóa cài đặt trên NumPy do máy thực nghiệm thiếu bộ nhớ, vì vậy "
     "Bảng 4.11 không so sánh thời gian xử lý.")

edit("• Về truy xuất: cấu hình triển khai chỉ dùng BM25",
     "Cấu hình lai đã được thử với encoder multilingual-e5-small chạy bằng NumPy (mục 4.5.1) nhưng",
     "Cấu hình lai đã được thử với mô hình multilingual-e5-small (bộ mã hóa chạy bằng NumPy, mục 4.5.1) nhưng")

# Table 4.11: drop the hybrid timing row (NumPy timing is not representative)
tbls = list(body.iterchildren(qn("w:tbl")))
t411 = [t for t in tbls if text(t.findall(qn("w:tr"))[0]).startswith("Chỉ sốBM25Lai")]
assert len(t411) == 1
last = t411[0].findall(qn("w:tr"))[-1]
assert text(last).startswith("Trung vị thời gian xử lý")
t411[0].remove(last)
report.append("Table 4.11: removed hybrid timing row")

# ---------------------------------------------------------------- tables: header repeat + rows not split
ORDER_AFTER_CANTSPLIT = {qn(x) for x in ("w:trHeight", "w:tblHeader", "w:tblCellSpacing", "w:jc", "w:hidden",
                                          "w:ins", "w:del", "w:trPrChange")}
ORDER_AFTER_HEADER = {qn(x) for x in ("w:tblCellSpacing", "w:jc", "w:hidden", "w:ins", "w:del", "w:trPrChange")}


def trpr_of(tr):
    trPr = tr.find(qn("w:trPr"))
    if trPr is None:
        trPr = parse_xml(f'<w:trPr {nsdecls("w")}/>')
        tblPrEx = tr.find(qn("w:tblPrEx"))
        if tblPrEx is not None:
            tblPrEx.addnext(trPr)
        else:
            tr.insert(0, trPr)
    return trPr


def insert_ordered(parent, el, after_set):
    for i, c in enumerate(parent):
        if c.tag in after_set:
            parent.insert(i, el)
            return
    parent.append(el)


n_rows = 0
for t in body.iter(qn("w:tbl")):
    rows = t.findall(qn("w:tr"))
    for k, tr in enumerate(rows):
        trPr = trpr_of(tr)
        if trPr.find(qn("w:cantSplit")) is None:
            insert_ordered(trPr, parse_xml(f'<w:cantSplit {nsdecls("w")}/>'), ORDER_AFTER_CANTSPLIT)
            n_rows += 1
        if k == 0 and len(rows) > 3 and trPr.find(qn("w:tblHeader")) is None:
            insert_ordered(trPr, parse_xml(f'<w:tblHeader {nsdecls("w")}/>'), ORDER_AFTER_HEADER)
            report.append(f"tblHeader added: {text(tr)[:40]}")
report.append(f"cantSplit added to {n_rows} rows")

d.save(dst)
print("\n".join(report))
