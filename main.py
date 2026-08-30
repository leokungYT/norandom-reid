from ppadb.client import Client as AdbClient
from ppadb.device import Device
import cv2
import numpy as np
import os
import time
from datetime import datetime
import getpass
import subprocess
import re
import threading
from typing import List, Tuple
import psutil
import socket
import concurrent.futures
import gc  # Add this with your other imports
import pytesseract
import pyperclip
import json
import glob
import sys
import struct

# กัน print ภาษาไทย crash เวลา stdout ถูก redirect ไปไฟล์/ไปป์ (locale cp1252/874)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# สำหรับแผนสำรองอ่าน UID ผ่าน clipboard (ตอน OCR เฟล) - ต่อคิวทีละเครื่องกันค่าซ้อนกัน
clipboard_lock = threading.Lock()
used_uids = set()

# ทำงานจากโฟลเดอร์ของไฟล์นี้เสมอ - ไม่ว่าจะรันจาก shortcut/โฟลเดอร์ไหน path 'img/...' ก็ต้องเจอ
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ใช้ adb.exe ในโฟลเดอร์บอทเสมอ (adb มักไม่ได้อยู่ใน PATH ของเครื่องฟาร์ม)
ADB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adb.exe")
if not os.path.exists(ADB):
    ADB = "adb"

# รูปสำคัญที่บอทต้องใช้ - เช็คตอนเริ่มว่าโหลดได้จริง (ถ้าโหลดไม่ได้ ImgSearchADB จะเงียบและไม่กดอะไรเลย)
REQUIRED_IMAGES = [
    'img/guestloing.png', 'img/login.png', 'img/checkpoint-click.bmp', 'img/ok.png',
    'img/mainstage.png', 'img/event.png', 'img/cancel.png', 'img/7day.png',
    'img/box3.png', 'img/coyp-id1.bmp', 'img/coyp-id2.bmp', 'img/coyp-id3.bmp', 'img/saveteam.png',
]


def check_required_images():
    """เช็คว่ารูป template สำคัญมีอยู่และเปิดได้ - พิมพ์เตือนชัดๆ ถ้ามีปัญหา"""
    print(f"\n=== เช็ครูป template (โฟลเดอร์ทำงาน: {os.getcwd()}) ===")
    missing = []
    for path in REQUIRED_IMAGES:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            missing.append(path)
            print(f"  [X] โหลดไม่ได้: {path}")
        else:
            print(f"  [OK] {path} ({img.shape[1]}x{img.shape[0]})")
    if missing:
        print(f"!!! รูปหาย/เปิดไม่ได้ {len(missing)} ไฟล์ - บอทจะไม่กดอะไรเลยถ้ารูปพวกนี้ไม่มี !!!")
    else:
        print("รูป template ครบทุกไฟล์")
    return not missing


def debug_match_score(adb_img, find_img_path):
    """คืนค่า match สูงสุด (0-1) ของรูป template บนหน้าจอ - ใช้วินิจฉัยว่าทำไมหาไม่เจอ"""
    try:
        tpl = cv2.imread(find_img_path, cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            return None
        if tpl.shape[0] > adb_img.shape[0] or tpl.shape[1] > adb_img.shape[1]:
            return -1.0  # template ใหญ่กว่าหน้าจอ = ความละเอียดไม่ตรงแน่นอน
        gray = cv2.cvtColor(adb_img, cv2.COLOR_BGR2GRAY) if adb_img.ndim == 3 else adb_img
        return float(cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED).max())
    except Exception:
        return None

# ตั้งค่า Tesseract OCR สำหรับอ่าน UID จากหน้าจอ (แต่ละเครื่องอ่านจอตัวเอง แยกขาดกัน ไม่ใช้ clipboard)
# หา tesseract.exe อัตโนมัติหลายที่ - เครื่องฟาร์มไม่ต้องติดตั้ง/ตั้ง PATH เอง
def _find_tesseract():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "Tesseract-OCR", "tesseract.exe"),   # แถมมากับบอท (ผ่าน autoupdate) - อันหลัก
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\Administrator\Downloads\CookieRun\src\Tesseract-OCR\tesseract.exe",
    ]
    # เช็คไฟล์ตรงๆ ก่อน (bundled อยู่อันแรก - เจอก็จบเร็ว)
    for path in candidates:
        if path and os.path.exists(path):
            return path
    # ไม่เจอ ค่อยลองจาก PATH
    try:
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        found = subprocess.run(["where", "tesseract"], capture_output=True, text=True, timeout=5, **kwargs).stdout.strip().splitlines()
        for f in found:
            if f.strip() and os.path.exists(f.strip()):
                return f.strip()
    except Exception:
        pass
    return None

TESSERACT_PATH = _find_tesseract()
OCR_AVAILABLE = TESSERACT_PATH is not None
if OCR_AVAILABLE:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    print(f"ใช้ Tesseract OCR ที่: {TESSERACT_PATH}")
else:
    print("!!! ไม่พบ Tesseract OCR บนเครื่องนี้ - จะใช้วิธี coyp-id3 (clipboard) อ่าน UID แทน !!!")

# ตำแหน่งข้อความ UID บนหน้าจอหลังกด coyp-id2 (x, y, กว้าง, สูง)
UID_REGION = (392, 238, 209, 43)

# ระยะเวลาระหว่างรอบสแกนรูปภาพ (วินาที) - Main() จะปรับตามจำนวนเครื่องที่เชื่อมต่อ
GLOBAL_SEARCH_INTERVAL = 0.6


# ตารางแปลงตัวอักษรที่ OCR ชอบอ่านสับสน กลับเป็นเลขฐาน 16 (UID เป็น hex ตัวพิมพ์เล็ก)
OCR_NORMALIZE = str.maketrans({'O': '0', 'o': '0', 'Q': '0', 'D': '0',
                               'I': '1', 'l': '1', 'L': '1', '|': '1', '!': '1',
                               'Z': '2', 'z': '2', 'S': '5', 's': '5'})
OCR_WHITELIST = '0123456789abcdefABCDEFoOQDIlL|!zZsS'


def read_uid_ocr(device):
    """อ่าน UID จากหน้าจอของเครื่องนั้นๆ ด้วย OCR ตามตำแหน่ง UID_REGION
    วิธี: แยกตัวอักษรสีเหลืองออกจากพื้นหลัง ตัดทีละตัว แล้ว OCR ทีละตัวอักษร
    (ทดสอบแล้วแม่นกว่าอ่านทั้งบรรทัด ซึ่งชอบตกเลข 1 ท้ายและอ่านเลข 0 เป็นตัว O)"""
    if not OCR_AVAILABLE:
        return None  # ไม่มี Tesseract - ให้ไปใช้ coyp-id3 แทน
    try:
        screen = fast_screencap(device)
        x, y, w, h = UID_REGION
        crop = cv2.resize(screen[y:y + h, x:x + w], None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

        # แยกตัวอักษรสีเหลืองออกจากพื้นน้ำตาล
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (15, 80, 120), (45, 255, 255))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = sorted([cv2.boundingRect(c) for c in cnts if cv2.boundingRect(c)[3] > 20],
                       key=lambda b: b[0])
        if not boxes:
            print(f"Device {device.serial}: OCR ไม่พบตัวอักษรใน region")
            return None

        uid = ''
        for (bx, by, bw, bh) in boxes:
            ch = cv2.copyMakeBorder(255 - mask[by:by + bh, bx:bx + bw],
                                    25, 25, 25, 25, cv2.BORDER_CONSTANT, value=255)
            t = ''
            for psm in (10, 8):
                t = pytesseract.image_to_string(
                    ch, config=f'--psm {psm} -c tessedit_char_whitelist={OCR_WHITELIST}').strip()
                t = re.sub(r'[^0-9a-f]', '', t.translate(OCR_NORMALIZE).lower())
                if t:
                    break
            if not t:
                # อ่านตัวใดตัวหนึ่งไม่ได้ = อย่าเดา คืน None ให้ไปใช้ชื่อไฟล์สำรองแทน
                print(f"Device {device.serial}: OCR อ่านตัวอักษรบางตัวไม่ได้ (ได้แค่ '{uid}')")
                return None
            uid += t[0]

        print(f"Device {device.serial}: ได้ UID จาก OCR: {uid}")
        return uid
    except Exception as e:
        print(f"Device {device.serial}: ข้อผิดพลาด OCR: {e}")
        return None


def copy_uid_via_id3(device, max_find_attempts=15):
    """แผนสำรองเมื่อ OCR อ่านไม่ได้: หาและกดปุ่ม coyp-id3 แล้วอ่าน UID จาก clipboard ของ Windows
    (MuMu sync clipboard มาที่ PC - ใช้ lock ต่อคิวทีละเครื่อง + เช็คค่าซ้ำ กันค่าซ้อนกัน)"""
    copy_pos = None
    for _ in range(max_find_attempts):
        try:
            screen = fast_screencap(device)
            copy_pos = ImgSearchADB(screen, 'img/coyp-id3.bmp')
            if copy_pos:
                break
        except Exception as e:
            print(f"Device {device.serial}: ข้อผิดพลาดในการหา coyp-id3: {e}")
        time.sleep(1)

    if not copy_pos:
        print(f"Device {device.serial}: ไม่พบปุ่ม coyp-id3 บนหน้าจอ")
        return None

    with clipboard_lock:
        for attempt in range(1, 4):
            try:
                pyperclip.copy("")
            except Exception:
                pass
            device.shell(f"input tap {copy_pos[0][0]} {copy_pos[0][1]}")
            time.sleep(2)  # รอ MuMu sync clipboard มาที่ PC
            try:
                value = (pyperclip.paste() or "").strip()
            except Exception:
                value = None

            if not value:
                print(f"Device {device.serial}: clipboard ว่าง (ครั้งที่ {attempt}/3) ลองกด copy ใหม่...")
                continue
            if re.search(r'\s', value) or len(value) > 64:
                print(f"Device {device.serial}: ค่าใน clipboard ผิดรูปแบบ ({value[:40]!r}) ลองกด copy ใหม่...")
                continue
            if value in used_uids:
                print(f"Device {device.serial}: UID {value} ซ้ำกับที่ใช้ไปแล้ว (ค่าค้าง) ลองกด copy ใหม่...")
                continue

            used_uids.add(value)
            print(f"Device {device.serial}: ได้ UID จาก clipboard (coyp-id3): {value}")
            return value

    print(f"Device {device.serial}: อ่าน UID จาก clipboard ไม่สำเร็จ")
    return None

