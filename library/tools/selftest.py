#!/usr/bin/env python3
"""ทดสอบตัวอ่าน PDF ด้วยไฟล์จำลอง (ไม่ต้องมี PDF จริง)
รัน: python3 library/tools/selftest.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import extract_pdf as ex  # noqa: E402

fitz = ex.fitz
FS = 11


def _inline(page, y, choices, hi=None, x=50):
    for L, txt in choices:
        t = f"{L}. {txt}"
        w = fitz.get_text_length(t, fontsize=FS)
        if L == hi:
            page.draw_rect(fitz.Rect(x - 2, y - 10, x + w + 2, y + 3), fill=(1, 1, 0), color=None)
        page.insert_text((x, y), t, fontsize=FS)
        x += w + 14


def _lines(page, y, choices, hi=None, x=50):
    for L, txt in choices:
        t = f"{L}. {txt}"
        w = fitz.get_text_length(t, fontsize=FS)
        if L == hi:
            page.draw_rect(fitz.Rect(x - 2, y - 10, x + w + 2, y + 3), fill=(0.6, 1, 0.6), color=None)
        page.insert_text((x, y), t, fontsize=FS)
        y += 16
    return y


def build(path, key=False):
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    p1, p2 = doc[0], doc[1]
    p1.insert_text((50, 60), "RESPIRATORY SYSTEM", fontsize=14)
    for i, line in enumerate(["1. first instruction", "2. second instruction", "3. third instruction"]):
        p1.insert_text((215, 85 + 14 * i), line, fontsize=FS)  # คำชี้แจงกลางหน้า ไม่ใช่ข้อ
    # ข้อ 1: ตัวเลือกอยู่บรรทัดเดียว
    p1.insert_text((50, 130), "1. A patient was stabbed at the manubrium. Which structure is hit?", fontsize=FS)
    _inline(p1, 150, [("A", "Trachea"), ("B", "Aorta"), ("C", "Pulmonary artery"), ("D", "Pulmonary vein"), ("E", "Azygos vein")],
            hi="A" if key else None)
    # ข้อ 2: มีรูป + ตัวเลือกแยกบรรทัด
    p1.insert_text((50, 200), "2. The X-ray shows a mass at the arrow. Which lobe?", fontsize=FS)
    pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 160, 90), False)
    pm.set_rect(pm.irect, (40, 90, 200))
    p1.insert_image(fitz.Rect(50, 210, 210, 300), pixmap=pm)
    _lines(p1, 330, [("A", "Right upper"), ("B", "Right middle"), ("C", "Right lower"), ("D", "Left upper"), ("E", "Left lower")],
           hi="C" if key else None)
    if key:  # กล่องคำอธิบายสีเหลืองอ่อน แทรกกลางตัวเลือก
        p1.draw_rect(fitz.Rect(250, 336, 480, 356), fill=(1, 1, 0.5), color=None)
        p1.insert_text((255, 350), "NOTE this explanation is not a choice", fontsize=9)
    p1.insert_text((50, 430), "3. -", fontsize=FS)  # ข้อว่าง
    # ข้อ 5 คร่อมหน้า (4 อยู่หน้า 2)
    p1.insert_text((50, 470), "4. Which nerve supplies the diaphragm and passes the neck?", fontsize=FS)
    _lines(p1, 490, [("A", "Vagus"), ("B", "Phrenic")], hi="B" if key else None)
    _lines(p2, 60, [("C", "Intercostal"), ("D", "Sympathetic"), ("E", "Hypoglossal")])
    p2.insert_text((50, 130), "5. A long stem that sits on page two only. What is the answer?", fontsize=FS)
    _lines(p2, 150, [("A", "One"), ("B", "Two"), ("C", "Three"), ("D", "Four"), ("E", "Five")], hi="D" if key else None)
    # ข้อ 6: เลขติดข้อความ + ตัวเลือกตัวพิมพ์เล็ก
    p2.insert_text((50, 330), "6.Glued number then stem text. Which is right?", fontsize=FS)
    _lines(p2, 350, [("a", "alpha"), ("b", "bravo"), ("c", "charlie"), ("d", "delta"), ("e", "echo")])
    if key:  # วงกลมสีม่วงล้อม c. และกากบาทขีดฆ่า a. (ต้องจับวงกลมเท่านั้น)
        p2.draw_circle((54, 378), 10, color=(0.6, 0, 1), width=1)
        p2.draw_line((44, 340), (62, 356), color=(0, 0, 1)); p2.draw_line((44, 356), (62, 340), color=(0, 0, 1))
    p2.insert_text((50, 450), "7.-", fontsize=FS)  # ข้อว่างแบบเลขติดขีด
    for p in (p1, p2):
        p.insert_text((50, 820), "VICHAKARN MED PSU 52", fontsize=9)
    doc.save(path)


def main():
    tmp = Path(tempfile.mkdtemp())
    qpdf, kpdf = tmp / "q.pdf", tmp / "k.pdf"
    build(qpdf, key=False)
    build(kpdf, key=True)

    q = ex.extract(qpdf, tmp / "imgq", rel_base=tmp)
    nums = [r["number"] for r in q["questions"]]
    assert nums == ["1", "2", "4", "5", "6"], nums
    assert q["blank_numbers"] == [3, 7], q["blank_numbers"]
    by = {r["number"]: r for r in q["questions"]}
    assert by["1"]["choices"]["A"] == "Trachea" and by["1"]["choices"]["E"] == "Azygos vein", by["1"]["choices"]
    assert all(r["highlight"]["letter"] is None for r in q["questions"]), "ไฟล์ข้อสอบไม่ควรมีไฮไลต์"
    assert len(by["2"]["images"]) == 1 and (tmp / by["2"]["images"][0]).exists(), by["2"]["images"]
    assert by["4"]["choices"]["E"] == "Hypoglossal" and by["4"]["pages"] == [0, 1], by["4"]["pages"]
    assert "VICHAKARN" not in by["5"]["choices"]["E"] and "VICHAKARN" not in by["5"]["stem"]

    ref = {int(r["number"]): r["choices"] for r in q["questions"]}
    k = ex.extract(kpdf, tmp / "imgk", reference=ref, rel_base=tmp)
    kb = {r["number"]: r for r in k["questions"]}
    got = {n: (r["highlight"]["letter"], r["highlight"]["confidence"]) for n, r in kb.items()}
    assert got["1"][0] == "A" and got["2"][0] == "C" and got["4"][0] == "B" and got["5"][0] == "D" and got["6"][0] == "C", got
    assert by["6"]["choices"]["C"] == "charlie" and by["6"]["stem"].startswith("Glued"), by["6"]
    assert all(c == "high" for _, c in got.values()), got
    print("ผ่านทุกข้อ:", got)
    print("รูปที่ตัดได้ข้อ 2:", by["2"]["images"], "| ภาพโจทย์:", by["1"]["crops"])


if __name__ == "__main__":
    main()
