#!/usr/bin/env python3
"""ตรวจข้อสอบหนึ่งชุดก่อนให้เว็บใช้

ใช้: python3 library/tools/check_exam.py library/evidence/<ชื่อ>.json library/staging/<ชื่อ>.json

อ่านข้อมูลเดิมจาก data.json แล้วเทียบกับหลักฐานจากไฟล์เฉลย (evidence)
สถานะที่ได้:
  verified    เฉลยตรงกับไฟล์เฉลยโดยไฟล์ระบุชัด (named/computed)
  quick_check เฉลยตรงกับไฟล์เฉลยแต่ต้องตีความเล็กน้อย (implied) ให้คนกวาดตาดู
  review      ยังไม่มั่นใจ: ขัดกัน, กำกวม, หรือไม่มีหลักฐานในข้อความ
  rejected    ใช้ทำข้อสอบไม่ได้: ตัวเลือกไม่ครบ หรือไม่มีคำตอบที่ถูก
เว็บควรใช้เฉพาะ verified (กับ quick_check ที่คนยืนยันแล้ว)
"""
import json
import sys
from pathlib import Path

PLACEHOLDERS = {"", "-", "—", "–"}


def real_choices(q):
    return {k: v.strip() for k, v in q.get("choices", {}).items()
            if v and v.strip() not in PLACEHOLDERS}


def main(evidence_path, out_path):
    ev = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    data = json.loads(Path("data.json").read_text(encoding="utf-8"))
    project = next(p for p in data if p["name"] == ev["project"])
    exam = next(e for e in project["exams"] if e["name"] == ev["exam"])

    out, counts = [], {"verified": 0, "quick_check": 0, "review": 0, "rejected": 0}
    conflicts = []
    for q in exam["questions"]:
        n = str(q["number"])
        ch = real_choices(q)
        stored = q.get("correct")
        item = ev["items"].get(n, {})
        key = item.get("letter")
        reasons = []
        flag = ev.get("source_flags", {}).get(n)
        if flag:
            reasons.append(flag)

        if len(ch) < 3:
            status = "rejected"
            reasons.append("ตัวเลือกไม่ครบ ใช้เป็นข้อสอบไม่ได้")
        elif item.get("no_valid_answer"):
            status = "rejected"
            reasons.append(item.get("note", "ไม่มีคำตอบที่ถูก"))
        elif stored not in ch:
            status = "review"
            reasons.append("เฉลยเดิมไม่อยู่ในตัวเลือก")
        elif key is None:
            status = "review"
            reasons.append(item.get("note", "ไม่มีหลักฐานเฉลยในข้อความ ต้องดูไฮไลต์ใน PDF"))
        elif key != stored:
            status = "review"
            reasons.append(f"เฉลยเดิมขัดกับไฟล์เฉลย: เดิม {stored} แต่ไฟล์เฉลยชี้ {key}")
            conflicts.append(n)
        elif "ต้องมีรูป" in (flag or ""):
            status = "review"
        elif item.get("strength") in ("named", "computed"):
            status = "verified"
        else:
            status = "quick_check"
            reasons.append("ไฟล์เฉลยไม่ระบุตรง ๆ ต้องตีความ ให้คนกวาดตาดู")

        counts[status] += 1
        out.append({
            "number": n,
            "stem": q["stem"],
            "choices": ch,
            "stored_correct": stored,
            "key_letter": key,
            "evidence": item.get("quote"),
            "status": status,
            "reasons": reasons,
        })

    result = {
        "exam": ev["exam"],
        "source": {"question_file": ev["question_file_drive_id"], "key_file": ev["key_file_drive_id"]},
        "source_blank_numbers": ev.get("source_blank_numbers", []),
        "source_note": ev.get("source_note", ""),
        "counts": counts,
        "questions": out,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    total = len(out)
    print(f"{ev['exam']}: {total} ข้อ -> {counts}")
    print("เฉลยเดิมขัดกับไฟล์เฉลย:", ", ".join(conflicts) or "ไม่มี")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