def find_mumu_adb_ports():
    """ค้นหา port ของ MuMu ADB ที่ active อยู่"""
    try:
        # รัน adb devices เพื่อดู list ของ devices ที่เชื่อมต่ออยู่
        result = subprocess.run([ADB, 'devices'], capture_output=True, text=True)
        # แสดงผลลัพธ์ทั้งหมดที่ได้จาก adb devices
        print("ผลลัพธ์จาก adb devices:")
        print(result.stdout)
        
        # ค้นหา pattern 127.0.0.1:port
        ports = re.findall(r'127\.0\.0\.1:(\d+)', result.stdout)
        
        if ports:
            print(f"พบ active ports: {ports}")
        else:
            print("ไม่พบ active ports")
            
        return ports
    except Exception as e:
        print(f"Error finding MuMu ports: {e}")
        return []
def scan_mumu_directory():
    """สแกนหา MuMu directory เพื่อหา config file แบบเร็วขึ้น"""
    common_paths = [
        "F:\\MuMuPlayerGlobal-12.0\\shell",
        "C:\\Program Files\\Netease\\MuMuPlayerGlobal-12.0\\shell",
        "D:\\MuMuPlayerGlobal-12.0\\shell",
        "E:\\MuMuPlayerGlobal-12.0\\shell",  # เพิ่ม path เพื่อครอบคลุมมากขึ้น
        os.path.join(os.environ['LOCALAPPDATA'], "Netease\\MuMuPlayerGlobal-12.0\\shell"),
        os.path.join(os.environ['PROGRAMFILES'], "Netease\\MuMuPlayerGlobal-12.0\\shell"),
        os.path.join(os.environ['PROGRAMFILES(X86)'], "Netease\\MuMuPlayerGlobal-12.0\\shell")
    ]
    
    ports = set()  # ใช้ set เพื่อป้องกันการซ้ำ
    
    for path in common_paths:
        if os.path.exists(path):
            config_files = [f for f in os.listdir(path) if f.endswith('.config')]
            for config_file in config_files:
                try:
                    with open(os.path.join(path, config_file), 'r') as f:
                        content = f.read()
                        port_match = re.search(r'adb_port=(\d+)', content)
                        if port_match:
                            ports.add(port_match.group(1))
                except:
                    continue
    
    return list(ports)
def find_mumu_processes():
    """ค้นหา processes ของ MuMu แบบเร็วขึ้น"""
    mumu_processes = []
    try:
        process_list = subprocess.check_output('tasklist /FI "IMAGENAME eq MuMu*"', shell=True).decode()
        for line in process_list.split('\n'):
            if 'MuMu' in line:
                try:
                    pid = int(re.search(r'\b(\d+)\b', line).group(1))
                    cmd = subprocess.check_output(f'wmic process where ProcessId={pid} get CommandLine', shell=True).decode()
                    port_match = re.search(r'-port (\d+)', cmd)
                    if port_match:
                        mumu_processes.append((pid, port_match.group(1)))
                except:
                    continue
    except:
        pass
    return mumu_processes
def scan_all_possible_ports():
    """สแกนทุก port ที่เป็นไปได้ของ MuMu แบบเร็วขึ้น"""
    all_ports = set()
    base_ports = [16416, 16448, 16480, 16512, 16544, 16576, 16608, 16640, 16672, 16704]  # พอร์ตที่ใช้บ่อย
    
    # สแกนพอร์ตที่ใช้บ่อยก่อน
    for port in base_ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.1)  # ลด timeout
            result = sock.connect_ex(('127.0.0.1', port))
            if result == 0:
                all_ports.add(str(port))
            sock.close()
        except:
            continue
    
    # ตรวจสอบ netstat แบบเร็ว
    try:
        netstat = subprocess.check_output('netstat -an | findstr "16"', shell=True).decode()
        for line in netstat.split('\n'):
            if '127.0.0.1' in line and 'LISTENING' in line:
                port_match = re.search(r':(\d+)', line)
                if port_match:
                    port = port_match.group(1)
                    if port.isdigit() and 16416 <= int(port) <= 18999:
                        all_ports.add(port)
    except:
        pass
    
    return list(all_ports)
def get_next_backup_id():
    """Get the start available backup ID by checking existing files"""
    backup_dir = "backup"
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        
    existing_files = [f for f in os.listdir(backup_dir) if f.startswith("botick-id") and f.endswith(".xml")]
    if not existing_files:
        return 1
        
    highest_id = 0
    for file in existing_files:
        try:
            id_str = file.split("botick-id")[1].split("_")[0]
            highest_id = max(highest_id, int(id_str))
        except:
            continue
            
    return highest_id + 1

def find_mumu_processes() -> List[Tuple[int, str]]:
    """ค้นหา processes ของ MuMu ที่กำลังทำงานและดึง ports ที่ใช้"""
    mumu_processes = []
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                # ค้นหาโปรเซส MuMu จากชื่อที่เป็นไปได้
                if any(mumu_name in proc.info['name'].lower() for mumu_name in ['mumu', 'nemu', 'memu']):
                    cmd = proc.info['cmdline']
                    if cmd:
                        # ค้นหา port จาก command line arguments
                        cmd_str = ' '.join(cmd)
                        port_match = re.search(r'-port (\d+)', cmd_str)
                        if port_match:
                            port = port_match.group(1)
                            mumu_processes.append((proc.info['pid'], port))
                            print(f"Found MuMu process: PID {proc.info['pid']}, Port {port}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        print(f"Error scanning processes: {e}")
    return mumu_processes
def scan_all_possible_ports() -> List[str]:
    """สแกนทุก port ที่เป็นไปได้ของ MuMu (16416-18999)"""
    all_ports = []
    base_port = 16416
    max_port = 19000
    found_ports = 0  # นับจำนวน ports ที่พบ
    max_ports = 50   # จำกัดจำนวน ports ที่จะค้นหา
    
    try:
        print("\nScanning for active MuMu ports...")
        
        # สแกนพอร์ตที่มักใช้บ่อยก่อน
        common_offsets = [0, 32, 64, 96, 128, 160, 192, 224, 256, 288]
        for offset in common_offsets:
            port = base_port + offset
            if found_ports >= max_ports:
                break
                
            try:
                result = subprocess.run(
                    [ADB, "connect", f"127.0.0.1:{port}"],
                    capture_output=True,
                    text=True,
                    timeout=2  # ลด timeout ลง
                )
                
                if "connected" in result.stdout.lower():
                    print(f"Found active port: {port}")
                    all_ports.append(str(port))
                    found_ports += 1
                    
            except subprocess.TimeoutExpired:
                continue
            except Exception:
                continue
            
            time.sleep(0.1)  # ลดเวลารอระหว่างการสแกน
            
    except Exception as e:
        print(f"Error in port scanning: {e}")
    
    return list(set(all_ports))

def scan_ports_from_netstat() -> List[str]:
    """ค้นหา ports ที่ใช้โดย adb จาก netstat"""
    ports = []
    try:
        # ใช้ netstat แบบกำหนดเวลา timeout
        process = subprocess.run(
            'netstat -ano', 
            shell=True, 
            capture_output=True, 
            timeout=5  # เพิ่ม timeout 5 วินาที
        )
        output = process.stdout.decode()
        
        # ค้นหา ports ที่เกี่ยวข้องกับ adb
        for line in output.split('\n'):
            if '127.0.0.1' in line and 'LISTENING' in line:
                match = re.search(r':(\d+)', line)
                if match:
                    port = match.group(1)
                    if 16416 <= int(port) <= 18999:  # กรองเฉพาะช่วง port ที่ต้องการ
                        ports.append(port)
    except subprocess.TimeoutExpired:
        print("Netstat scan timed out")
    except Exception as e:
        print(f"Error scanning netstat: {e}")
    return list(set(ports))



def find_mumu_manager():
    """หา MuMuManager.exe ให้เจอไม่ว่าจะติดตั้ง MuMuPlayer หรือ MuMuPlayerGlobal เวอร์ชันไหน"""
    fixed = [
        r"C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe",
        r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\nx_main\MuMuManager.exe",
        r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\shell\MuMuManager.exe",
    ]
    for p in fixed:
        if os.path.exists(p):
            return p
    # ค้นหาแบบกว้างใน Program Files ทั้งสองที่
    for base in [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]:
        if not base:
            continue
        hits = glob.glob(os.path.join(base, "Netease", "**", "MuMuManager.exe"), recursive=True)
        if hits:
            return hits[0]
    return None


def get_ports_from_mumu_manager():
    """แหล่งที่แม่นสุด: ถาม MuMuManager ว่ามีเครื่องไหนรันอยู่บ้าง + adb_port ของแต่ละเครื่อง"""
    exe = find_mumu_manager()
    if not exe:
        return []
    try:
        res = subprocess.run([exe, "info", "-v", "all"], capture_output=True, text=True, timeout=15)
        data = json.loads(res.stdout)
    except Exception as e:
        print(f"MuMuManager อ่านข้อมูลไม่ได้: {e}")
        return []

    # info อาจคืน dict ของหลายเครื่อง หรือ dict เดียวเมื่อมีเครื่องเดียว
    entries = data.values() if isinstance(data, dict) and not data.get("adb_port") else [data]
    ports = []
    for v in entries:
        if isinstance(v, dict) and v.get("is_android_started") and v.get("adb_port"):
            ports.append(str(v["adb_port"]))
    if ports:
        print(f"MuMuManager พบเครื่องที่รันอยู่ {len(ports)} เครื่อง: {sorted(ports)}")
    return ports


def connect_to_mumu():
    """เชื่อมต่อกับ MuMu Emulator แบบเร็วขึ้น"""
    try:
        print("\n=== เริ่มกระบวนการเชื่อมต่อ MuMu ===")
        
        # รีเซ็ต ADB server อย่างรวดเร็ว
        subprocess.run([ADB, "kill-server"], capture_output=True, timeout=3)
        subprocess.run([ADB, "start-server"], capture_output=True, timeout=3)
        time.sleep(1)
        
        # === วิธีเดียวกับ login.py: brute-force สแกนช่วง port แล้ว adb connect ทุกตัว ===
        # เล็งเฉพาะช่วง MuMu (16384-17416) ที่บอทนี้ใช้ - ไม่แตะช่วง 5555+ กันไปชนบอทอื่น/LDPlayer
        candidate_ports = list(range(16384, 17417))

        # จาก MuMuManager ด้วย (แม่นสุด รวมเข้าไปในชุดที่จะยิงเชื่อม)
        for p in get_ports_from_mumu_manager():
            try:
                candidate_ports.append(int(p))
            except ValueError:
                pass
        candidate_ports = sorted(set(candidate_ports))

        # กรองเร็วด้วย socket ก่อน - เอาเฉพาะ port ที่เปิดฟังจริง (ไม่ต้อง adb connect port ที่ปิด)
        def is_open(port):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.15)
                ok = sock.connect_ex(('127.0.0.1', port)) == 0
                sock.close()
                return port if ok else None
            except Exception:
                return None

        open_ports = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
            for r in executor.map(is_open, candidate_ports):
                if r:
                    open_ports.append(r)

        print(f"\n--- [ADB] สแกนพบ port ที่เปิดอยู่ {len(open_ports)} port: {sorted(open_ports)} ---")

        # ยิง adb connect ทุก port ที่เปิด พร้อมกัน (50 workers แบบ login.py) เช็คคำว่า connected
        adb = AdbClient(host="127.0.0.1", port=5037)

        def try_connect_port(port):
            try:
                addr = f"127.0.0.1:{port}"
                result = subprocess.run([ADB, "connect", addr],
                                        capture_output=True, timeout=5, text=True)
                out = (result.stdout or "").lower()
                if ("connected" in out) and "cannot" not in out:
                    return addr
            except Exception:
                pass
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            list(executor.map(try_connect_port, open_ports))

        # รอให้ทุกเครื่องขึ้นสถานะ device (ไม่ใช่ offline) - retry สูงสุด 5 รอบ + reconnect ตัวที่ยัง offline
        connected_devices = []
        for attempt in range(5):
            connected_devices = []
            offline = []
            for d in adb.devices():
                if "127.0.0.1" not in d.serial:
                    continue
                try:
                    state = d.get_state()
                except Exception:
                    state = "offline"
                if state == "device":
                    connected_devices.append(d)
                else:
                    offline.append(d.serial)
            if not offline:
                break
            print(f"รอเครื่องออนไลน์... (รอบ {attempt + 1}/5) ยัง offline: {offline}")
            for serial in offline:
                try:
                    subprocess.run([ADB, "connect", serial], capture_output=True, timeout=5)
                except Exception:
                    pass
            time.sleep(2)

        print(f"เชื่อมต่อสำเร็จ {len(connected_devices)} เครื่อง: {sorted(d.serial for d in connected_devices)}")

        if connected_devices:
            return adb, connected_devices if len(connected_devices) > 1 else connected_devices[0]
        return None, []
        
    except Exception as e:
        print(f"Error in connect_to_mumu: {e}")
        return None, []

