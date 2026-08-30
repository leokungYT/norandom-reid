"""
ไฟล์เทสอ่าน UID ด้วย OCR - รันแยกจากบอทได้เลย (ใช้สูตรเดียวกับบอทจริง import จาก main.py)

วิธีใช้:
  python test-ocr.py                  -> เทสทุกเครื่องที่ต่อ adb อยู่
  python test-ocr.py 16512            -> เทสเฉพาะพอร์ต 16512
  python test-ocr.py 127.0.0.1:16512  -> เทสเฉพาะเครื่องนี้

สิ่งที่ได้:
  1. ผลอ่าน UID โชว์ในจอ พร้อมชื่อไฟล์ backup ที่จะได้
  2. ภาพเต็มจอ + ภาพ region ที่ใช้อ่าน เซฟไว้ใน test-ocr-output/
     (เปิดดูได้ว่ากรอบครอบตำแหน่ง UID ถูกไหม ถ้าไม่ถูกค่อยขยับ UID_REGION ใน main.py)
"""
import os
import sys

import cv2
import numpy as np
from ppadb.client import Client as AdbClient

from main import read_uid_ocr, UID_REGION

OUT_DIR = "test-ocr-output"


def test_device(device):
    print(f"\n=== เทสเครื่อง {device.serial} ===")
    try:
        cap = device.screencap()
        screen = cv2.imdecode(np.frombuffer(cap, dtype=np.uint8), cv2.IMREAD_COLOR)
        if screen is None:
            print("ถ่ายหน้าจอไม่ได้!")
            return

        x, y, w, h = UID_REGION
        crop = screen[y:y + h, x:x + w]

        os.makedirs(OUT_DIR, exist_ok=True)
        safe_serial = device.serial.replace(":", "_")
        full_path = os.path.join(OUT_DIR, f"{safe_serial}_full.png")
        region_path = os.path.join(OUT_DIR, f"{safe_serial}_region.png")
        cv2.imwrite(full_path, screen)
        cv2.imwrite(region_path, cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
        print(f"เซฟภาพเต็มจอ:  {full_path}")
        print(f"เซฟภาพ region: {region_path}")

        uid = read_uid_ocr(device)
        if uid:
            print(f"ผลอ่าน UID: {uid}  (ยาว {len(uid)} ตัวอักษร)")
            print(f"ชื่อไฟล์ backup ที่จะได้: noradom+[{uid}]+_LINE_COCOS_PREF_KEY.xml")
        else:
            print("อ่าน UID ไม่ได้ - เปิดภาพ region ดูว่าหน้าจอตอนนี้มี UID โชว์ตรงตำแหน่งนั้นจริงไหม")
    except Exception as e:
        print(f"ผิดพลาด: {e}")


def main():
    client = AdbClient(host="127.0.0.1", port=5037)
    devices = client.devices()
    if not devices:
        print("ไม่พบเครื่องที่ต่อ adb อยู่เลย (ลอง adb connect ก่อน)")
        return

    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target and ":" not in target:
        target = f"127.0.0.1:{target}"

    tested = 0
    for d in devices:
        if target is None or d.serial == target:
            test_device(d)
            tested += 1

    if target and tested == 0:
        print(f"ไม่พบเครื่อง {target} ในรายการ adb devices")


if __name__ == "__main__":
    main()
