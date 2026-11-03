#!/usr/bin/env python3
"""อ่าน PDF ข้อสอบ: แยกข้อ, อ่านไฮไลต์เฉลย, ตัดรูปประกอบโจทย์

ใช้เป็นโมดูล (build_clean.py เรียกใช้) หรือรันเดี่ยว:
  python3 library/tools/extract_pdf.py <file.pdf> <โฟลเดอร์รูปที่จะเก็บ>

ผลลัพธ์ต่อข้อ: number, stem, choices, highlight (ตัวเลือกที่ถูกไฮไลต์), images, crops, pages
ไม่เดาเฉลยเอง: ถ้าไม่เห็นไฮไลต์ชัด จะได้ highlight.letter = None
"""
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:  # เวอร์ชันเก่า
    import fitz

ZOOM = 2.0
Q_RE = re.compile(r"^(\d{1,3})[.)]$")
C_RE = re.compile(r"^([A-Ea-e])[.)](.*)$")
QGLUE_RE = re.compile(r"^(\d{1,3}[.)])(\D.*)$")
LETTERS = "ABCDE"
PLACEHOLDERS = {"", "-", "—", "–"}


def _norm(s):
    return re.sub(r"\W+", "", s.lower())


# ---------------------------------------------------------------- words
def _page_words(page):
    """คำทั้งหน้า เรียงตามการอ่าน; แยก 'A.xxx' ที่ติดกันออกเป็น 'A.' กับ 'xxx'"""
    out = []
    for x0, y0, x1, y1, text, block, line, wno in page.get_text("words", sort=True):
        m = C_RE.match(text)
        g = QGLUE_RE.match(text) if wno == 0 else None  # เลขข้อติดข้อความ เช่น 12.ทารก
        if m and m.group(2):
            w = (x1 - x0)
            cut = x0 + w * 2 / max(len(text), 2)
            out.append({"t": text[0] + text[1], "b": (x0, y0, cut, y1), "line": (block, line), "wno": wno})
            out.append({"t": m.group(2), "b": (cut, y0, x1, y1), "line": (block, line), "wno": wno + 1})
        elif g:
            w = (x1 - x0)
            cut = x0 + w * len(g.group(1)) / max(len(text), 2)
            out.append({"t": g.group(1), "b": (x0, y0, cut, y1), "line": (block, line), "wno": wno})
            out.append({"t": g.group(2), "b": (cut, y0, x1, y1), "line": (block, line), "wno": wno + 1})
        else:
            out.append({"t": text, "b": (x0, y0, x1, y1), "line": (block, line), "wno": wno})
    return out


def _repeated_margin_noise(doc, words_by_page):
    """บรรทัดหัว/ท้ายที่ซ้ำหลายหน้า (เช่น ชื่อรุ่น เลขหน้า) ให้ตัดทิ้ง"""
    seen = {}
    for pi, words in enumerate(words_by_page):
        h = doc[pi].rect.height
        lines = {}
        for w in words:
            lines.setdefault(w["line"], []).append(w)
        for ws in lines.values():
            y0 = min(w["b"][1] for w in ws)
            y1 = max(w["b"][3] for w in ws)
            if y0 < 0.10 * h or y1 > 0.90 * h:
                key = _norm(" ".join(w["t"] for w in ws))
                if key:
                    seen.setdefault(key, set()).add(pi)
    return {k for k, v in seen.items() if len(v) >= 2}


# ---------------------------------------------------------------- highlight
def _fill_fraction(pix, rect):
    """สัดส่วนพิกเซลในกรอบที่เป็นสีพื้นไฮไลต์ (สีสด ไม่ใช่ตัวอักษรดำ/ขาว)"""
    x0 = max(int(rect[0] * ZOOM), 0)
    y0 = max(int(rect[1] * ZOOM), 0)
    x1 = min(int(rect[2] * ZOOM) + 1, pix.width)
    y1 = min(int(rect[3] * ZOOM) + 1, pix.height)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    n = pix.n
    data = pix.samples
    stride = pix.stride
    hit = total = 0
    for y in range(y0, y1):
        row = data[y * stride + x0 * n: y * stride + x1 * n]
        for i in range(0, len(row) - n + 1, n):
            r, g, b = row[i], row[i + 1], row[i + 2]
            mx, mn = max(r, g, b), min(r, g, b)
            total += 1
            if mx - mn >= 30 and (0.299 * r + 0.587 * g + 0.114 * b) >= 110:
                hit += 1
    return hit / total if total else 0.0


