from pathlib import Path
import re
from docx import Document
from docx.shared import Inches, Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path("/home/runner/workspace")
source = ROOT / ".work/upgrade_plan.md"
out = ROOT / "HocVu_AI_Ke_hoach_nang_cap_toan_dien_v1.docx"
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.top_margin, sec.bottom_margin = Cm(2), Cm(2)
sec.left_margin, sec.right_margin = Cm(2.2), Cm(1.8)
sec.header_distance, sec.footer_distance = Cm(0.8), Cm(0.8)
styles = doc.styles
for name in ("Normal", "Title", "Subtitle", "Heading 1", "Heading 2", "Heading 3"):
    s = styles[name]
    s.font.name = "Times New Roman"
    s.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Times New Roman")
    s.font.color.rgb = RGBColor.from_string("172C42")
styles["Normal"].font.color.rgb = RGBColor.from_string("202020")
styles["Normal"].font.size = Pt(11.5)
styles["Normal"].paragraph_format.space_after = Pt(6)
styles["Normal"].paragraph_format.line_spacing = 1.12
styles["Title"].font.size = Pt(23)
styles["Heading 1"].font.size = Pt(15)
styles["Heading 1"].paragraph_format.space_before = Pt(15)
styles["Heading 1"].paragraph_format.space_after = Pt(7)
styles["Heading 2"].font.size = Pt(13)
styles["Heading 3"].font.size = Pt(12)
for n in ("Heading 1", "Heading 2", "Heading 3"):
    styles[n].paragraph_format.keep_with_next = True

header = sec.header.paragraphs[0]
header.text = "HOCVU AI  |  KẾ HOẠCH NÂNG CẤP & TRIỂN KHAI THỬ"
header.runs[0].font.size = Pt(9)
header.runs[0].font.color.rgb = RGBColor.from_string("62758A")
footer = sec.footer.paragraphs[0]
footer.alignment = 2
footer.add_run("Đề xuất v1.0 • 09/11/2026  |  Trang ").font.size = Pt(9)
field = OxmlElement("w:fldSimple")
field.set(qn("w:instr"), "PAGE")
footer._p.append(field)

def add_link(p, label, url):
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    rel = p.part.relate_to(url, RT.HYPERLINK, is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), rel)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "176A8C")
    rpr.append(color)
    run.append(rpr)
    text = OxmlElement("w:t")
    text.text = label
    run.append(text)
    h.append(run)
    p._p.append(h)

def text_to_p(p, text):
    url = re.search(r"https://\S+", text)
    if url:
        p.add_run(text[:url.start()])
        add_link(p, url.group(), url.group())
        p.add_run(text[url.end():])
    else:
        p.add_run(text)

def make_table(rows):
    parsed = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    parsed = [r for r in parsed if not all(re.fullmatch(r":?-+:?", c) for c in r)]
    cols = len(parsed[0])
    table = doc.add_table(rows=0, cols=cols)
    table.style = "Table Grid"
    table.autofit = False
    widths = {
        3: [2.8, 7.2, 7.0],
        4: [3.3, 2.6, 5.5, 5.6],
        5: [1.9, 1.2, 4.6, 2.6, 6.7],
    }.get(cols, [17 / cols] * cols)
    for i, row in enumerate(parsed):
        cells = table.add_row().cells
        trpr = table.rows[-1]._tr.get_or_add_trPr()
        cant = OxmlElement("w:cantSplit")
        trpr.append(cant)
        if i == 0:
            repeat = OxmlElement("w:tblHeader")
            trpr.append(repeat)
        for j, value in enumerate(row):
            if value.startswith("HV-"):
                value = value.replace(",", ", ")
            cells[j].width = Cm(widths[j])
            cells[j].vertical_alignment = 1
            p = cells[j].paragraphs[0]
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.space_before = Pt(4)
            text_to_p(p, value)
            for r in p.runs:
                r.font.size = Pt(9.5)
                if i == 0:
                    r.font.bold = True
                    r.font.color.rgb = RGBColor.from_string("FFFFFF")
            if i == 0:
                tcpr = cells[j]._tc.get_or_add_tcPr()
                shade = OxmlElement("w:shd")
                shade.set(qn("w:fill"), "24465F")
                tcpr.append(shade)
    for col, width in zip(table.columns, widths):
        col.width = Cm(width)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)

lines = source.read_text().splitlines()
i = 0
while i < len(lines):
    line = lines[i].strip()
    if not line:
        i += 1
        continue
    if line.startswith("|"):
        rows = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            rows.append(lines[i])
            i += 1
        make_table(rows)
        continue
    if line.startswith("# "):
        doc.add_paragraph(line[2:], "Title")
    elif line.startswith("## "):
        doc.add_heading(line[3:], 1)
    elif line.startswith("- "):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.4)
        p.paragraph_format.first_line_indent = Cm(-0.25)
        text_to_p(p, "• " + line[2:])
    else:
        p = doc.add_paragraph()
        text_to_p(p, line)
    i += 1
doc.core_properties.title = "HocVu AI – Kế hoạch nâng cấp toàn diện"
doc.core_properties.subject = "Lộ trình nhóm nhỏ triển khai thử; backlog và tiêu chí nghiệm thu"
doc.core_properties.author = "HocVu AI"
doc.save(out)
print(out.name)
print("Tables:", len(doc.tables), "Paragraphs:", len(doc.paragraphs))
