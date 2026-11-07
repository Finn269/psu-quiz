#!/usr/bin/env python3
"""แปลงผลดาวน์โหลดจาก Google Drive (ไฟล์ JSON ที่ระบบเก็บให้) เป็น PDF ใน library/raw

ขั้นตอน: เรียกเครื่องมือ Google Drive download_file_content ด้วย fileId
ถ้าไฟล์ใหญ่ ระบบจะเก็บผลลงไฟล์ในเครื่องและบอกพาธ -> ส่งพาธนั้นให้สคริปต์นี้

ใช้: python3 library/tools/drive_import.py <ไฟล์ผลดาวน์โหลด> <ปลายทาง.pdf> [ขนาดไบต์ที่ควรได้]
"""
import base64
import json
import sys
from pathlib import Path


def main():
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    expected = int(sys.argv[3]) if len(sys.argv) > 3 else None
    d = json.loads(src.read_text(encoding="utf-8"))
    data = base64.b64decode(d["content"])
    if not data.startswith(b"%PDF"):
        sys.exit(f"ไม่ใช่ PDF: {d.get('title')}")
    if expected and abs(len(data) - expected) > 1:
        sys.exit(f"ขนาดไม่ตรง: ได้ {len(data)} คาด {expected} ({d.get('title')})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"{d.get('title')} -> {dest} ({len(data):,} ไบต์)")


if __name__ == "__main__":
    main()
