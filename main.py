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

def find_mumu_adb_ports():
    """ค้นหา port ของ MuMu ADB ที่ active อยู่"""
    try:
        # รัน adb devices เพื่อดู list ของ devices ที่เชื่อมต่ออยู่
        result = subprocess.run(['adb', 'devices'], capture_output=True, text=True)
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
                    ["adb", "connect", f"127.0.0.1:{port}"],
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



def connect_to_mumu():
    """เชื่อมต่อกับ MuMu Emulator แบบเร็วขึ้น"""
    try:
        print("\n=== เริ่มกระบวนการเชื่อมต่อ MuMu ===")
        
        # รีเซ็ต ADB server อย่างรวดเร็ว
        subprocess.run(["adb", "kill-server"], capture_output=True, timeout=3)
        subprocess.run(["adb", "start-server"], capture_output=True, timeout=3)
        time.sleep(1)
        
        all_ports = set()
        
        # รวบรวม ports จากทุกแหล่งพร้อมกัน
        with concurrent.futures.ThreadPoolExecutor() as executor:
            config_ports = executor.submit(scan_mumu_directory)
            netstat_ports = executor.submit(scan_ports_from_netstat)
            process_ports = executor.submit(lambda: [port for _, port in find_mumu_processes()])
            active_ports = executor.submit(find_mumu_adb_ports)
            
            all_ports.update(config_ports.result())
            all_ports.update(netstat_ports.result())
            all_ports.update(process_ports.result())
            all_ports.update(active_ports.result())
        
        # เชื่อมต่อกับทุก port พร้อมกัน
        connected_devices = []
        adb = AdbClient(host="127.0.0.1", port=5037)
        
        def try_connect_port(port):
            try:
                subprocess.run(
                    ["adb", "connect", f"127.0.0.1:{port}"],
                    capture_output=True,
                    timeout=2
                )
                devices = adb.devices()
                return [d for d in devices if f"127.0.0.1:{port}" in d.serial]
            except:
                return []
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [executor.submit(try_connect_port, port) for port in all_ports]
            for future in concurrent.futures.as_completed(futures):
                connected_devices.extend(future.result())
        
        if connected_devices:
            return adb, connected_devices if len(connected_devices) > 1 else connected_devices[0]
        return None, []
        
    except Exception as e:
        print(f"Error in connect_to_mumu: {e}")
        return None, []

def backup_game_data(device):
    """Backup game data with sequential ID naming and detailed logging"""
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
            ['adb', "-s", device_id, "pull", "/sdcard/temp_backup.xml", backup_path],
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
    def __init__(self, max_size=50, cleanup_interval=300):
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
            self.cache[path] = cv2.imread(path, cv2.IMREAD_COLOR)
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
                cap = self.device.screencap()
                image = np.frombuffer(cap, dtype=np.uint8)
                self.last_capture = cv2.imdecode(image, cv2.IMREAD_COLOR)
                self.last_capture_time = current_time
            except Exception as e:
                print(f"Error capturing screen: {e}")
                if self.last_capture is None:
                    raise  # ถ้าไม่มี cache ให้ raise error
        
        return self.last_capture


def ImgSearchADB(adb_img, find_img_path, threshold=0.95, method=cv2.TM_CCOEFF_NORMED):
    try:
        find_img = image_cache.get_image(find_img_path)  # ใช้ cache แทน
        if find_img is None:
            return None
            
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
                    cap = device.screencap()
                    image = np.frombuffer(cap, dtype=np.uint8)
                    adb_img = cv2.imdecode(image, cv2.IMREAD_COLOR)
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
                cap = device.screencap()
                image = np.frombuffer(cap, dtype=np.uint8)
                adb_img = cv2.imdecode(image, cv2.IMREAD_COLOR)

                pos_guest = ImgSearchADB(adb_img, 'img/guestloing.png')
                if pos_guest:
                    print(f"\nDevice {device.serial}: === พบ Guest Login กดเลย ===")
                    device.shell(f"input tap {pos_guest[0][0]} {pos_guest[0][1]}")
                    time.sleep(3)
                    check_and_click_ok(device, "หลังกด Guest Login")

                    # ถ่ายภาพหน้าจอใหม่เพื่อค้นหา login.png
                    cap = device.screencap()
                    image = np.frombuffer(cap, dtype=np.uint8)
                    adb_img = cv2.imdecode(image, cv2.IMREAD_COLOR)

                # ค้นหา login.png จากภาพล่าสุด
                print(f"Device {device.serial}: กำลังค้นหา login.png...")
                pos_login = ImgSearchADB(adb_img, 'img/login.png')
                if pos_login:
                    print(f"\nDevice {device.serial}: === เริ่มขั้นตอน Login ===")
                    device.shell(f"input tap {pos_login[0][0]} {pos_login[0][1]}")
                    time.sleep(3)

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