def _stroke_points(page):
    """จุดตัวอย่างตามเส้นวาด (ทีละเส้น) ใช้หาว่ามีเส้นล้อมตัวอักษรเลือกหรือไม่"""
    strokes = []
    for d in page.get_drawings():
        if d.get("type") not in ("s", "fs", "f"):
            continue
        if d["rect"].width > 60 or d["rect"].height > 60:   # ไม่ใช่วงกลม/ลายมือเล็ก ๆ
            continue
        pts = []
        for it in d["items"]:
            if it[0] == "l":
                p1, p2 = it[1], it[2]
                pts += [(p1.x + (p2.x - p1.x) * k / 6, p1.y + (p2.y - p1.y) * k / 6) for k in range(7)]
            elif it[0] == "c":
                p1, c1, c2, p2 = it[1], it[2], it[3], it[4]
                for k in range(11):
                    s = k / 10
                    m = 1 - s
                    pts.append((m ** 3 * p1.x + 3 * m * m * s * c1.x + 3 * m * s * s * c2.x + s ** 3 * p2.x,
                                m ** 3 * p1.y + 3 * m * m * s * c1.y + 3 * m * s * s * c2.y + s ** 3 * p2.y))
        if pts:
            strokes.append(pts)
    return strokes


def _is_circled(strokes, mx, my):
    """มีเส้นวาดเส้นเดียวล้อมจุด (mx,my) ที่รัศมี 5-17 pt ครอบคลุมอย่างน้อย 7 จาก 12 ช่วง (30 องศา) หรือไม่
    (หรือเส้นโค้งหลายเส้นที่แต่ละเส้นครอบคลุม >= 4 ช่วง รวมกัน >= 9)
    วงกลม/วงกลมไม่ปิด = ครอบคลุมมาก; กากบาท ขีดทับ เครื่องหมายถูก = ครอบคลุมน้อย จึงไม่นับ"""
    per = []
    through = 0  # จุดของเส้นที่พาดผ่านตัวอักษรเอง (กากบาท/ขีดฆ่า) วงกลมจริงต้องโปร่งตรงกลาง
    for pts in strokes:
        cov = set()
        for x, y in pts:
            dx, dy = x - mx, y - my
            r = (dx * dx + dy * dy) ** 0.5
            if r < 4.5:
                through += 1
            elif 5 <= r <= 17:
                cov.add(int((math.degrees(math.atan2(dy, dx)) + 180) // 30) % 12)
        per.append(cov)
    if through >= 2:
        return False
    if any(len(c) >= 7 for c in per):
        return True
    arcs = [c for c in per if len(c) >= 4]
    return len(set().union(*arcs)) >= 9 if arcs else False


def _repair_zero_bbox(doc):
    """บาง PDF มีเนื้อหาในฟอร์มที่ BBox = [0 0 0 0] ทำให้เห็นเป็นหน้าว่าง ซ่อมในหน่วยความจำ (ไม่แก้ไฟล์จริง)"""
    fixed = 0
    for pi in range(len(doc)):
        page = doc[pi]
        w, h = page.rect.width, page.rect.height
        for x in page.get_xobjects():
            xr = x[0]
            try:
                kind, val = doc.xref_get_key(xr, "BBox")
            except Exception:
                continue
            nums = re.findall(r"-?\d+\.?\d*", val or "")
            if kind == "array" and nums and all(float(v) == 0 for v in nums):
                doc.xref_set_key(xr, "BBox", f"[0 0 {w:.0f} {h:.0f}]")
                fixed += 1
    return fixed


def _annot_overlap(page, rect):
    """ถ้ามี highlight annotation ซ้อนทับกรอบ คืนสัดส่วนการซ้อน"""
    best = 0.0
    area = max((rect[2] - rect[0]) * (rect[3] - rect[1]), 1e-6)
    try:
        for a in page.annots() or []:
            if a.type[0] not in (8,):  # 8 = highlight
                continue
            r = a.rect
            ix = max(0, min(rect[2], r.x1) - max(rect[0], r.x0))
            iy = max(0, min(rect[3], r.y1) - max(rect[1], r.y0))
            best = max(best, ix * iy / area)
    except Exception:
        pass
    return min(best, 1.0)


def _decide_highlight(scores, min_best=0.30, amb_ratio=2.0, high_ratio=3.0, high_best=0.5):
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked or ranked[0][1] < min_best:
        return {"letter": None, "confidence": "none", "scores": scores}
    best, second = ranked[0][1], (ranked[1][1] if len(ranked) > 1 else 0.0)
    if second >= min_best and best < amb_ratio * second:
        return {"letter": None, "confidence": "ambiguous", "scores": scores}
    conf = "high" if best >= high_best and best >= high_ratio * max(second, 0.01) else "medium"
    return {"letter": ranked[0][0], "confidence": conf, "scores": scores}


# ---------------------------------------------------------------- main
def extract(pdf_path, out_dir, reference=None, rel_base=None):
    """reference: {เลขข้อ: {ตัวเลือก: ข้อความ}} ใช้กรองคำอธิบายแทรกในไฟล์เฉลย"""
    doc = fitz.open(pdf_path)
    _repair_zero_bbox(doc)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rel_base = Path(rel_base) if rel_base else Path.cwd()

    def rel(p):
        try:
            return Path(p).resolve().relative_to(rel_base.resolve()).as_posix()
        except ValueError:
            return Path(p).as_posix()

    words_by_page = [_page_words(p) for p in doc]
    noise = _repeated_margin_noise(doc, words_by_page)
    pix_cache = {}
    loops_cache = {}

    def pix_of(pi):
        if pi not in pix_cache:
            pix_cache[pi] = doc[pi].get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
        return pix_cache[pi]

    # --- กรองคำ + หาจุดเริ่มข้อ
    tokens = []  # ลำดับอ่านทั้งเอกสาร
    # ขอบซ้ายของเลขข้อ = ตำแหน่งที่พบบ่อยที่สุดทั้งเอกสาร (กันรายการคำชี้แจงกลางหน้าแรก)
    xs = [round(w["b"][0] / 4) * 4 for ws in words_by_page for w in ws if Q_RE.match(w["t"]) and w["wno"] == 0]
    left = Counter(xs).most_common(1)[0][0] if xs else None
    for pi, words in enumerate(words_by_page):
        h = doc[pi].rect.height
        line_text = {}
        for w in words:
            line_text.setdefault(w["line"], []).append(w["t"])
        for w in words:
            in_margin = w["b"][1] < 0.10 * h or w["b"][3] > 0.90 * h
            if in_margin and _norm(" ".join(line_text[w["line"]])) in noise:
                continue
            is_q = bool(Q_RE.match(w["t"])) and w["wno"] == 0 and left is not None and abs(w["b"][0] - left) <= 25
            tokens.append({"page": pi, "t": w["t"], "b": w["b"], "is_q": is_q})

    questions = []
    cur = None
    last_num = 0
    for tk in tokens:
        if tk["is_q"]:
            num = int(Q_RE.match(tk["t"]).group(1))
            restart = num == 1 and questions and all(not _has_marker(q["tokens"]) for q in questions)
            if restart:
                questions, last_num = [], 0
            if num == last_num + 1 or (last_num < num <= last_num + 3):
                cur = {"number": num, "tokens": [], "start": tk}
                questions.append(cur)
                last_num = num
                continue
        if cur is not None:
            cur["tokens"].append(tk)

    # --- แยก stem / choices
    result, blank = [], []
    page_regions = {}
    for q in questions:
        toks = q["tokens"]
        marks, expect = [], 0
        for i, tk in enumerate(toks):
            m = C_RE.match(tk["t"])
            if m and not m.group(2) and expect < 5 and m.group(1).upper() == LETTERS[expect]:
                marks.append((LETTERS[expect], i))
                expect += 1
        stem_end = marks[0][1] if marks else len(toks)
        stem_toks = toks[:stem_end]
        choices, choice_toks = {}, {}
        for k, (letter, i) in enumerate(marks):
            j = marks[k + 1][1] if k + 1 < len(marks) else len(toks)
            seg = toks[i + 1:j]
            choice_toks[letter] = seg
            choices[letter] = " ".join(t["t"] for t in seg).strip()
        for L in LETTERS:
            choices.setdefault(L, "")
        stem = " ".join(t["t"] for t in stem_toks).strip()
        issues = []
        if stem in PLACEHOLDERS and not any(choices.values()):
            blank.append(q["number"])
            continue

        # ไฮไลต์: ใช้เฉพาะคำที่อยู่ในตัวเลือกอ้างอิง (กันคำอธิบายที่แทรก)
        ref = (reference or {}).get(q["number"])
        scores = {}
        for letter in LETTERS:
            seg = choice_toks.get(letter, [])
            if ref and ref.get(letter):
                allowed = {_norm(w) for w in ref[letter].split()}
                seg = [t for t in seg if _norm(t["t"]) in allowed]
            seg = [t for t in seg if _norm(t["t"])]
            if not seg:
                continue
            # รวมกรอบเป็นรายหน้า
            by_page = {}
            for t in seg:
                by_page.setdefault(t["page"], []).append(t["b"])
            w_sum = s_sum = 0.0
            for pi, boxes in by_page.items():
                for b in boxes:
                    area = max((b[2] - b[0]) * (b[3] - b[1]), 1e-6)
                    s = max(_fill_fraction(pix_of(pi), b), _annot_overlap(doc[pi], b))
                    w_sum += area
                    s_sum += s * area
            scores[letter] = round(s_sum / w_sum, 3) if w_sum else 0.0
        highlight = _decide_highlight(scores)
        highlight["method"] = "fill"
        if highlight["confidence"] == "none":
            # ไม่มีไฮไลต์พื้น -> หาวงกลมที่วาดล้อมตัวอักษรเลือก (a. b. c.) โดยดูจากรูปร่างเส้นวาด
            circled = []
            for letter, mi in marks:
                mt = toks[mi]
                if mt["page"] not in loops_cache:
                    loops_cache[mt["page"]] = _stroke_points(doc[mt["page"]])
                mx, my = (mt["b"][0] + mt["b"][2]) / 2, (mt["b"][1] + mt["b"][3]) / 2
                if _is_circled(loops_cache[mt["page"]], mx, my):
                    circled.append(letter)
            sc = {L: (1.0 if L in circled else 0.0) for L, _ in marks}
            if len(circled) == 1:
                highlight = {"letter": circled[0], "confidence": "high", "scores": sc, "method": "circle"}
            elif len(circled) > 1:
                highlight = {"letter": None, "confidence": "ambiguous", "scores": sc, "method": "circle"}

        # ขอบเขตบนหน้า (ใช้ตัดรูป)
        pages = {}
        for t in [q["start"]] + toks:
            pg = pages.setdefault(t["page"], [1e9, 1e9, -1e9, -1e9])
            pg[0] = min(pg[0], t["b"][0]); pg[1] = min(pg[1], t["b"][1])
            pg[2] = max(pg[2], t["b"][2]); pg[3] = max(pg[3], t["b"][3])
        page_regions[q["number"]] = pages
        result.append({
            "number": str(q["number"]),
            "stem": stem,
            "choices": choices,
            "highlight": highlight,
            "images": [],
            "crops": [],
            "pages": sorted(pages),
            "issues": issues,
        })

    by_num = {r["number"]: r for r in result}

    # --- ตัดภาพโจทย์ทั้งข้อ (ไว้ให้คนตรวจเทียบ)
    for num, pages in page_regions.items():
        r = by_num.get(str(num))
        if not r:
            continue
        for pi, (x0, y0, x1, y1) in sorted(pages.items()):
            page = doc[pi]
            clip = fitz.Rect(0, max(y0 - 8, 0), page.rect.width, min(y1 + 8, page.rect.height))
            path = out_dir / f"crop-q{num:03d}-p{pi + 1}.png"
            page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=clip, alpha=False).save(str(path))
            r["crops"].append(rel(path))

    # --- รูปประกอบโจทย์
    xref_pages = {}
    infos = []
    for pi, page in enumerate(doc):
        for info in page.get_image_info(xrefs=True):
            bb = info["bbox"]
            w, h = bb[2] - bb[0], bb[3] - bb[1]
            if w < 30 or h < 30:
                continue
            if w * h > 0.85 * page.rect.width * page.rect.height:
                continue
            xref_pages.setdefault(info.get("xref"), set()).add(pi)
            infos.append((pi, info))
    repeated = {x for x, s in xref_pages.items() if x and len(s) >= max(2, len(doc) // 2 + 1)}
    counters = {}
    flat = [(int(n), pages) for n, pages in page_regions.items()]
    for pi, info in infos:
        if info.get("xref") in repeated:
            continue
        bb = info["bbox"]
        cy = (bb[1] + bb[3]) / 2
        owner = None
        for n, pages in sorted(flat):
            if pi in pages and pages[pi][1] - 4 <= cy:
                owner = n
        if owner is None:  # อยู่เหนือข้อแรกของหน้า -> เป็นของข้อสุดท้ายของหน้าก่อน
            prev = [n for n, pages in sorted(flat) if any(p < pi for p in pages)]
            owner = prev[-1] if prev else None
        r = by_num.get(str(owner)) if owner else None
        if not r:
            continue
        counters[owner] = counters.get(owner, 0) + 1
        path = out_dir / f"q{owner:03d}-img{counters[owner]}.png"
        doc[pi].get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=fitz.Rect(*bb), alpha=False).save(str(path))
        r["images"].append(rel(path))

    return {
        "pdf": rel(pdf_path),
        "page_count": len(doc),
        "blank_numbers": blank,
        "questions": result,
    }


def _has_marker(tokens):
    return any(C_RE.match(t["t"]) for t in tokens)


if __name__ == "__main__":
    res = extract(sys.argv[1], sys.argv[2])
    print(json.dumps(res, ensure_ascii=False, indent=1)[:4000])
    print(f"... {len(res['questions'])} ข้อ, ข้อว่าง {res['blank_numbers']}")