def backup_game_data(device, uid=None):
    """Backup game data with sequential ID naming and detailed logging
    ถ้าส่ง uid มา จะตั้งชื่อไฟล์เป็น noradom+[uid]+_LINE_COCOS_PREF_KEY.xml"""
    try:
        # กำหนดค่าคงที่สำหรับการรอ
        INITIAL_WAIT = 5        # เวลารอก่อนทำ backup
        RESTART_DELAY = 10      # เวลารอหลังจาก backup เสร็จก่อนเริ่มใหม่

        # บันทึกเวลาเริ่มต้น
        current_time = datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')
        print(f"\nDevice {device.serial}: === เริ่มกระบวนการ Backup ===")
        print(f"Device {device.serial}: เวลาเริ่มต้น: {current_time}")
        print(f"Device {device.serial}: ผู้ใช้งาน: {getpass.getuser()}")
        
        # สร้างโฟลเดอร์ backup
        backup_dir = "backup"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            print(f"Device {device.serial}: สร้างโฟลเดอร์ backup เรียบร้อย")
            
        # สร้างชื่อไฟล์ backup
        next_id = get_next_backup_id()
        if uid:
            # ตั้งชื่อตาม UID ที่ copy มาจากเกม เช่น noradom+[409f99e9]+_LINE_COCOS_PREF_KEY.xml
            safe_uid = re.sub(r'[\\/:*?"<>|\s]', '', uid)
            backup_path = f"backup/noradom+[{safe_uid}]+_LINE_COCOS_PREF_KEY.xml"
        else:
            backup_path = f"backup/botick-id{next_id}_LINE_COCOS_PREF_KEY_{current_time}.xml"
        device_id = device.serial
        
        print(f"\nDevice {device.serial}: === ข้อมูล Backup ===")
        print(f"Device {device.serial}: - ID: {next_id}")
        print(f"Device {device.serial}: - Path: {backup_path}")
        print(f"Device {device.serial}: - Device ID: {device_id}")
        
        # ขอสิทธิ์ root และคัดลอกไฟล์
        print(f"\nDevice {device.serial}: กำลังขอสิทธิ์ root เพื่อ copy ไฟล์...")
        try:
            device.shell("su -c 'chmod 777 /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml'")
        except Exception as e:
            print(f"Device {device.serial}: ไม่สามารถขอสิทธิ์ root ได้: {e}")
        
        print(f"\nDevice {device.serial}: กำลังคัดลอกไฟล์...")
        try:
            # ลบไฟล์เก่าถ้ามี
            device.shell("rm /sdcard/temp_backup.xml")
            # คัดลอกไฟล์ใหม่
            device.shell("su -c 'cp /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml /sdcard/temp_backup.xml'")
            device.shell("su -c 'chmod 777 /sdcard/temp_backup.xml'")
            print(f"Device {device.serial}: คัดลอกไฟล์สำเร็จ")
        except Exception as e:
            print(f"Device {device.serial}: ไม่สามารถคัดลอกไฟล์ได้: {e}")
            
        print(f"\nDevice {device.serial}: กำลัง Pull ไฟล์...")
        result = subprocess.run(
            [ADB, "-s", device_id, "pull", "/sdcard/temp_backup.xml", backup_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
        
        # ลบไฟล์ชั่วคราว
        device.shell("rm /sdcard/temp_backup.xml")
        
        # ตรวจสอบผลลัพธ์
        if os.path.exists(backup_path) and os.path.getsize(backup_path) > 0:
            print(f"\nDevice {device.serial}: === Backup สำเร็จ ===")
            print(f"Device {device.serial}: Backup path: {backup_path}")
            print(f"Device {device.serial}: File size: {os.path.getsize(backup_path)} bytes")
            print(f"Device {device.serial}: เวลาเสร็จสิ้น: {datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')}")
            
            print(f"\nDevice {device.serial}: รอ {RESTART_DELAY} วินาทีก่อนเริ่มต้นใหม่...")
            for i in range(RESTART_DELAY, 0, -1):
                print(f"Device {device.serial}: เหลือเวลา {i} วินาที")
                time.sleep(1)
            
            return True
            
        return False
            
    except Exception as e:
        print(f"Device {device.serial}: เกิดข้อผิดพลาดในการ Backup: {e}")
        return False

def limit_cpu_usage():
    try:
        if os.name == 'nt':  # Windows
            import psutil
            p = psutil.Process()
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:  # Linux/Unix
            os.nice(10)
    except Exception as e:
        print(f"Error setting CPU priority: {e}")

class ImageCache:
    def __init__(self, max_size=200, cleanup_interval=600):
        self.cache = {}
        self.max_size = max_size
        self.last_cleanup = time.time()
        self.cleanup_interval = cleanup_interval
        self.access_times = {}  # เพิ่มการติดตามการเข้าถึง
        
    def get_image(self, path):
        current_time = time.time()
        self.access_times[path] = current_time
        
        # ทำความสะอาด cache ตามรอบเวลา
        if current_time - self.last_cleanup > self.cleanup_interval:
            self.cleanup()
        
        if path not in self.cache:
            if len(self.cache) >= self.max_size:
                self.remove_least_used()
            # เก็บ template เป็นภาพขาวดำ - matchTemplate เร็วขึ้น ~3 เท่า (สำคัญมากตอนรันหลายเครื่อง)
            self.cache[path] = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        return self.cache[path]
        
    def remove_least_used(self):
        if not self.access_times:
            return
        oldest_path = min(self.access_times.keys(), 
                         key=lambda k: self.access_times[k])
        del self.cache[oldest_path]
        del self.access_times[oldest_path]
    
    def cleanup(self):
        current_time = time.time()
        expired_paths = [path for path, last_access in self.access_times.items()
                        if current_time - last_access > self.cleanup_interval]
        for path in expired_paths:
            if path in self.cache:
                del self.cache[path]
                del self.access_times[path]
        self.last_cleanup = current_time
        gc.collect()
        
    def clear(self):
        self.cache.clear()
        self.access_times.clear()
        gc.collect()

# สร้าง instance ของ cache
image_cache = ImageCache()

class ScreenCapture:
    def __init__(self, device, min_interval=0.5, max_age=2.0):
        self.device = device
        self.last_capture = None
        self.last_capture_time = 0
        self.min_interval = min_interval
        self.max_age = max_age  # เพิ่มการกำหนดอายุสูงสุดของ cache
        
    def get_screen(self):
        current_time = time.time()
        age = current_time - self.last_capture_time
        
        # ถ้า cache เก่าเกินไปหรือยังไม่มี cache ให้ capture ใหม่
        if self.last_capture is None or age >= self.max_age or age >= self.min_interval:
            try:
                self.last_capture = fast_screencap(self.device)
                self.last_capture_time = current_time
            except Exception as e:
                print(f"Error capturing screen: {e}")
                if self.last_capture is None:
                    raise  # ถ้าไม่มี cache ให้ raise error
        
        return self.last_capture


# แปลงภาพหน้าจอเป็นขาวดำครั้งเดียวต่อรอบ (thread-local: แต่ละเครื่องมีของตัวเอง ไม่ชนกัน)
_gray_tls = threading.local()


def _screen_to_gray(adb_img):
    """cvtColor ภาพหน้าจอเป็นขาวดำ แล้ว cache ไว้ - ถ้าเป็นภาพเดิม (identity) ใช้ซ้ำไม่แปลงใหม่"""
    if getattr(_gray_tls, "color", None) is adb_img and getattr(_gray_tls, "gray", None) is not None:
        return _gray_tls.gray
    gray = cv2.cvtColor(adb_img, cv2.COLOR_BGR2GRAY) if adb_img.ndim == 3 else adb_img
    _gray_tls.color = adb_img
    _gray_tls.gray = gray
    return gray


# === Watchdog: ถ้าเครื่องไหนค้าง/ไม่คืบหน้าเกิน 25 นาที ให้ล้างแอพเริ่มใหม่ตั้งแต่ลบไฟล์ ===
STUCK_TIMEOUT = 1500  # 25 นาที (วินาที)
_last_activity = {}   # serial -> เวลาที่คืบหน้าล่าสุด


class StuckTimeoutError(BaseException):
    """เครื่องค้างเกิน STUCK_TIMEOUT - ต้อง reset ใหม่ทั้งหมด
    (สืบจาก BaseException เพื่อไม่ให้ except Exception ทั่วไปในลูปกลืนทิ้ง - จะลอยขึ้นไปถึง device_worker)"""
    pass


def mark_activity(device):
    """บันทึกว่าเครื่องนี้เพิ่งมีความคืบหน้า (เจอรูป/กดปุ่ม/เริ่มรอบใหม่)"""
    _last_activity[device.serial] = time.time()


def check_stuck(device):
    """เช็คว่าเครื่องค้างเกิน 25 นาทีไหม - ถ้าใช่ raise StuckTimeoutError
    เรียกจาก fast_screencap ซึ่งถูกเรียกทุกเฟส (ทั้งตอน login และตอนเล่น) จึงจับได้ตั้งแต่เริ่ม"""
    last = _last_activity.get(device.serial)
    if last is not None and time.time() - last > STUCK_TIMEOUT:
        raise StuckTimeoutError(f"{device.serial} ค้างเกิน {STUCK_TIMEOUT} วินาที (25 นาที)")


# === เฝ้า checkpoint-click.bmp แบบลอยๆ: ถ้าค้างบนจอต่อเนื่องเกิน 45 วิ ให้เริ่มใหม่ตั้งแต่ลบไฟล์ ===
CHECKPOINT_STUCK_TIMEOUT = 45  # วินาที
_checkpoint_since = {}  # serial -> เวลาที่เริ่มเห็น checkpoint-click ต่อเนื่อง


def check_checkpoint_stuck(device, adb_img):
    """หา checkpoint-click.bmp แบบลอยๆ ทุกครั้ง - ถ้ามันค้างบนจอต่อเนื่องเกิน 45 วิ
    (กดแล้วไม่ยอมหาย = ค้าง) ให้ raise StuckTimeoutError เพื่อ reset ทั้งหมด"""
    try:
        found = ImgSearchADB(adb_img, 'img/checkpoint-click.bmp', threshold=0.9)
    except Exception:
        return
    now = time.time()
    if found:
        first = _checkpoint_since.get(device.serial)
        if first is None:
            _checkpoint_since[device.serial] = now
        elif now - first >= CHECKPOINT_STUCK_TIMEOUT:
            _checkpoint_since[device.serial] = None
            raise StuckTimeoutError(f"{device.serial} checkpoint-click ค้างเกิน {CHECKPOINT_STUCK_TIMEOUT} วินาที")
    elif _checkpoint_since.get(device.serial) is not None:
        _checkpoint_since[device.serial] = None  # ไม่เจอแล้ว - รีเซ็ตตัวจับเวลา


def fast_screencap(device):
    """จับหน้าจอแบบ raw (ไม่ encode PNG) = เร็วกว่ามาก แล้วคืนภาพ BGR (แบบเดียวกับ login.py)
    ถ้า raw ใช้ไม่ได้ fallback ไป PNG/ppadb ให้เอง"""
    check_stuck(device)  # จับเครื่องค้าง 25 นาที (ทำงานทุกเฟส เพราะ fast_screencap ถูกเรียกทุกที่)
    try:
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            [ADB, "-s", device.serial, "exec-out", "screencap"],
            capture_output=True, timeout=10, **kwargs
        )
        data = result.stdout
        if result.returncode == 0 and len(data) >= 16:
            w, h, _ = struct.unpack("<III", data[:12])
            if 0 < w <= 4096 and 0 < h <= 4096:
                header = len(data) - w * h * 4
                if header in (12, 16):
                    rgba = np.frombuffer(data[header:header + w * h * 4], np.uint8).reshape((h, w, 4))
                    return np.ascontiguousarray(rgba[:, :, [2, 1, 0]])  # RGBA -> BGR
            # เผื่อบาง emulator ส่ง PNG มา
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                return img
    except Exception as e:
        print(f"fast_screencap error {device.serial}: {e}")
    # ทางสำรองสุดท้าย: ppadb screencap (PNG)
    try:
        cap = device.screencap()
        return cv2.imdecode(np.frombuffer(cap, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


# จำตำแหน่งที่เคยเจอรูปแต่ละอัน (UI เกมอยู่ตำแหน่งเดิมเสมอ) - รอบต่อไปเช็คบริเวณเล็กๆ ก่อน = เร็วขึ้นมาก
_pos_memory = {}


def clear_all_state():
    """ล้าง cache/สถานะที่จำไว้ทั้งหมด เริ่มรอบใหม่แบบสะอาด กันค่าเก่าจากบัญชีก่อนหน้าค้าง"""
    try:
        _pos_memory.clear()                    # ลืมตำแหน่งเก่า - สแกนหาใหม่หมด
        _gray_tls.__dict__.clear()             # ล้าง cache ภาพขาวดำของ thread นี้
        try:
            image_cache.access_times.clear()   # รีเซ็ตสถิติการใช้ template
        except Exception:
            pass
        gc.collect()                            # คืน memory
        print("ล้าง cache/สถานะทั้งหมดแล้ว - เริ่มรอบใหม่สะอาด")
    except Exception as e:
        print(f"ล้าง state ไม่สำเร็จ: {e}")


def ImgSearchADB(adb_img, find_img_path, threshold=0.95, method=cv2.TM_CCOEFF_NORMED):
    try:
        find_img = image_cache.get_image(find_img_path)  # ใช้ cache แทน (เป็นภาพขาวดำแล้ว)
        if find_img is None:
            return None

        gray_screen = _screen_to_gray(adb_img)
        needle_h, needle_w = find_img.shape[:2]
        H, W = gray_screen.shape[:2]

        # เช็คบริเวณที่จำไว้ก่อน (ROI เล็กๆ รอบตำแหน่งเดิม) - ถ้าเจอ ไม่ต้องสแกนเต็มจอ
        remembered = _pos_memory.get(find_img_path)
        if remembered is not None:
            rx, ry = remembered
            pad = 6
            x0 = max(0, rx - pad); y0 = max(0, ry - pad)
            x1 = min(W, rx + needle_w + pad); y1 = min(H, ry + needle_h + pad)
            roi = gray_screen[y0:y1, x0:x1]
            if roi.shape[0] >= needle_h and roi.shape[1] >= needle_w:
                _, maxv, _, maxloc = cv2.minMaxLoc(cv2.matchTemplate(roi, find_img, method))
                if maxv >= threshold:
                    return [(x0 + maxloc[0] + needle_w // 2, y0 + maxloc[1] + needle_h // 2)]

        result = cv2.matchTemplate(gray_screen, find_img, method)
        # จำตำแหน่งที่ดีที่สุด (top-left) ไว้ใช้รอบหน้า
        _, best_v, _, best_loc = cv2.minMaxLoc(result)
        if best_v >= threshold:
            _pos_memory[find_img_path] = (best_loc[0], best_loc[1])
        locations = np.where(result >= threshold)
        locations = list(zip(*locations[::-1]))
        rectangles = []
        for loc in locations:
            rect = [int(loc[0]), int(loc[1]), needle_w, needle_h]
            rectangles.append(rect)
            rectangles.append(rect)
        rectangles, _ = cv2.groupRectangles(rectangles, groupThreshold=1, eps=1)
        points = []
        if len(rectangles):
            for (x, y, w, h) in rectangles:
                center_x = x + int(w/2)
                center_y = y + int(h/2)
                points.append((center_x, center_y))
        if len(points) > 0:
            return points
        return None
    except Exception as e:
        print(f"Error in ImgSearchADB for {find_img_path}: {e}")
        return None


def perform_sing_actions(device):
    """ฟังก์ชันสำหรับดำเนินการหลังจากคลิกรูป sing.png"""
    try:
        print(f"\nDevice {device.serial}: === เริ่มกระบวนการ Sing ===")
        print(f"Time: 2025-05-06 17:41:50")
        print(f"User: leokungYT2")
        time.sleep(3)  # เพิ่มการรอให้นานขึ้น

        def check_and_click_ok(device, message, max_attempts=3):
            """ฟังก์ชันตรวจสอบและคลิก ok.png แบบมีการลองซ้ำ"""
            for attempt in range(max_attempts):
                try:
                    print(f"Device {device.serial}: กำลังตรวจสอบ ok.png ({message}) ครั้งที่ {attempt + 1}/{max_attempts}")
                    adb_img = fast_screencap(device)
                    pos_ok = ImgSearchADB(adb_img, 'img/ok.png')
                    if pos_ok:
                        print(f"Device {device.serial}: พบ ok.png {message}")
                        device.shell(f"input tap {pos_ok[0][0]} {pos_ok[0][1]}")
                        time.sleep(2)  # เพิ่มการรอหลังจากคลิก
                        return True
                    time.sleep(1)  # รอระหว่างการลองใหม่
                except Exception as e:
                    print(f"Device {device.serial}: ข้อผิดพลาดในการตรวจสอบ ok.png: {e}")
            return False

        # รอ guestlogin.png
        print(f"\nDevice {device.serial}: === เริ่มรอ Guest Login ===")
        retry_count = 0
        max_retries = 30  # กำหนดจำนวนครั้งสูงสุดในการรอ

        while retry_count < max_retries:
            try:
                print(f"Device {device.serial}: กำลังค้นหา guestlogin.png (พยายามครั้งที่ {retry_count + 1}/{max_retries})")
                adb_img = fast_screencap(device)

                # ใช้ threshold 0.9 (ปุ่ม Guest Login เด่นมาก) เผื่อเครื่องอื่นเรนเดอร์ต่างกันเล็กน้อย
                pos_guest = ImgSearchADB(adb_img, 'img/guestloing.png', threshold=0.9)
                if pos_guest:
                    print(f"\nDevice {device.serial}: === พบ Guest Login กดเลย ===")
                    device.shell(f"input tap {pos_guest[0][0]} {pos_guest[0][1]}")
                    time.sleep(3)
                    check_and_click_ok(device, "หลังกด Guest Login")

                    # ถ่ายภาพหน้าจอใหม่เพื่อค้นหา login.png
                    adb_img = fast_screencap(device)

                # ค้นหา login.png จากภาพล่าสุด
                print(f"Device {device.serial}: กำลังค้นหา login.png...")
                pos_login = ImgSearchADB(adb_img, 'img/login.png', threshold=0.9)
                if pos_login:
                    print(f"\nDevice {device.serial}: === เริ่มขั้นตอน Login ===")
                    device.shell(f"input tap {pos_login[0][0]} {pos_login[0][1]}")
                    time.sleep(3)

                    # รอเรื่อยๆ จนเจอ checkpoint-click แล้วค่อยคลิก
                    checkpoint_attempt = 0
                    while True:
                        checkpoint_attempt += 1
                        print(f"Device {device.serial}: กำลังรอ checkpoint-click (ครั้งที่ {checkpoint_attempt})")
                        adb_img = fast_screencap(device)
                        # ค้างที่ checkpoint เกิน 45 วิ (กดแล้วไม่หาย) -> เริ่มใหม่ตั้งแต่ลบไฟล์
                        check_checkpoint_stuck(device, adb_img)
                        pos_checkpoint = ImgSearchADB(adb_img, 'img/checkpoint-click.bmp')
                        if pos_checkpoint:
                            print(f"\nDevice {device.serial}: === พบ checkpoint-click กดเลย ===")
                            device.shell(f"input tap {pos_checkpoint[0][0]} {pos_checkpoint[0][1]}")
                            time.sleep(2)
                            break
                        time.sleep(2)

                    # ทำการ login ตามขั้นตอน
                    login_steps = [
                        ("input tap 928 137", 2),
                        ("input tap 927 253", 2),
                        ("input tap 928 331", 2),
                        ("input tap 419 486", 2),
                        ("input keyevent KEYCODE_BACK", 10),
                        ("input tap 534 500", 2)
                    ]

                    for step_num, (command, delay) in enumerate(login_steps, 1):
                        print(f"Device {device.serial}: ขั้นตอน Login ที่ {step_num}/6")
                        device.shell(command)
                        time.sleep(delay)
                        # ตรวจสอบ ok.png หลังแต่ละขั้นตอน
                        check_and_click_ok(device, f"ระหว่าง login ขั้นตอนที่ {step_num}")

                    print(f"\nDevice {device.serial}: === Login เสร็จสมบูรณ์ ===")
                    print(f"Time: 2025-05-06 17:41:50")
                    return True

                retry_count += 1

                # วินิจฉัยทุก 5 ครั้งที่หาไม่เจอ: บอกความละเอียดจอ + คะแนน match + เซฟภาพไว้ดู
                if retry_count % 5 == 0:
                    h, w = adb_img.shape[:2]
                    sg = debug_match_score(adb_img, 'img/guestloing.png')
                    sl = debug_match_score(adb_img, 'img/login.png')
                    fmt = lambda s: "โหลดรูปไม่ได้" if s is None else ("รูปใหญ่กว่าจอ" if s < 0 else f"{s:.2f}")
                    print(f"Device {device.serial}: [วินิจฉัย] จอ {w}x{h} (ต้องเป็น 960x540) | "
                          f"match guestlogin={fmt(sg)} login={fmt(sl)} (ต้อง >= 0.90)")
                    try:
                        os.makedirs("debug", exist_ok=True)
                        dbg_path = os.path.join("debug", f"{device.serial.replace(':', '_')}_guestlogin_miss.png")
                        cv2.imwrite(dbg_path, adb_img)
                        print(f"Device {device.serial}: [วินิจฉัย] เซฟภาพหน้าจอไว้ที่ {dbg_path}")
                    except Exception:
                        pass

                time.sleep(2)  # เพิ่มการรอระหว่างการลองใหม่

            except Exception as e:
                print(f"Device {device.serial}: ข้อผิดพลาด: {e}")
                retry_count += 1
                time.sleep(2)
                continue

        print(f"Device {device.serial}: ไม่สามารถพบ guestlogin.png หลังจากพยายาม {max_retries} ครั้ง")
        return False
        
    except Exception as e:
        print(f"\nDevice {device.serial}: === เกิดข้อผิดพลาด ===")
        print(f"Error: {e}")
        print(f"Time: 2025-05-06 17:41:50")
        return False



def open_app(device, max_attempts=5):
    """เปิดแอป LINE Rangers ด้วย am start / monkey สลับกัน แล้วเช็ค pidof ว่าเปิดติดจริง (แบบเดียวกับ login.py ของ LGR)"""
    # เช็คครั้งเดียวว่าเกมติดตั้งอยู่ไหม - ถ้าไม่ติดตั้งจะ retry กี่ครั้งก็เปิดไม่ได้
    try:
        pm_out = device.shell("pm list packages com.linecorp.LGRGS") or ""
        if "com.linecorp.LGRGS" not in pm_out:
            print(f"Device {device.serial}: ⛔ ไม่พบแอป com.linecorp.LGRGS บนเครื่องนี้! (ยังไม่ได้ติดตั้ง/ชื่อ package ไม่ตรง)")
            return False
    except Exception as e:
        print(f"Device {device.serial}: [WARN] เช็ค package ไม่ได้: {e} - ลองเปิดต่อ")

    for attempt in range(1, max_attempts + 1):
        try:
            # สลับวิธีเปิด: am start กับ monkey
            if attempt % 2 == 1:
                launch_out = device.shell("am start -S -n com.linecorp.LGRGS/.LineRangersAdr")
            else:
                launch_out = device.shell("monkey -p com.linecorp.LGRGS -c android.intent.category.LAUNCHER 1")
            time.sleep(3)

            # ตรวจว่าแอปยังรันอยู่ด้วย pidof
            pid = (device.shell("pidof com.linecorp.LGRGS") or "").strip()
            if pid:
                print(f"Device {device.serial}: ✓ เปิดแอพติดแล้ว (PID: {pid}) - ครั้งที่ {attempt}")
                return True

            launch_msg = (launch_out or "").strip().replace("\n", " | ")
            print(f"Device {device.serial}: ✗ แอพเปิดไม่ติด (ครั้งที่ {attempt}) ลองใหม่... | สาเหตุจาก launch: {launch_msg[:250] or '(ไม่มี output)'}")
            time.sleep(2)

        except Exception as e:
            print(f"Device {device.serial}: ข้อผิดพลาดในการเปิดแอพ (ครั้งที่ {attempt}): {e}")
            time.sleep(2)

    print(f"Device {device.serial}: เปิดแอพไม่สำเร็จหลังลอง {max_attempts} ครั้ง!")
    return False


def reset_app_and_login(device, clear_app_wait=5):
    """ปิดแอพ -> ลบข้อมูลภายในแอพ (เก็บทรัพยากรเกม 1.5GB ใน /sdcard ไว้) -> เปิดแอพใหม่ -> หา guestlogin
    ถ้าหา guestlogin ไม่เจอเกินกำหนด (30 ครั้ง) จะปิดแอพแล้วเริ่มใหม่ตั้งแต่ลบไฟล์ วนจนกว่าจะสำเร็จ"""
    cycle = 0
    while True:
        cycle += 1
        mark_activity(device)  # เริ่มรอบใหม่ = มีความคืบหน้า (รีเซ็ตนาฬิกา watchdog 25 นาที)
        # ล้างค่าที่จำไว้ทั้งหมดก่อนเริ่มรอบใหม่ (ตำแหน่ง, cache, memory)
        clear_all_state()
        print(f"\nDevice {device.serial}: === เริ่มกระบวนการลบข้อมูลภายในแอพ (รอบที่ {cycle}) ===")
        try:
            print(f"Device {device.serial}: [1/3] กำลังปิดแอพ...")
            device.shell("am force-stop com.linecorp.LGRGS")
            time.sleep(2)

            print(f"Device {device.serial}: [2/3] กำลังลบข้อมูลภายในแอพ (ไม่แตะทรัพยากรเกม 1.5GB)...")
            device.shell("su -c 'rm -rf /data/data/com.linecorp.LGRGS/shared_prefs /data/data/com.linecorp.LGRGS/files /data/data/com.linecorp.LGRGS/databases /data/data/com.linecorp.LGRGS/no_backup /data/data/com.linecorp.LGRGS/app_webview /data/data/com.linecorp.LGRGS/app_pccache /data/data/com.linecorp.LGRGS/app_tmppccache /data/data/com.linecorp.LGRGS/app_textures /data/data/com.linecorp.LGRGS/cache /data/data/com.linecorp.LGRGS/code_cache'")  # ลบข้อมูลภายในทั้งหมด แต่เก็บทรัพยากรเกม 1.5GB ใน /sdcard ไว้
            print(f"Device {device.serial}: ลบข้อมูลภายในแอพเสร็จสิ้น (logout แล้ว)")

            print(f"Device {device.serial}: รอ {clear_app_wait} วินาทีก่อนเริ่มต่อ...")
            for i in range(clear_app_wait, 0, -1):
                print(f"Device {device.serial}: เหลือเวลา {i} วินาที")
                time.sleep(1)

            print(f"Device {device.serial}: [3/3] กำลังเปิดแอพใหม่ (แบบ login.py)...")
            open_app(device)
            time.sleep(5)

            # ค้นหา guestlogin.png ทันทีตั้งแต่เปิดแอพ
            if perform_sing_actions(device):
                return True

            print(f"Device {device.serial}: หา guestlogin ไม่เจอเกินกำหนด - ปิดแอพแล้วเริ่มใหม่ตั้งแต่ลบไฟล์...")
        except Exception as e:
            print(f"Device {device.serial}: ข้อผิดพลาดในกระบวนการรีเซ็ตแอพ: {e}")
            time.sleep(3)


def device_worker(device):
    """Worker function for handling device automation"""
    mark_activity(device)  # arm watchdog 25 นาที ตั้งแต่วินาทีแรกที่บอทเริ่มทำงาน
    last_memory_cleanup = time.time()
    last_image_cleanup = time.time()
    MEMORY_CLEANUP_INTERVAL = 300  # ทำความสะอาด memory ทุก 5 นาที
    IMAGE_CLEANUP_INTERVAL = 300   # ทำความสะอาด image cache ทุก 5 นาที (รูป template ไม่เคยเปลี่ยน ไม่ต้องล้างบ่อย)
    while True:  # เพิ่ม loop หลักเพื่อทำงานต่อเนื่อง
        try:
            # (ตัด thread ตรวจสีหน้าจอแยกออก - loop หลักเช็คจอเทาอยู่แล้ว
            #  thread เดิมถ่ายภาพหน้าจอซ้ำซ้อนทุกวินาทีและเพิ่มขึ้นเรื่อยๆ ทุกรอบ ทำให้บอทหน่วง)
            limit_cpu_usage()
            
            # ค่าคงที่สำหรับการตั้งค่าเวลา
            SEARCH_INTERVAL = GLOBAL_SEARCH_INTERVAL  # ระยะห่างระหว่างการค้นหารูปภาพ (ปรับตามจำนวนเครื่อง)
            CLICK_DELAY = 0     # ดีเลย์หลังการคลิก
            BOX3_WAIT = 5         # เวลารอหลังคลิก box3
            CLEAR_APP_WAIT = 5   # เวลารอหลังการ Clear App
            EVENT_WAIT = 15       # เวลารอสำหรับ event.png
            FIXBACK_WAIT = 5      # เวลารอสำหรับ fixback.png
            FIXBUG_WAIT = 30      # เวลารอสำหรับ fixbugicon

            print(f"\n=== เริ่มกระบวนการทำงาน ===")
            print(f"Device: {device.serial}")
            print(f"Time: 2025-05-02 13:03:26")
            print(f"User: leokungYT")

            # ขั้นตอนแรก: ลบข้อมูลภายในแอพ + เปิดแอพ + หา guestlogin
            # (ถ้าหา guestlogin เกิน 30 ครั้งไม่เจอ จะปิดแอพแล้วเริ่มใหม่ตั้งแต่ลบไฟล์เอง)
            try:
                reset_app_and_login(device, CLEAR_APP_WAIT)
            except Exception as e:
                print(f"Device {device.serial}: เกิดข้อผิดพลาดในการลบข้อมูลภายในแอพ: {e}")
                print("ดำเนินการต่อ...")

            # ตัวแปรสำหรับการติดตามสถานะ
            last_image_found_time = time.time()
            no_image_timeout = 1500  # ไม่พบรูปภาพเกิน 1500 วินาที (25 นาที) ค่อยเริ่มใหม่ตั้งแต่ลบไฟล์
            mainstage_attempts = 0
            max_mainstage_attempts = 10
                                # เพิ่มตัวแปรด้านบนของฟังก์ชัน device_worker
            gray_screen_start_time = None  # เวลาที่เริ่มเจอหน้าจอสีเทา
            GRAY_SCREEN_TIMEOUT = 5  # ระยะเวลาที่ยอมให้หน้าจอค้างสีเทา (วินาที)
            sequence_complete = False
            fixbug_start_time = None
            fixback_start_time = None
            in_sequence_mode = False
            event_start_time = None
            event_found_continuously = False
            check_fixback = False
            tried_mainstage = False

            # รายการรูปภาพที่ต้องตรวจสอบ
            mainstage_path = 'img/mainstage.png'
            sequence_images = [
                'img/7day.png', 'img/7day1.png', 'img/7day2.png',
                'img/event.png', 'img/box1.png',
                'img/box2.png', 'img/box3.png', 'img/ok.png', 'img/event.png'
            ]

            image_list = [
                'img/fixid.png',  # เพิ่มการตรวจสอบ fixid
                'img/steage2.png', 'img/icon.png', 'img/sing.png', 'img/play.png',
                'img/skip.png', 'img/ok.png', 'img/gachaok.png', 'img/au1.png',
                'img/clearstage1.png', 'img/clearstage2.png', 'img/clearstage3.png',
                'img/clearstage4.png', 'img/clearstage5.png', 'img/gacha.png', 
                'img/gacha1.png', 'img/gacha2.png', 'img/gototeam.png',
                'img/gototeam1.png', 'img/guestloing.png', 'img/hero1.png', 
                'img/hero2.png', 'img/hero3.png', 'img/hero4.png', 'img/herodrag.png', 
                'img/herodrag1.png', 'img/nextstage1-1.png', 'img/nextstage1.png', 
                'img/stageok.png', 'img/start.png', 'img/heroo1.png', 
                'img/heroo2.png', 'img/heroo3.png', 'img/heroo4.png', 'img/steage1.png', 
                'img/okwhite.png', 'img/okgust.png', 'img/fixnet.png', 'img/saveteam.png',
                'img/enter1.png', 'img/enter2.png', 'img/enter3.png', 'img/enter4.png',
                'img/enter5.png', 'img/enter6.png', 'img/enter7.png', 'img/enter8.png',
                'img/enter9.png', 'img/enter10.png', 'img/enter11.png', 'img/enter12.png',
                'img/enter13.png', 'img/save.png', 'img/waitsteplogin1.png'
            ]

            print(f"\nDevice {device.serial}: === เริ่มการตรวจจับรูปภาพ ===")





            while True:
                try:
                    # ถ่ายภาพหน้าจอสำหรับตรวจจับรูปภาพ (ประมวลผลทันที ไม่รอให้ภาพเก่า)
                    adb_img = fast_screencap(device)
                    found_any_image = False

                    # หา checkpoint-click แบบลอยๆ ทุกครั้ง - ค้างเกิน 45 วิ ให้เริ่มใหม่ตั้งแต่ลบไฟล์
                    check_checkpoint_stuck(device, adb_img)

                    # ในส่วนของการตรวจสอบสีหน้าจอ:
                    screen_percentage, is_gray_screen = check_screen_color(adb_img)

                    current_time = time.time()
                    
                    # ทำความสะอาด memory ตามรอบเวลา
                    if current_time - last_memory_cleanup > MEMORY_CLEANUP_INTERVAL:
                        gc.collect()
                        last_memory_cleanup = current_time
                    
                    # ทำความสะอาด image cache ตามรอบเวลา
                    if current_time - last_image_cleanup > IMAGE_CLEANUP_INTERVAL:
                        image_cache.clear()
                        last_image_cleanup = current_time

                    if is_gray_screen:  # ถ้าเกิน 80%
                        if gray_screen_start_time is None:
                            gray_screen_start_time = time.time()
                            print(f"Device {device.serial}: เริ่มจับเวลาหน้าจอสีเทา...")
                        else:
                            elapsed_time = time.time() - gray_screen_start_time
                            remaining_time = GRAY_SCREEN_TIMEOUT - elapsed_time
                            print(f"Device {device.serial}: หน้าจอสีเทาค้าง {elapsed_time:.1f} วินาที (เหลือ {remaining_time:.1f} วินาที)")

                            if elapsed_time >= GRAY_SCREEN_TIMEOUT:
                                print(f"\nDevice {device.serial}: === หน้าจอสีเทาค้างเกิน {GRAY_SCREEN_TIMEOUT} วินาที ===")
                                print(f"Device {device.serial}: {screen_percentage:.2f}% เริ่มรีสตาร์ทแอพ...")
                                
                                device.shell("am force-stop com.linecorp.LGRGS")
                                time.sleep(2)
                                open_app(device)
                                time.sleep(5)
                                
                                gray_screen_start_time = None
                                continue
                    else:
                        if gray_screen_start_time is not None:
                            print(f"Device {device.serial}: หน้าจอสีเทาหายไป รีเซ็ตตัวจับเวลา")
                            gray_screen_start_time = None

                    # ตรวจสอบ clearstage4 ก่อนเป็นอันดับแรก
                    pos_clearstage4 = ImgSearchADB(adb_img, 'img/clearstage4.png')
                    if pos_clearstage4:
                        found_any_image = True
                        last_image_found_time = time.time()
                        print(f"\nDevice {device.serial}: === พบ clearstage4.png ===")
                        
                        print(f"Device {device.serial}: [1/3] Clear App...")
                        device.shell("am force-stop com.linecorp.LGRGS")
                        time.sleep(2)
                        
                        print(f"Device {device.serial}: [2/3] รอ {CLEAR_APP_WAIT} วินาที...")
                        for i in range(CLEAR_APP_WAIT, 0, -1):
                            print(f"Device {device.serial}: เหลือเวลา {i} วินาที")
                            time.sleep(1)
                        
                        print(f"Device {device.serial}: [3/3] เปิดแอพใหม่...")
                        open_app(device)
                        time.sleep(10)

                        # เริ่มค้นหา event.png
                        print(f"Device {device.serial}: เริ่มค้นหา event.png...")
                        event_start_time = None
                        event_found_continuously = False
                        back_pressed = False

                        while True:
                            try:
                                current_img = fast_screencap(device)
                                pos = ImgSearchADB(current_img, 'img/event.png')
                                
                                if pos:
                                    found_any_image = True
                                    last_image_found_time = time.time()
                                    if event_start_time is None:
                                        event_start_time = time.time()
                                        print(f"Device {device.serial}: เริ่มจับเวลา event.png...")
                                    elif time.time() - event_start_time >= EVENT_WAIT:
                                        if not event_found_continuously:
                                            print(f"Device {device.serial}: เริ่มคลิก event.png...")
                                            event_found_continuously = True
                                        
                                        print(f"Device {device.serial}: คลิก event.png...")
                                        device.shell(f"input tap {pos[0][0]} {pos[0][1]}")
                                        time.sleep(2)
                                        
                                        # เริ่มกดปุ่ม BACK รัวๆ - ระหว่างกดถ้าเจอ event.png ให้คลิกเลย
                                        # หยุดเมื่อเจอ mainstage.png แล้วค่อยเริ่มทำงาน 7day
                                        print(f"Device {device.serial}: เริ่มกดปุ่ม BACK รัวๆ (รอจนเจอ mainstage.png)...")
                                        back_count = 0
                                        max_back_presses = 100  # กันลูปค้าง
                                        back_done = False

                                        while back_count < max_back_presses:
                                            back_count += 1
                                            print(f"Device {device.serial}: กดปุ่ม BACK ครั้งที่ {back_count}")
                                            device.shell("input keyevent KEYCODE_BACK")

                                            try:
                                                check_img = fast_screencap(device)

                                                # เจอ mainstage.png = ถึงหน้าหลักแล้ว หยุดกด BACK แล้วไปเริ่ม 7day
                                                pos_mainstage_check = ImgSearchADB(check_img, mainstage_path)
                                                if pos_mainstage_check:
                                                    print(f"Device {device.serial}: เจอ mainstage.png หยุดกด BACK เริ่มทำงาน 7day")
                                                    back_done = True
                                                    break

                                                # เจอ cancel.png ให้กดแล้วกด BACK ต่อ (ไม่หยุด)
                                                cancel_pos = ImgSearchADB(check_img, 'img/cancel.png')
                                                if cancel_pos:
                                                    print(f"Device {device.serial}: พบ cancel.png กดแล้ว BACK ต่อ")
                                                    device.shell(f"input tap {cancel_pos[0][0]} {cancel_pos[0][1]}")

                                                # หา event.png ไปด้วยระหว่างกด BACK - เจอแล้วคลิกเลย
                                                event_pos = ImgSearchADB(check_img, 'img/event.png')
                                                if event_pos:
                                                    print(f"Device {device.serial}: เจอ event.png ระหว่างกด BACK คลิกเลย")
                                                    device.shell(f"input tap {event_pos[0][0]} {event_pos[0][1]}")
                                                    time.sleep(1)
                                            except Exception as e:
                                                print(f"Device {device.serial}: ข้อผิดพลาดระหว่างกด BACK: {e}")

                                        if back_done:
                                            back_pressed = True
                                            print(f"Device {device.serial}: เสร็จสิ้นการกดปุ่ม BACK (กดไป {back_count} ครั้ง)")
                                            print(f"Device {device.serial}: เริ่มค้นหา sequence_images...")
                                            break

                                        # กดครบเพดานแล้วยังไปต่อไม่ได้ - หยุดแล้วกลับไปหา event ใหม่อีกรอบ
                                        print(f"Device {device.serial}: กด BACK ครบ {max_back_presses} ครั้งแล้วยังไปต่อไม่ได้ กลับไปหา event ใหม่...")
                                        event_start_time = None
                                        event_found_continuously = False
                                        continue
                                    else:
                                        remaining = EVENT_WAIT - (time.time() - event_start_time)
                                        print(f"Device {device.serial}: รอ event.png... ({int(remaining)} วินาที)")
                                else:
                                    if event_found_continuously and back_pressed:
                                        print(f"Device {device.serial}: เริ่มค้นหา sequence_images...")
                                        break
                                    event_start_time = None
                                    event_found_continuously = False
                                
                            except Exception as e:
                                print(f"Device {device.serial}: ข้อผิดพลาด event.png: {e}")
                            time.sleep(SEARCH_INTERVAL)

                        # ดำเนินการตามลำดับรูปภาพ sequence_images
                        for seq_img in sequence_images:
                            while True:
                                try:
                                    current_img = fast_screencap(device)
                                    pos = ImgSearchADB(current_img, seq_img)
                                    
                                    if pos:
                                        found_any_image = True
                                        last_image_found_time = time.time()
                                        print(f"Device {device.serial}: พบ {seq_img}")
                                        
                                        if seq_img == 'img/box3.png':
                                            print(f"\nDevice {device.serial}: === เริ่มกระบวนการ box3 ===")
                                            print(f"Device {device.serial}: คลิก box3.png")
                                            device.shell(f"input tap {pos[0][0]} {pos[0][1]}")
                                            time.sleep(5)

                                            # กด ESC (BACK) รัวๆ จนกว่าจะเจอ cancel.png ค่อยหยุด
                                            print(f"Device {device.serial}: เริ่มกด ESC รัวๆ จนกว่าจะเจอ cancel.png...")
                                            esc_count = 0
                                            max_esc_presses = 100  # กันลูปค้าง
                                            while esc_count < max_esc_presses:
                                                esc_count += 1
                                                print(f"Device {device.serial}: กด ESC ครั้งที่ {esc_count}")
                                                device.shell("input keyevent KEYCODE_BACK")
                                                try:
                                                    check_img = fast_screencap(device)
                                                    cancel_pos = ImgSearchADB(check_img, 'img/cancel.png')
                                                    if cancel_pos:
                                                        print(f"Device {device.serial}: พบ cancel.png หลังกด ESC {esc_count} ครั้ง หยุดกด")
                                                        device.shell(f"input tap {cancel_pos[0][0]} {cancel_pos[0][1]}")
                                                        time.sleep(2)
                                                        break
                                                except Exception as e:
                                                    print(f"Device {device.serial}: ข้อผิดพลาดระหว่างกด ESC: {e}")

                                            # ทำงานตามลำดับ coyp-id1 -> coyp-id2 แล้วอ่าน UID ด้วย OCR
                                            copied_uid = None
                                            copy_sequence = ['img/coyp-id1.bmp', 'img/coyp-id2.bmp']
                                            for copy_img in copy_sequence:
                                                copy_found = False
                                                for copy_attempt in range(30):  # รอรูปละไม่เกิน 30 รอบ
                                                    try:
                                                        copy_screen = fast_screencap(device)
                                                        copy_pos = ImgSearchADB(copy_screen, copy_img)
                                                        if copy_pos:
                                                            print(f"Device {device.serial}: พบ {copy_img} กดเลย")
                                                            device.shell(f"input tap {copy_pos[0][0]} {copy_pos[0][1]}")
                                                            if copy_img == 'img/coyp-id2.bmp':
                                                                # หลังกด coyp-id2 รอ 5 วิ แล้วอ่าน UID จากหน้าจอด้วย OCR
                                                                print(f"Device {device.serial}: รอ 5 วินาทีก่อนอ่าน UID ด้วย OCR...")
                                                                time.sleep(5)
                                                                copied_uid = read_uid_ocr(device)
                                                                if not copied_uid:
                                                                    # OCR เฟล - ใช้วิธีกด coyp-id3 อ่านจาก clipboard แทน
                                                                    print(f"Device {device.serial}: OCR เฟล เปลี่ยนไปใช้วิธีกด coyp-id3 + clipboard...")
                                                                    copied_uid = copy_uid_via_id3(device)
                                                            else:
                                                                time.sleep(2)
                                                            copy_found = True
                                                            break
                                                        time.sleep(1)
                                                    except Exception as e:
                                                        print(f"Device {device.serial}: ข้อผิดพลาดในการค้นหา {copy_img}: {e}")
                                                        time.sleep(1)
                                                if not copy_found:
                                                    print(f"Device {device.serial}: ไม่พบ {copy_img} ข้ามขั้นตอน copy UID")
                                                    break

                                            # ส่งไฟล์ออก (backup) โดยใช้ UID ตั้งชื่อไฟล์ เช่น noradom+[409f99e9]+_LINE_COCOS_PREF_KEY.xml
                                            if backup_game_data(device, copied_uid):
                                                # หลังส่งไฟล์ออกแล้ว ทำขั้นตอนเดียวกับตอนเริ่มบอท แล้วค่อยเริ่มรอบใหม่
                                                # (ถ้าหา guestlogin เกิน 30 ครั้งไม่เจอ จะปิดแอพแล้วเริ่มใหม่ตั้งแต่ลบไฟล์เอง)
                                                reset_app_and_login(device, CLEAR_APP_WAIT)

                                                # รีเซ็ตตัวแปรทั้งหมด
                                                last_image_found_time = time.time()
                                                tried_mainstage = False
                                                mainstage_attempts = 0
                                                break  # ออกจากลูป sequence_images
                                        
                                        elif seq_img == 'img/7day.png':
                                            # แวะหา cancel.png 8 วินาทีก่อนกด 7day
                                            print(f"Device {device.serial}: แวะหา cancel.png 8 วินาทีก่อนกด 7day...")
                                            cancel_hunt_start = time.time()
                                            while time.time() - cancel_hunt_start < 8:
                                                try:
                                                    hunt_img = fast_screencap(device)
                                                    hunt_cancel = ImgSearchADB(hunt_img, 'img/cancel.png')
                                                    if hunt_cancel:
                                                        print(f"Device {device.serial}: พบ cancel.png กดปิดก่อน")
                                                        device.shell(f"input tap {hunt_cancel[0][0]} {hunt_cancel[0][1]}")
                                                        time.sleep(1)
                                                except Exception as e:
                                                    print(f"Device {device.serial}: ข้อผิดพลาดระหว่างหา cancel.png: {e}")
                                                time.sleep(0.5)

                                            # ถ่ายจอใหม่แล้วค่อยกด 7day (ตำแหน่งอาจเปลี่ยนหลังปิด popup)
                                            print(f"Device {device.serial}: ครบ 8 วินาที กด 7day.png")
                                            try:
                                                fresh_img = fast_screencap(device)
                                                new_pos = ImgSearchADB(fresh_img, 'img/7day.png')
                                            except Exception:
                                                new_pos = None
                                            if new_pos:
                                                device.shell(f"input tap {new_pos[0][0]} {new_pos[0][1]}")
                                            else:
                                                device.shell(f"input tap {pos[0][0]} {pos[0][1]}")
                                            time.sleep(CLICK_DELAY)

                                        else:
                                            device.shell(f"input tap {pos[0][0]} {pos[0][1]}")
                                            time.sleep(CLICK_DELAY)
                                        break
                                    time.sleep(SEARCH_INTERVAL)
                                    
                                except Exception as e:
                                    print(f"Device {device.serial}: ข้อผิดพลาด {seq_img}: {e}")
                                    time.sleep(SEARCH_INTERVAL)
                                    break
                            
                            # หลังจาก backup เสร็จ ให้ออกจาก loop
                            if seq_img == 'img/box3.png':
                                break

                    # ตรวจสอบ mainstage
                    if not tried_mainstage and mainstage_attempts < max_mainstage_attempts:
                        pos_mainstage = ImgSearchADB(adb_img, mainstage_path)
                        if pos_mainstage:
                            found_any_image = True
                            last_image_found_time = time.time()
                            print(f"Device {device.serial}: พบ mainstage.png")
                            
                            # ตรวจสอบ fixbugicon ก่อนคลิก
                            pos_fixbug = ImgSearchADB(adb_img, 'img/fixbugicon.png')
                            if pos_fixbug:
                                print(f"Device {device.serial}: พบ fixbugicon ทำการ Clear App...")
                                device.shell("am force-stop com.linecorp.LGRGS")
                                time.sleep(2)
                                open_app(device)
                                time.sleep(10)
                                mainstage_attempts += 1
                                continue
                            
                            print(f"Device {device.serial}: คลิก mainstage.png")
                            device.shell(f"input tap {pos_mainstage[0][0]} {pos_mainstage[0][1]}")
                            check_fixback = True
                            time.sleep(2)
                            tried_mainstage = True

                    # ตรวจสอบ event.png และ cancel.png
                    pos_event = ImgSearchADB(adb_img, 'img/event.png')
                    if pos_event:
                        found_any_image = True
                        last_image_found_time = time.time()
                        print(f"Device {device.serial}: พบ event.png")
                        print(f"Device {device.serial}: คลิก event.png")
                        device.shell(f"input tap {pos_event[0][0]} {pos_event[0][1]}")
                        time.sleep(1)
                        
                        # เริ่มกระบวนการกด BACK และค้นหา cancel.png
                        back_press_count = 0
                        max_back_press = 50
                        while back_press_count < max_back_press:
                            try:
                                check_img = fast_screencap(device)
                                pos_cancel = ImgSearchADB(check_img, 'img/cancel.png')
                                
                                if pos_cancel:
                                    print(f"Device {device.serial}: พบ cancel.png หลังจากกด BACK {back_press_count} ครั้ง")
                                    device.shell(f"input tap {pos_cancel[0][0]} {pos_cancel[0][1]}")
                                    time.sleep(1)
                                    break
                                
                                back_press_count += 1
                                print(f"Device {device.serial}: กด BACK ครั้งที่ {back_press_count}")
                                device.shell("input keyevent KEYCODE_BACK")
                                
                            except Exception as e:
                                print(f"Device {device.serial}: ข้อผิดพลาดระหว่างการค้นหา cancel.png: {e}")
                                break

                    # ตรวจสอบรูปภาพอื่นๆ
                    for img_path in image_list:
                        try:
                            pos = ImgSearchADB(adb_img, img_path)
                            if pos:
                                found_any_image = True
                                last_image_found_time = time.time()
                                print(f"Device {device.serial}: พบ {img_path}")
                                
                                # ตรวจสอบ fixid.png
                                if 'fixid.png' in img_path:
                                    print(f"\nDevice {device.serial}: === พบ fixid.png ===")
                                    print(f"Device {device.serial}: เริ่มกระบวนการใหม่...")
                                    
                                    # Clear App
                                    print(f"Device {device.serial}: [1/3] Clear App...")
                                    device.shell("am force-stop com.linecorp.LGRGS")
                                    time.sleep(2)
                                    device.shell("su -c 'rm -rf /data/data/com.linecorp.LGRGS/shared_prefs /data/data/com.linecorp.LGRGS/files /data/data/com.linecorp.LGRGS/databases /data/data/com.linecorp.LGRGS/no_backup /data/data/com.linecorp.LGRGS/app_webview /data/data/com.linecorp.LGRGS/app_pccache /data/data/com.linecorp.LGRGS/app_tmppccache /data/data/com.linecorp.LGRGS/app_textures /data/data/com.linecorp.LGRGS/cache /data/data/com.linecorp.LGRGS/code_cache'")  # ลบข้อมูลภายในทั้งหมด แต่เก็บทรัพยากรเกม 1.5GB ใน /sdcard ไว้
                                    time.sleep(2)
                                    
                                    print(f"Device {device.serial}: [2/3] รอ {CLEAR_APP_WAIT} วินาที...")
                                    for i in range(CLEAR_APP_WAIT, 0, -1):
                                        print(f"Device {device.serial}: เหลือเวลา {i} วินาที")
                                        time.sleep(1)
                                    
                                    print(f"Device {device.serial}: [3/3] เปิดแอพใหม่...")
                                    open_app(device)
                                    time.sleep(5)
                                    
                                    # รีเซ็ตตัวแปรทั้งหมด
                                    last_image_found_time = time.time()
                                    tried_mainstage = False
                                    mainstage_attempts = 0
                                    event_start_time = None
                                    event_found_continuously = False
                                    check_fixback = False
                                    break
                                
                                elif 'steage2.png' in img_path:
                                    print(f"Device {device.serial}: จัดการ steage2.png")
                                    time.sleep(2)
                                    new_pos = ImgSearchADB(adb_img, 'img/steage2.png')
                                    if new_pos:
                                        device.shell(f"input tap {new_pos[0][0]} {new_pos[0][1]}")
                                    else:
                                        device.shell(f"input tap {pos[0][0]} {pos[0][1]}")
                                    
                                    time.sleep(2)
                                    pos_start = ImgSearchADB(adb_img, 'img/start.png')
                                    if pos_start:
                                        device.shell(f"input tap {pos_start[0][0]} {pos_start[0][1]}")
                                    time.sleep(1)
                                
                                elif 'waitsteplogin1.png' in img_path:
                                    print(f"Device {device.serial}: รอ login 40 วินาที...")
                                    for i in range(40, 0, -1):
                                        print(f"Device {device.serial}: เหลือเวลา {i} วินาที")
                                        time.sleep(1)
                                    device.shell("input tap 491 298")
                                
                                elif 'sing.png' in img_path:
                                    device.shell(f"input tap {pos[0][0]} {pos[0][1]}")
                                    perform_sing_actions(device)

                                elif 'saveteam.png' in img_path:
                                    print(f"\nDevice {device.serial}: === พบ saveteam.png กด save team ===")
                                    device.shell(f"input tap {pos[0][0]} {pos[0][1]}")
                                    time.sleep(3)

                                    # หลังจบ save team: ปิดแอพแล้วเปิดใหม่เลย (ไม่ลบข้อมูล)
                                    print(f"Device {device.serial}: ปิดแอพหลัง save team...")
                                    device.shell("am force-stop com.linecorp.LGRGS")
                                    time.sleep(2)
                                    print(f"Device {device.serial}: เปิดแอพใหม่...")
                                    open_app(device)
                                    time.sleep(10)

                                    # รีเซ็ตสถานะให้กลับไปหาและกด mainstage.png ใหม่
                                    # ถ้าระหว่างนั้นเจอ steage2.png จะกระโดดเข้าขั้นตอน steage2 ต่อเองตามปกติ
                                    tried_mainstage = False
                                    mainstage_attempts = 0
                                    last_image_found_time = time.time()
                                    break

                                elif 'herodrag.png' in img_path:
                                    print(f"Device {device.serial}: ลาก herodrag")
                                    device.shell("input swipe 484 200 503 387 100")
                                    time.sleep(1)
                                
                                elif 'herodrag1.png' in img_path:
                                    print(f"Device {device.serial}: ลาก herodrag1")
                                    device.shell("input swipe 142 440 474 191 100")
                                    time.sleep(1)
                                
                                else:
                                    device.shell(f"input tap {pos[0][0]} {pos[0][1]}")
                                    time.sleep(CLICK_DELAY)
                                
                        except Exception as e:
                            print(f"Device {device.serial}: ข้อผิดพลาด {img_path}: {e}")
                            continue

                    # ถ้าเจอรูป = มีความคืบหน้า -> รีเซ็ตนาฬิกา watchdog 25 นาที
                    if found_any_image:
                        mark_activity(device)

                    # ตรวจสอบ timeout: ไม่พบรูปเกินกำหนด -> ล้างแอพเริ่มใหม่ตั้งแต่ลบไฟล์ (full reset + relogin)
                    if not found_any_image:
                        if time.time() - last_image_found_time > no_image_timeout:
                            print(f"\nDevice {device.serial}: === ไม่พบรูปภาพเกิน {no_image_timeout} วินาที - เริ่มใหม่ตั้งแต่ลบไฟล์ ===")
                            reset_app_and_login(device, CLEAR_APP_WAIT)
                            last_image_found_time = time.time()
                            tried_mainstage = False
                            mainstage_attempts = 0
                            break  # ออกจากลูปปัจจุบันเพื่อเริ่มต้นใหม่

                    time.sleep(SEARCH_INTERVAL)
                    
                except Exception as e:
                    print(f"Device {device.serial}: ข้อผิดพลาด: {e}")
                    time.sleep(SEARCH_INTERVAL)
                    if "device offline" in str(e) or "device unauthorized" in str(e):
                        print(f"Device {device.serial}: อุปกรณ์หลุด กำลังเชื่อมต่อใหม่...")
                        break

        except StuckTimeoutError as e:
            # เครื่องค้างเกิน 25 นาที (จับได้จากทุกเฟส รวมถึงตอน login) -> วนกลับไปต้น while
            # ซึ่งจะเรียก reset_app_and_login (ลบไฟล์ + เปิดแอพ + login ใหม่) เอง
            print(f"\nDevice {device.serial}: === {e} === ล้างแอพเริ่มใหม่ตั้งแต่ลบไฟล์")
            continue
        except Exception as e:
            print(f"Device {device.serial}: ข้อผิดพลาดร้ายแรง: {e}")
            time.sleep(5)
            continue

def press_back_until_cancel(device):
    """ฟังก์ชันสำหรับกด BACK รัวๆ จนกว่าจะเจอ cancel.png"""
    print(f"Device {device.serial}: เริ่มกด BACK เพื่อหา cancel.png...")
    back_count = 0
    max_attempts = 50  # จำนวนครั้งสูงสุดที่จะลองกด BACK
    
    while back_count < max_attempts:
        try:
            # ถ่ายภาพหน้าจอ
            current_img = fast_screencap(device)
            
            # ตรวจสอบ cancel.png
            cancel_pos = ImgSearchADB(current_img, 'img/cancel.png')
            if cancel_pos:
                print(f"Device {device.serial}: พบ cancel.png หลังจากกด BACK {back_count} ครั้ง")
                device.shell(f"input tap {cancel_pos[0][0]} {cancel_pos[0][1]}")
                time.sleep(1)
                return True
                
            # กด BACK
            device.shell("input keyevent KEYCODE_BACK")
            back_count += 1
            print(f"Device {device.serial}: กด BACK ครั้งที่ {back_count}")
            time.sleep(1)
            
        except Exception as e:
            print(f"Device {device.serial}: ข้อผิดพลาดในการค้นหา cancel.png: {e}")
            return False
            
    print(f"Device {device.serial}: ไม่พบ cancel.png หลังจากพยายาม {max_attempts} ครั้ง")
    return False

def check_screen_color(adb_img, target_color=0x303030, threshold_percentage=80, sample_rate=0.25):
    try:
        # ลดขนาดภาพลงเพื่อเพิ่มประสิทธิภาพ
        height, width = adb_img.shape[:2]
        if height * width > 1000000:  # ถ้าภาพใหญ่เกินไป
            scale = 1000000 / (height * width)
            sample_rate *= scale
            
        sample_h = max(1, int(height * sample_rate))
        sample_w = max(1, int(width * sample_rate))
        sampled_img = cv2.resize(adb_img, (sample_w, sample_h))
        
        # แปลง BGR เป็น HSV เพื่อลดผลกระทบจากความสว่าง
        hsv = cv2.cvtColor(sampled_img, cv2.COLOR_BGR2HSV)
        lower_gray = np.array([0, 0, 20])
        upper_gray = np.array([180, 30, 80])
        
        mask = cv2.inRange(hsv, lower_gray, upper_gray)
        matching_pixels = np.count_nonzero(mask)
        total_pixels = mask.size
        
        percentage = (matching_pixels / total_pixels) * 100
        return percentage, percentage > threshold_percentage
        
    except Exception as e:
        print(f"Error in check_screen_color: {e}")
        return 0, False

def monitor_screen_color(device):
    """ฟังก์ชันสำหรับตรวจสอบสีหน้าจอแบบต่อเนื่อง"""
    last_check_time = 0
    CHECK_INTERVAL = 1.0  # ตรวจสอบทุก 1 วินาที
    
    while True:
        try:
            current_time = time.time()
            if current_time - last_check_time >= CHECK_INTERVAL:
                # ถ่ายภาพหน้าจอ
                adb_img = fast_screencap(device)
                
                # ตรวจสอบสี
                screen_percentage, is_gray_screen = check_screen_color(adb_img)
                
                last_check_time = current_time
            
            time.sleep(0.1)  # ลด CPU usage
            
        except Exception as e:
            print(f"Error in monitor_screen_color: {e}")
            time.sleep(1)

def limit_cpu_usage():
    """ลด priority ของ process บอท ให้ OS/emulator ได้ CPU ก่อน (เครื่องไม่ค้าง)"""
    try:
        p = psutil.Process()
        if os.name == "nt":  # Windows
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(10)
    except Exception as e:
        print(f"ตั้ง CPU priority ไม่ได้: {e}")

def Main():
    limit_cpu_usage()
    
    while True:
        try:
            print("\n=== เริ่มต้นโปรแกรม ===")
            check_required_images()
            print("กำลังค้นหาอุปกรณ์ MuMu...")
            adb, devices = connect_to_mumu()
            
            if devices:
                if isinstance(devices, list):
                    # คำนวณจำนวน workers ที่เหมาะสม
                    cpu_count = os.cpu_count() or 1
                    # ต้องมี 1 worker ต่อ 1 เครื่องเสมอ (device_worker วนไม่รู้จบ ถ้า worker น้อยกว่าเครื่อง บางเครื่องจะไม่ถูกทำงานเลย)
                    max_workers = len(devices)

                    # เครื่องสเปคแรง CPU เหลือเยอะ - สแกนถี่เพื่อความไว (ไม่ต้อง throttle ตามจำนวนเครื่อง)
                    global GLOBAL_SEARCH_INTERVAL
                    GLOBAL_SEARCH_INTERVAL = 0.3

                    print(f"\nพบ {len(devices)} อุปกรณ์ ใช้ {max_workers} workers | ระยะสแกน {GLOBAL_SEARCH_INTERVAL:.1f}s/รอบ")
                    
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = [executor.submit(device_worker, device) 
                                 for device in devices]
                        done, _ = concurrent.futures.wait(
                            futures,
                            return_when=concurrent.futures.FIRST_EXCEPTION
                        )
                        
                        # ตรวจสอบ exceptions
                        for future in done:
                            try:
                                future.result()
                            except Exception as e:
                                print(f"Worker error: {e}")
                else:
                    print("\nพบ 1 อุปกรณ์ กำลังเริ่มทำงาน...")
                    device_worker(devices)
            else:
                print("ไม่พบอุปกรณ์ จะลองใหม่ในอีก 5 วินาที...")
                time.sleep(5)
                
        except Exception as e:
            print(f"เกิดข้อผิดพลาดในการทำงาน: {e}")
            time.sleep(5)

if __name__ == "__main__":
    Main()