def device_worker(device):
    """Worker function for handling device automation"""
    last_memory_cleanup = time.time()
    last_image_cleanup = time.time()
    MEMORY_CLEANUP_INTERVAL = 300  # ทำความสะอาด memory ทุก 5 นาที
    IMAGE_CLEANUP_INTERVAL = 60    # ทำความสะอาด image cache ทุก 1 นาที
    while True:  # เพิ่ม loop หลักเพื่อทำงานต่อเนื่อง
        try:
            
                        # เริ่ม thread สำหรับตรวจสอบสีหน้าจอ
            monitor_thread = threading.Thread(
                target=monitor_screen_color,
                args=(device,),
                daemon=True  # ให้ thread จบเมื่อโปรแกรมหลักจบ
            )
            monitor_thread.start()
            
            limit_cpu_usage()
            
            # ค่าคงที่สำหรับการตั้งค่าเวลา
            SEARCH_INTERVAL = 0.5  # ระยะห่างระหว่างการค้นหารูปภาพ
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

            # ขั้นตอนแรก: ลบเฉพาะไฟล์ shared_prefs .xml และรีสตาร์ท
            print(f"\nDevice {device.serial}: === เริ่มกระบวนการลบไฟล์ shared_prefs ===")
            try:
                print(f"Device {device.serial}: [1/3] กำลังปิดแอพ...")
                device.shell("am force-stop com.linecorp.LGRGS")
                time.sleep(2)

                print(f"Device {device.serial}: [2/3] กำลังลบไฟล์ _LINE_COCOS_PREF_KEY.xml...")
                device.shell("su -c 'rm /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml'")
                print(f"Device {device.serial}: ลบไฟล์ shared_prefs เสร็จสิ้น")

                print(f"Device {device.serial}: รอ {CLEAR_APP_WAIT} วินาทีก่อนเริ่มต่อ...")
                for i in range(CLEAR_APP_WAIT, 0, -1):
                    print(f"Device {device.serial}: เหลือเวลา {i} วินาที")
                    time.sleep(1)

                print(f"Device {device.serial}: [3/3] กำลังเปิดแอพใหม่...")
                device.shell("monkey -p com.linecorp.LGRGS 1")
                time.sleep(5)

                # ค้นหา guestlogin.png ทันทีตั้งแต่เปิดแอพ
                perform_sing_actions(device)

            except Exception as e:
                print(f"Device {device.serial}: เกิดข้อผิดพลาดในการลบไฟล์ shared_prefs: {e}")
                print("ดำเนินการต่อ...")

            # ตัวแปรสำหรับการติดตามสถานะ
            last_image_found_time = time.time()
            no_image_timeout = 400
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
                    # ถ่ายภาพหน้าจอสำหรับตรวจจับรูปภาพ
                    cap = device.screencap()
                    # เพิ่ม sleep time หลังการ screencap
                    time.sleep(SEARCH_INTERVAL)
                    image = np.frombuffer(cap, dtype=np.uint8)
                    adb_img = cv2.imdecode(image, cv2.IMREAD_COLOR)
                    found_any_image = False



                    # ในส่วนของการตรวจสอบสีหน้าจอ:
                    screen_percentage, is_gray_screen = check_screen_color(adb_img)
                    print(f"Device {device.serial}: สีเทา (0x303030): {screen_percentage:.2f}%")

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
                            # เริ่มจับเวลาเมื่อเจอหน้าจอสีเทาครั้งแรก
                            gray_screen_start_time = time.time()
                            print(f"Device {device.serial}: เริ่มจับเวลาหน้าจอสีเทา...")
                        else:
                            # คำนวณเวลาที่ผ่านไป
                            elapsed_time = time.time() - gray_screen_start_time
                            remaining_time = GRAY_SCREEN_TIMEOUT - elapsed_time
                            
                            # แสดงเวลาที่เหลือ
                            print(f"Device {device.serial}: หน้าจอสีเทาค้าง {elapsed_time:.1f} วินาที (เหลือ {remaining_time:.1f} วินาที)")
                            
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
                                device.shell("monkey -p com.linecorp.LGRGS 1")
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
                        device.shell("monkey -p com.linecorp.LGRGS 1")
                        time.sleep(10)

                        # เริ่มค้นหา event.png
                        print(f"Device {device.serial}: เริ่มค้นหา event.png...")
                        event_start_time = None
                        event_found_continuously = False
                        back_pressed = False

                        while True:
                            try:
                                cap = device.screencap()
                                image = np.frombuffer(cap, dtype=np.uint8)
                                current_img = cv2.imdecode(image, cv2.IMREAD_COLOR)
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
                                        
                                        # เริ่มกดปุ่ม BACK รัวๆ
                                        print(f"Device {device.serial}: เริ่มกดปุ่ม BACK รัวๆ...")
                                        back_count = 0
                                        max_back_presses = 50  # จำนวนครั้งที่จะกด BACK
                                        
                                        for i in range(max_back_presses):
                                            print(f"Device {device.serial}: กดปุ่ม BACK ครั้งที่ {i + 1}/{max_back_presses}")
                                            device.shell("input keyevent KEYCODE_BACK")
                                            
                                            # ตรวจสอบหา cancel.png หลังจากกด BACK แต่ละครั้ง
                                            try:
                                                cap = device.screencap()
                                                image = np.frombuffer(cap, dtype=np.uint8)
                                                check_img = cv2.imdecode(image, cv2.IMREAD_COLOR)
                                                cancel_pos = ImgSearchADB(check_img, 'img/cancel.png')
                                                
                                                if cancel_pos:
                                                    print(f"Device {device.serial}: พบ cancel.png หลังจากกด BACK {i + 1} ครั้ง")
                                                    device.shell(f"input tap {cancel_pos[0][0]} {cancel_pos[0][1]}")
                                                    back_pressed = True
                                                    print(f"Device {device.serial}: กดปุ่ม cancel แล้ว")
                                                    break
                                            except Exception as e:
                                                print(f"Device {device.serial}: ข้อผิดพลาดในการค้นหา cancel.png: {e}")
                                        
                                        if back_pressed:
                                            print(f"Device {device.serial}: เสร็จสิ้นการกดปุ่ม BACK")
                                            print(f"Device {device.serial}: เริ่มค้นหา sequence_images...")
                                            break
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
                                    cap = device.screencap()
                                    image = np.frombuffer(cap, dtype=np.uint8)
                                    current_img = cv2.imdecode(image, cv2.IMREAD_COLOR)
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
                                            
                                            if backup_game_data(device):
                                                print(f"\nDevice {device.serial}: === เริ่มต้นกระบวนการใหม่ ===")
                                                print(f"Device {device.serial}: Clear App...")
                                                device.shell("am force-stop com.linecorp.LGRGS")
                                                time.sleep(2)
                                                device.shell("su -c 'rm /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml'")
                                                time.sleep(2)
                                                
                                                print(f"Device {device.serial}: เปิดแอพใหม่...")
                                                device.shell("monkey -p com.linecorp.LGRGS 1")
                                                time.sleep(5)
                                                
                                                # รีเซ็ตตัวแปรทั้งหมด
                                                last_image_found_time = time.time()
                                                tried_mainstage = False
                                                mainstage_attempts = 0
                                                break  # ออกจากลูป sequence_images
                                        
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
                                device.shell("monkey -p com.linecorp.LGRGS 1")
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
                                cap = device.screencap()
                                image = np.frombuffer(cap, dtype=np.uint8)
                                check_img = cv2.imdecode(image, cv2.IMREAD_COLOR)
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
                                    device.shell("su -c 'rm /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml'")
                                    time.sleep(2)
                                    
                                    print(f"Device {device.serial}: [2/3] รอ {CLEAR_APP_WAIT} วินาที...")
                                    for i in range(CLEAR_APP_WAIT, 0, -1):
                                        print(f"Device {device.serial}: เหลือเวลา {i} วินาที")
                                        time.sleep(1)
                                    
                                    print(f"Device {device.serial}: [3/3] เปิดแอพใหม่...")
                                    device.shell("monkey -p com.linecorp.LGRGS 1")
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

                    # ตรวจสอบ timeout
                    if not found_any_image:
                        if time.time() - last_image_found_time > no_image_timeout:
                            print(f"\nDevice {device.serial}: === ไม่พบรูปภาพเกิน {no_image_timeout} วินาที ===")
                            print(f"Device {device.serial}: Clear App...")
                            device.shell("am force-stop com.linecorp.LGRGS")
                            time.sleep(2)
                            device.shell("su -c 'rm /data/data/com.linecorp.LGRGS/shared_prefs/_LINE_COCOS_PREF_KEY.xml'")
                            time.sleep(2)
                            
                            print(f"Device {device.serial}: รอ {CLEAR_APP_WAIT} วินาที")
                            for i in range(CLEAR_APP_WAIT, 0, -1):
                                print(f"Device {device.serial}: เหลือเวลา {i} วินาที")
                                time.sleep(1)
                            
                            print(f"Device {device.serial}: เปิดแอพใหม่...")
                            device.shell("monkey -p com.linecorp.LGRGS 1")
                            time.sleep(5)
                            
                            last_image_found_time = time.time()
                            tried_mainstage = False
                            mainstage_attempts = 0
                            break  # ออกจากลูปปัจจุบันเพื่อเริ่มต้นใหม่
                        else:
                            remaining_time = no_image_timeout - (time.time() - last_image_found_time)
                            print(f"Device {device.serial}: ไม่พบรูปภาพ (เหลือ {int(remaining_time)} วินาที)")
                    
                    time.sleep(SEARCH_INTERVAL)
                    
                except Exception as e:
                    print(f"Device {device.serial}: ข้อผิดพลาด: {e}")
                    time.sleep(SEARCH_INTERVAL)
                    if "device offline" in str(e) or "device unauthorized" in str(e):
                        print(f"Device {device.serial}: อุปกรณ์หลุด กำลังเชื่อมต่อใหม่...")
                        break

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
            cap = device.screencap()
            image = np.frombuffer(cap, dtype=np.uint8)
            current_img = cv2.imdecode(image, cv2.IMREAD_COLOR)
            
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
                cap = device.screencap()
                image = np.frombuffer(cap, dtype=np.uint8)
                adb_img = cv2.imdecode(image, cv2.IMREAD_COLOR)
                
                # ตรวจสอบสี
                screen_percentage, is_gray_screen = check_screen_color(adb_img)
                
                # แสดงผลด้วยสีที่แตกต่างกันตามระดับ
                if screen_percentage >= 80:
                    print(f"\033[91mDevice {device.serial}: สีเทา (0x303030): {screen_percentage:.2f}% [สูง]\033[0m")
                elif screen_percentage >= 50:
                    print(f"\033[93mDevice {device.serial}: สีเทา (0x303030): {screen_percentage:.2f}% [ปานกลาง]\033[0m")
                else:
                    print(f"\033[92mDevice {device.serial}: สีเทา (0x303030): {screen_percentage:.2f}% [ต่ำ]\033[0m")
                
                last_check_time = current_time
            
            time.sleep(0.1)  # ลด CPU usage
            
        except Exception as e:
            print(f"Error in monitor_screen_color: {e}")
            time.sleep(1)

def limit_cpu_usage():
    # ตั้งค่า nice value เพื่อลดความสำคัญของ process
    try:
        os.nice(10)  # ค่าสูงหมายถึงความสำคัญน้อยลง
    except:
        pass

def Main():
    limit_cpu_usage()
    
    while True:
        try:
            print("\n=== เริ่มต้นโปรแกรม ===")
            print("กำลังค้นหาอุปกรณ์ MuMu...")
            adb, devices = connect_to_mumu()
            
            if devices:
                if isinstance(devices, list):
                    # คำนวณจำนวน workers ที่เหมาะสม
                    cpu_count = os.cpu_count() or 1
                    max_workers = min(len(devices), cpu_count - 1 or 1)
                    
                    print(f"\nพบ {len(devices)} อุปกรณ์ ใช้ {max_workers} workers")
                    
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

