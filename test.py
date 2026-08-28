import cv2
import numpy as np
from datetime import datetime
import os
import logging

# ตั้งค่าการบันทึกล็อก
logging.basicConfig(
    filename='image_detection.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def setup_directories():
    """สร้างโฟลเดอร์ที่จำเป็นถ้ายังไม่มี"""
    directories = ['img', 'logs']
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            logging.info(f"Created directory: {directory}")

def ImgSearchADB(adb_img_path, find_img_path, threshold=0.95, method=cv2.TM_CCOEFF_NORMED):
    """
    ค้นหาภาพเป้าหมายในภาพหน้าจอ
    """
    try:
        adb_img = cv2.imread(adb_img_path, cv2.IMREAD_COLOR)
        find_img = cv2.imread(find_img_path, cv2.IMREAD_COLOR)

        if adb_img is None:
            logging.error(f"ไม่พบภาพหน้าจอที่: {adb_img_path}")
            return None, None

        if find_img is None:
            logging.error(f"ไม่พบภาพเป้าหมายที่: {find_img_path}")
            return None, None

        needle_w = find_img.shape[1]
        needle_h = find_img.shape[0]

        result = cv2.matchTemplate(adb_img, find_img, method)
        locations = np.where(result >= threshold)
        locations = list(zip(*locations[::-1]))

        rectangles = []
        for loc in locations:
            rect = [int(loc[0]), int(loc[1]), needle_w, needle_h]
            rectangles.append(rect)
            rectangles.append(rect)

        rectangles, _ = cv2.groupRectangles(rectangles, groupThreshold=1, eps=1)
        return rectangles, adb_img

    except Exception as e:
        logging.error(f"เกิดข้อผิดพลาดในการค้นหาภาพ: {str(e)}")
        return None, None

def draw_rectangles(image, rectangles):
    """
    วาดกรอบสี่เหลี่ยมรอบพื้นที่ที่ตรวจพบ
    """
    try:
        line_color = (0, 255, 0)  # BGR format - สีเขียว
        line_thickness = 2

        for (x, y, w, h) in rectangles:
            top_left = (x, y)
            bottom_right = (x + w, y + h)
            cv2.rectangle(image, top_left, bottom_right, line_color, line_thickness)

    except Exception as e:
        logging.error(f"เกิดข้อผิดพลาดในการวาดกรอบ: {str(e)}")

def save_image_with_metadata(image, save_path, user, timestamp):
    """
    บันทึกภาพพร้อมข้อมูล metadata
    """
    try:
        # เพิ่มข้อมูล metadata ลงในภาพ
        font = cv2.FONT_HERSHEY_SIMPLEX
        metadata_text = f"User: {user} | Date: {timestamp}"
        cv2.putText(image, metadata_text, (10, 30), font, 0.7, (255, 255, 255), 2)
        cv2.putText(image, metadata_text, (10, 30), font, 0.7, (0, 0, 0), 1)

        # บันทึกภาพ
        cv2.imwrite(save_path, image)
        logging.info(f"บันทึกภาพสำเร็จที่: {save_path}")
        return True

    except Exception as e:
        logging.error(f"เกิดข้อผิดพลาดในการบันทึกภาพ: {str(e)}")
        return False

def test_image_detection(username="", timestamp=""):
    """
    ทดสอบการตรวจจับภาพและบันทึกผล
    """
    setup_directories()
    
    adb_screen_path = 'img/fixgray.png'
    target_img_path = 'img/fixgray.png'
    
    logging.info(f"เริ่มการค้นหาภาพโดยผู้ใช้: {username}")
    print("🔍 กำลังค้นหาภาพเป้าหมาย...")
    
    rectangles, source_image = ImgSearchADB(adb_screen_path, target_img_path)
    
    if rectangles is not None and len(rectangles) > 0:
        print(f"✅ พบภาพทั้งหมด {len(rectangles)} ตำแหน่ง:")
        for (x, y, w, h) in rectangles:
            center_x = x + w//2
            center_y = y + h//2
            print(f"   📍 ตำแหน่ง (x, y): ({center_x}, {center_y})")
            print(f"   📐 ขนาด (w x h): {w} x {h}")
            logging.info(f"พบภาพที่ตำแหน่ง: ({center_x}, {center_y}) ขนาด: {w}x{h}")
        
        draw_rectangles(source_image, rectangles)
        
        if save_image_with_metadata(source_image, adb_screen_path, username, timestamp):
            print(f"💾 บันทึกภาพผลการตรวจจับทับไฟล์เดิมที่: {adb_screen_path}")
        else:
            print("❌ เกิดข้อผิดพลาดในการบันทึกภาพ")
    else:
        print("❌ ไม่พบภาพเป้าหมาย")
        logging.warning("ไม่พบภาพเป้าหมาย")

if __name__ == '__main__':
    # ใช้ค่าที่ได้รับจากระบบ
    current_user = "leokungYT2"
    current_time = "2025-05-03 10:11:12"
    
    test_image_detection(username=current_user, timestamp=current_time)