#!/usr/bin/env python3
"""สร้างข้อสอบสะอาดสำหรับเว็บ: library/clean/<ชื่อ>.json

ตัวอย่าง:
  # ครบระบบ: มี PDF ข้อสอบ + PDF เฉลย
  python3 library/tools/build_clean.py --block Respiratory --cohort 52 \
      --question-pdf library/raw/Respiratory/52/MCQ.pdf --key-pdf library/raw/Respiratory/52/MCQ-key.pdf
  # ทุกชุดที่อยู่ใน library/raw/<บล็อก>/<รุ่น>/MCQ.pdf (+ MCQ-key.pdf)
  python3 library/tools/build_clean.py --all
  # ยังไม่มี PDF: ใช้ข้อมูลเดิมใน data.json + หลักฐานจากคำอธิบาย (library/evidence/*.json)
  python3 library/tools/build_clean.py --block Respiratory --cohort 52 --evidence library/evidence/respiratory_52_mcq.json

กติกาไม่ให้เฉลยมั่ว:
  - เฉลยมาจาก "ไฮไลต์ในไฟล์เฉลย" หรือ "ข้อความในไฟล์เฉลย" เท่านั้น ไม่เดาเอง
  - อ่านไม่ชัด/ขัดกัน/ไม่มีเฉลย -> review, ตัวเลือกไม่ครบ/ไม่มีคำตอบที่ถูก -> rejected
  - คนยืนยันผ่านแท็บตรวจเฉลย (ผลเก็บใน library/decisions/<ชื่อ>.json)
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path.cwd()
CLEAN = ROOT / "library" / "clean"
IMAGES = ROOT / "library" / "images"
DECISIONS = ROOT / "library" / "decisions"
EVIDENCE = ROOT / "library" / "evidence"
OPINIONS = ROOT / "library" / "opinions"
OP_LABEL = {"file": "ไฟล์เฉลย", "ai": "AI", "lecture": "Lecture", "cross_cohort": "ข้อซ้ำรุ่นอื่น"}
LETTERS = "ABCDE"
PLACEHOLDERS = {"", "-", "—", "–"}
IMAGE_HINT = re.compile(
    r"\b(arrow|figure|image|picture|pictured|photograph|photo|shown (?:below|above)|slide)\b|รูป|ภาพ", re.I)


def slugify(block, cohort, typ):
    s = f"{block}-{cohort}-{typ}".lower()
    return re.sub(r"[^a-z0-9ก-๙]+", "-", s).strip("-")


def norm(s):
    return re.sub(r"\W+", "", (s or "").lower())


def real_choices(choices):
    return {k: v.strip() for k, v in choices.items() if k in LETTERS and v and v.strip() not in PLACEHOLDERS}


def word_overlap(a, b):
    wa = {w for w in re.findall(r"\w+", a.lower()) if len(w) > 2}
    wb = set(re.findall(r"\w+", b.lower()))
    return len(wa & wb) / len(wa) if wa else 1.0


def load_old_exam(project, exam):
    p = ROOT / "data.json"
    if not p.exists() or not project:
        return None
    for pr in json.loads(p.read_text(encoding="utf-8")):
        if pr["name"] == project:
            for e in pr["exams"]:
                if e["name"] == exam:
                    return e
    return None


# ------------------------------------------------------------ build one
def build(block, cohort, typ="MCQ", year_group=None, question_pdf=None, key_pdf=None,
          evidence_path=None, old_project=None, old_exam=None):
    slug = slugify(block, cohort, typ)
    img_dir = IMAGES / slug
    ev = {}
    if not evidence_path:
        cand = EVIDENCE / (slug.replace("-", "_") + ".json")
        evidence_path = cand if cand.exists() else None
    if evidence_path:
        ev = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
        old_project = old_project or ev.get("project")
        old_exam = old_exam or ev.get("exam")
    old = load_old_exam(old_project, old_exam)
    old_by = {str(q["number"]): q for q in (old or {}).get("questions", [])}

    # --- ข้อสอบ: จาก PDF (ถ้ามี) ไม่งั้นจากข้อมูลเดิม
    qx = kx = None
    if question_pdf:
        import extract_pdf
        qx = extract_pdf.extract(question_pdf, img_dir / "q")
        base = qx["questions"]
        if key_pdf:
            ref = {int(r["number"]): r["choices"] for r in base}
            kx = extract_pdf.extract(key_pdf, img_dir / "k", reference=ref)
    else:
        if not old:
            sys.exit("ไม่มี PDF และหาข้อมูลเดิมใน data.json ไม่เจอ (ใส่ --evidence ที่มี project/exam)")
        base = [{"number": str(q["number"]), "stem": q["stem"], "choices": q["choices"],
                 "highlight": {"letter": None, "confidence": "none", "scores": {}},
                 "images": [], "crops": [], "pages": [], "issues": []} for q in old["questions"]]
    k_by = {r["number"]: r for r in (kx or {}).get("questions", [])}
    decisions = {}
    dpath = DECISIONS / f"{slug}.json"
    if dpath.exists():
        decisions = json.loads(dpath.read_text(encoding="utf-8"))

    # ความเห็นจากแหล่งอื่น (AI / Lecture): library/opinions/<ชื่อ>.<แหล่ง>.json
    ext, ext_reviewed = {}, {}
    for f in sorted(OPINIONS.glob(f"{slug}.*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        src = d.get("source") or f.stem.split(".")[-1]
        ext_reviewed.setdefault(src, set()).update(str(x) for x in d.get("reviewed", []))
        for num, o in (d.get("opinions") or {}).items():
            ext.setdefault(str(num), []).append({"source": src, "letter": o.get("letter"),
                                                  "reason": o.get("reason", ""), "ref": o.get("ref", "")})

    questions, counts = [], {"verified": 0, "quick_check": 0, "review": 0, "rejected": 0}
    for r in base:
        n = r["number"]
        ch = real_choices(r["choices"])
        item = (ev.get("items") or {}).get(n, {})
        flag = (ev.get("source_flags") or {}).get(n)
        kq = k_by.get(n)
        hl = (kq or {}).get("highlight") or {"letter": None, "confidence": "none", "scores": {}}
        ev_letter = item.get("letter")
        strength = item.get("strength")
        reasons = []
        if flag:
            reasons.append(flag)

        # เฉลยที่อ่านได้จากไฟล์เฉลย
        correct, source = None, None
        if hl["letter"]:
            correct, source = hl["letter"], "highlight"
        elif ev_letter:
            correct, source = ev_letter, "text" if strength in ("named", "computed") else "text-implied"

        status = None
        if len(ch) < 3:
            status = "rejected"; reasons.append("ตัวเลือกไม่ครบ ใช้เป็นข้อสอบไม่ได้")
        elif item.get("no_valid_answer"):
            status = "rejected"; reasons.append(item.get("note", "ไม่มีคำตอบที่ถูก"))
        else:
            problems = []
            if not key_pdf and not ev_letter and not item.get("note"):
                problems.append("ยังไม่มีไฟล์เฉลย/หลักฐานเฉลย")
            if hl["confidence"] == "ambiguous":
                problems.append("ไฮไลต์ในไฟล์เฉลยกำกวม (เห็นหลายตัวเลือก)")
            if hl["letter"] and ev_letter and hl["letter"] != ev_letter:
                problems.append(f"ไฮไลต์ชี้ {hl['letter']} แต่คำอธิบายชี้ {ev_letter}")
            if correct is None and not problems:
                problems.append(item.get("note") or "อ่านเฉลยไม่ได้ (ไม่เห็นไฮไลต์ และไม่มีคำอธิบายระบุตัวเลือก)")
            if correct and correct not in ch:
                problems.append("เฉลยที่อ่านได้ไม่อยู่ในตัวเลือก")
            if kq and word_overlap(r["stem"], kq["stem"]) < 0.8:
                problems.append("โจทย์ในไฟล์ข้อสอบกับไฟล์เฉลยไม่ตรงกัน")
            if question_pdf and IMAGE_HINT.search(r["stem"]) and not r["images"]:
                problems.append("โจทย์อ้างถึงรูป แต่ไม่พบรูปในโจทย์")
            if not question_pdf and flag and "รูป" in flag:
                problems.append("โจทย์อ้างถึงรูป ต้องใช้ PDF เพื่อตัดรูป")
            if problems:
                status = "review"; reasons += problems
            elif source == "highlight" and hl["confidence"] == "high":
                status = "verified"
            elif source == "highlight":  # medium
                status = "verified" if ev_letter == correct and strength in ("named", "computed") else "quick_check"
                if status == "quick_check":
                    reasons.append("ไฮไลต์ไม่ชัดมาก ให้คนกวาดตาดู")
            elif source == "text":
                status = "verified"
            else:
                status = "quick_check"; reasons.append("ไฟล์เฉลยไม่ระบุตรง ๆ ต้องตีความ ให้คนกวาดตาดู")

        o = old_by.get(n)
        if o and correct and o.get("correct") and o["correct"] != correct:
            reasons.append(f"เฉลยเดิมในระบบ ({o['correct']}) ต่างจากเฉลยที่อ่านได้ ({correct})")

        entry = {
            "id": f"{slug}-{int(n):03d}",
            "number": n,
            "stem": r["stem"],
            "choices": ch,
            "correct": correct if status in ("verified", "quick_check") else (correct if status == "review" else None),
            "key_source": source,
            "status": status,
            "reasons": reasons,
            "highlight": {"letter": hl["letter"], "confidence": hl["confidence"]},
            "evidence": item.get("quote"),
            "old_correct": o.get("correct") if o else None,
            "images": r["images"],
            "crops_question": r["crops"],
            "crops_key": (kq or {}).get("crops", []),
        }
        # คนตัดสินแล้ว (ชนะทุกอย่าง)
        d = decisions.get(n)
        if d:
            entry["decision"] = d
            if d.get("action") == "reject":
                entry["status"] = "rejected"
            elif d.get("action") == "approve" and (d.get("correct") or entry["correct"]) in ch:
                entry["correct"] = d.get("correct") or entry["correct"]
                entry["status"] = "verified"
                entry["key_source"] = "manual"
        file_letter = correct if source else None
        ops = []
        if file_letter:
            ops.append({"source": "file", "letter": file_letter,
                        "reason": {"highlight": "ไฮไลต์ในไฟล์เฉลย", "text": "คำอธิบายในไฟล์เฉลย",
                                   "text-implied": "คำอธิบายในไฟล์เฉลย (ตีความ)"}.get(source, "")})
        ops += ext.get(n, [])
        for src, rv in ext_reviewed.items():
            if n in rv and file_letter and not any(o["source"] == src for o in ops):
                ops.append({"source": src, "letter": file_letter, "reason": "เห็นด้วยกับเฉลยในไฟล์"})
        entry["opinions"] = ops
        entry["base_status"] = entry["status"]
        counts[entry["status"]] += 1
        questions.append(entry)

    blank = sorted(set((qx or {}).get("blank_numbers", [])) | set(ev.get("source_blank_numbers", [])))
    out = {
        "id": slug, "block": block, "year_group": year_group, "cohort": str(cohort), "type": typ,
        "name": f"{block} PSU {cohort} {typ}",
        "source": {"question_pdf": question_pdf and str(Path(question_pdf).as_posix()),
                   "key_pdf": key_pdf and str(Path(key_pdf).as_posix()),
                   "drive_question_id": ev.get("question_file_drive_id"), "drive_key_id": ev.get("key_file_drive_id")},
        "source_blank_numbers": blank,
        "source_note": ev.get("source_note", ""),
        "counts": counts,
        "questions": questions,
    }
    CLEAN.mkdir(parents=True, exist_ok=True)
    (CLEAN / f"{slug}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{slug}: {len(questions)} ข้อ -> {counts}")
    return slug


# ------------------------------------------------------------ index + duplicates
def build_index():
    exams, groups = [], {}
    files = sorted(p for p in CLEAN.glob("*.json") if p.name != "index.json")
    data = {p: json.loads(p.read_text(encoding="utf-8")) for p in files}
    # ล้างผลที่ index รอบก่อนเติมไว้ (ให้รันซ้ำได้ ผลเหมือนเดิม)
    for ex in data.values():
        for q in ex["questions"]:
            q["status"] = q.get("base_status", q["status"])
            q["opinions"] = [o for o in q.get("opinions", []) if o["source"] != "cross_cohort"]
            q["reasons"] = [r for r in q.get("reasons", []) if not r.startswith("มีความเห็นต่าง")]
            q.pop("duplicate_of", None); q.pop("duplicate_group_size", None)
    for p, ex in data.items():
        for q in ex["questions"]:
            key = norm(q["stem"]) + "|" + "|".join(norm(q["choices"].get(L, "")) for L in LETTERS)
            groups.setdefault(key, []).append(q)
    dup = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        for q in members:
            q["duplicate_of"] = members[0]["id"] if q is not members[0] else None
            q["duplicate_group_size"] = len(members)
            for o in members:
                if o is not q and o.get("correct"):
                    q["opinions"].append({"source": "cross_cohort", "letter": o["correct"],
                                          "reason": "ข้อเดียวกันในชุด " + o["id"], "ref": o["id"]})
        dup += len(members) - 1
    # ความเห็นไม่ตรง -> ต้องตรวจ (ยกเว้นคนตัดสินแล้ว)
    for p, ex in data.items():
        for q in ex["questions"]:
            for o in q["opinions"]:
                o["agree"] = o.get("letter") == q.get("correct")
            diff = [o for o in q["opinions"] if o["source"] != "file" and o.get("letter") and q.get("correct") and not o["agree"]]
            q["dispute"] = bool(diff)
            if diff and q.get("key_source") != "manual" and q["status"] in ("verified", "quick_check"):
                q["status"] = "review"
                q["reasons"].append("มีความเห็นต่าง: " + ", ".join(f"{OP_LABEL.get(o['source'], o['source'])} ชี้ {o['letter']}" for o in diff))
    for p, ex in data.items():
        c = {"verified": 0, "quick_check": 0, "review": 0, "rejected": 0}
        for q in ex["questions"]:
            c[q["status"]] += 1
        ex["counts"] = c
        p.write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
        exams.append({"id": ex["id"], "block": ex["block"], "year_group": ex.get("year_group"),
                      "cohort": ex["cohort"], "type": ex["type"], "name": ex["name"],
                      "file": f"library/clean/{p.name}", "counts": c, "total": len(ex["questions"])})
    (CLEAN / "index.json").write_text(json.dumps({"exams": exams}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"index: {len(exams)} ชุด, ข้อซ้ำข้ามชุด {dup}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--block"); ap.add_argument("--cohort"); ap.add_argument("--type", default="MCQ")
    ap.add_argument("--year-group", type=int)
    ap.add_argument("--question-pdf"); ap.add_argument("--key-pdf"); ap.add_argument("--evidence")
    a = ap.parse_args()
    if a.all:
        raw = ROOT / "library" / "raw"
        for q in sorted(raw.glob("*/*/*.pdf")):
            if q.stem.endswith("-key"):
                continue
            key = q.with_name(q.stem + "-key.pdf")
            build(q.parent.parent.name, q.parent.name, q.stem, a.year_group, str(q.relative_to(ROOT)),
                  str(key.relative_to(ROOT)) if key.exists() else None)
    else:
        if not (a.block and a.cohort):
            ap.error("ต้องใส่ --block และ --cohort (หรือใช้ --all)")
        build(a.block, a.cohort, a.type, a.year_group, a.question_pdf, a.key_pdf, a.evidence)
    build_index()


if __name__ == "__main__":
    main()
