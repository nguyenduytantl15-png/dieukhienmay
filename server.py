# -*- coding: utf-8 -*-
"""
Điều Khiển Máy - chương trình chạy trên máy tính Windows.
Điện thoại (cùng Wi-Fi) kết nối vào để xem màn hình và điều khiển chuột/bàn phím.
Chạy: python server.py   (cần: pip install pillow)
"""
import sys, os, io, re, json, time, secrets, socket, threading, subprocess, urllib.request
import struct, base64, hashlib

if os.name != "nt":
    print("Chương trình này chỉ chạy trên Windows.")
    sys.exit(1)

import ctypes
import ctypes.wintypes as wt
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from PIL import ImageGrab, Image

PORT = 8765

# ---------- Thư mục ----------
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)          # thư mục chứa file .exe
    RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)         # file web đóng gói kèm
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    RES_DIR = APP_DIR
WEB_DIR = os.path.join(RES_DIR, "web")

# ---------- Windows API ----------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # tọa độ đúng khi màn hình phóng to 125%, 150%...
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

ULONG_PTR = ctypes.c_size_t

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]

class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]

user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wt.UINT

def send_inputs(items):
    if not items:
        return
    arr = (INPUT * len(items))(*items)
    user32.SendInput(len(items), arr, ctypes.sizeof(INPUT))

def mouse_input(flags, data=0):
    i = INPUT(type=0)
    i.mi = MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0)
    return i

MOUSE_FLAGS = {  # (nhấn, nhả)
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
}

VK = {
    "enter": 0x0D, "bs": 0x08, "tab": 0x09, "esc": 0x1B, "space": 0x20,
    "del": 0x2E, "ins": 0x2D, "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdn": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "prtsc": 0x2C, "menu": 0x5D, "caps": 0x14,
}
for n in range(1, 13):
    VK["f%d" % n] = 0x6F + n
EXTENDED = {0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x5B, 0x5D, 0x2C}

def vk_of(name):
    name = name.lower()
    if name in VK:
        return VK[name]
    if len(name) == 1 and (name.isalpha() or name.isdigit()):
        return ord(name.upper())
    return None

def key_input(vk, up=False):
    i = INPUT(type=1)
    flags = 0x0002 if up else 0
    if vk in EXTENDED:
        flags |= 0x0001
    i.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    return i

def unicode_inputs(ch):
    out = []
    data = ch.encode("utf-16-le")
    for k in range(0, len(data), 2):
        code = data[k] | (data[k + 1] << 8)
        for up in (False, True):
            i = INPUT(type=1)
            i.ki = KEYBDINPUT(0, code, 0x0004 | (0x0002 if up else 0), 0, 0)
            out.append(i)
    return out

def press_combo(names):
    vks = [vk_of(n) for n in names]
    if not vks or None in vks:
        return
    items = [key_input(v) for v in vks] + [key_input(v, True) for v in reversed(vks)]
    send_inputs(items)

def type_text(s):
    items = []
    for ch in s:
        if ch == "\n":
            items += [key_input(0x0D), key_input(0x0D, True)]
        elif ch == "\t":
            items += [key_input(0x09), key_input(0x09, True)]
        else:
            items += unicode_inputs(ch)
    send_inputs(items)

def screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

def cursor_pos():
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y

def set_cursor(x, y):
    w, h = screen_size()
    x = max(0, min(w - 1, int(round(x))))
    y = max(0, min(h - 1, int(round(y))))
    user32.SetCursorPos(x, y)

# ---------- Xử lý lệnh từ điện thoại ----------
input_lock = threading.Lock()

def handle_events(events):
    with input_lock:
        for ev in events:
            t = ev.get("t")
            w, h = screen_size()
            if t == "move":
                set_cursor(float(ev["x"]) * (w - 1), float(ev["y"]) * (h - 1))
            elif t == "rel":
                cx, cy = cursor_pos()
                set_cursor(cx + float(ev.get("dx", 0)), cy + float(ev.get("dy", 0)))
            elif t in ("down", "up", "click"):
                b = MOUSE_FLAGS.get(ev.get("b", "left"), MOUSE_FLAGS["left"])
                if t == "down":
                    send_inputs([mouse_input(b[0])])
                elif t == "up":
                    send_inputs([mouse_input(b[1])])
                else:
                    for _ in range(int(ev.get("n", 1))):
                        send_inputs([mouse_input(b[0]), mouse_input(b[1])])
            elif t == "wheel":
                flag = 0x01000 if ev.get("h") else 0x0800
                send_inputs([mouse_input(flag, int(ev.get("d", 0)))])
            elif t == "text":
                type_text(str(ev.get("s", ""))[:2000])
            elif t == "bs":
                n = max(0, min(200, int(ev.get("n", 1))))
                send_inputs([key_input(0x08), key_input(0x08, True)] * n)
            elif t == "key":
                press_combo(list(ev.get("k", []))[:4])
    w, h = screen_size()
    cx, cy = cursor_pos()
    return {"cx": cx / max(1, w - 1), "cy": cy / max(1, h - 1)}

# ---------- Chụp màn hình (GDI: chụp + thu nhỏ trong 1 bước, rất nhanh) ----------
gdi32 = ctypes.windll.gdi32
user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = (wt.HWND,)
user32.ReleaseDC.argtypes = (wt.HWND, wt.HDC)
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = (wt.HDC,)
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int)
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = (wt.HDC, wt.HGDIOBJ)
gdi32.DeleteObject.argtypes = (wt.HGDIOBJ,)
gdi32.DeleteDC.argtypes = (wt.HDC,)
gdi32.SetStretchBltMode.argtypes = (wt.HDC, ctypes.c_int)
gdi32.SetBrushOrgEx.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
gdi32.BitBlt.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD)
gdi32.StretchBlt.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.DWORD)
gdi32.GetDIBits.argtypes = (wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT)

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

class Capturer:
    """Mỗi kết nối một bộ chụp riêng; giữ lại DC/bitmap giữa các khung hình."""
    def __init__(self):
        self.size = None
        self.mdc = self.bmp = self.old = None
        self.buf = None

    def _prepare(self, sdc, ow, oh):
        if self.size == (ow, oh):
            return
        self.close()
        self.mdc = gdi32.CreateCompatibleDC(sdc)
        self.bmp = gdi32.CreateCompatibleBitmap(sdc, ow, oh)
        self.old = gdi32.SelectObject(self.mdc, self.bmp)
        self.buf = ctypes.create_string_buffer(ow * oh * 4)
        self.size = (ow, oh)

    def grab(self, x, y, w, h, ow, oh):
        """Chụp vùng (x,y,w,h) của màn hình, thu về kích thước (ow,oh). Trả về bytes BGRX."""
        sdc = user32.GetDC(None)
        try:
            self._prepare(sdc, ow, oh)
            if (ow, oh) == (w, h):
                ok = gdi32.BitBlt(self.mdc, 0, 0, w, h, sdc, x, y, 0x00CC0020)
            else:
                gdi32.SetStretchBltMode(self.mdc, 4)   # HALFTONE: chữ nét hơn khi thu nhỏ
                gdi32.SetBrushOrgEx(self.mdc, 0, 0, None)
                ok = gdi32.StretchBlt(self.mdc, 0, 0, ow, oh, sdc, x, y, w, h, 0x00CC0020)
        finally:
            user32.ReleaseDC(None, sdc)
        if not ok:
            return None
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), ow, -oh, 1, 32, 0, 0, 0, 0, 0, 0)
        gdi32.GetDIBits(self.mdc, self.bmp, 0, oh, self.buf, ctypes.byref(bmi), 0)
        return self.buf.raw

    def close(self):
        if self.mdc:
            gdi32.SelectObject(self.mdc, self.old)
            gdi32.DeleteObject(self.bmp)
            gdi32.DeleteDC(self.mdc)
        self.mdc = self.bmp = self.old = None
        self.size = None

def encode_jpeg(raw, ow, oh, quality):
    if raw is None:
        img = ImageGrab.grab().resize((ow, oh))       # dự phòng
    else:
        img = Image.frombuffer("RGB", (ow, oh), raw, "raw", "BGRX", 0, 1)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()

# ---------- Mật khẩu & phiên ----------
PW_FILE = os.path.join(APP_DIR, "matkhau.txt")
PASSWORD = None
try:
    with open(PW_FILE, "r", encoding="utf-8") as f:
        PASSWORD = f.read().strip() or None
except Exception:
    pass
NEW_PW = PASSWORD is None
if not PASSWORD:
    # tạo mật khẩu cố định 8 số và lưu lại (máy tự khởi động nên mật khẩu không được đổi mỗi lần)
    PASSWORD = "%08d" % secrets.randbelow(100000000)
    try:
        with open(PW_FILE, "w", encoding="utf-8") as f:
            f.write(PASSWORD)
    except Exception:
        pass

TOKENS = set()
FAILS = {}   # ip -> [số lần sai, khóa đến lúc]
GLOBAL_FAILS = []   # thời điểm các lần sai (chống dò mật khẩu qua Internet)
fail_lock = threading.Lock()

# ---------- ID cố định (giống UltraViewer) ----------
ID_FILE = os.path.join(APP_DIR, "id.txt")
MACHINE_ID = None
try:
    with open(ID_FILE, "r", encoding="utf-8") as f:
        MACHINE_ID = re.sub(r"\D", "", f.read())[:9] or None
except Exception:
    pass
if not MACHINE_ID or len(MACHINE_ID) != 9:
    MACHINE_ID = str(100000000 + secrets.randbelow(900000000))
    try:
        with open(ID_FILE, "w", encoding="utf-8") as f:
            f.write(MACHINE_ID)
    except Exception:
        pass
ID_SHOW = "%s %s %s" % (MACHINE_ID[:3], MACHINE_ID[3:6], MACHINE_ID[6:])
NTFY_TOPIC = "https://ntfy.sh/dkm-v1-" + MACHINE_ID

# ---------- Kết nối Internet: Cloudflare Tunnel + bảng tra ID (ntfy.sh) ----------
PUBLIC_URL = None

def _kill_child_with_me(proc):
    """Gắn tiến trình con vào Job Object: đóng cửa sổ chương trình thì cloudflared cũng tắt."""
    try:
        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("a", "b", "c", "d", "e", "f")]
        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]
        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        kernel32.CreateJobObjectW.restype = wt.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        info = EXT()
        info.Basic.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(wt.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
        kernel32.AssignProcessToJobObject(wt.HANDLE(job), wt.HANDLE(int(proc._handle)))
        globals()["_JOB"] = job   # giữ handle tới khi chương trình tắt
    except Exception:
        pass

def find_cloudflared():
    for d in (APP_DIR, RES_DIR):
        p = os.path.join(d, "cloudflared.exe")
        if os.path.exists(p):
            return p
    return None

def publish_url():
    if not PUBLIC_URL:
        return False
    try:
        body = json.dumps({"url": PUBLIC_URL, "t": int(time.time())}).encode("utf-8")
        req = urllib.request.Request(NTFY_TOPIC, data=body, method="POST",
                                     headers={"Title": "dkm", "Cache": "yes"})
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except Exception:
        return False

def tunnel_loop():
    global PUBLIC_URL
    exe = find_cloudflared()
    if not exe:
        print("  [!] Không có cloudflared.exe -> chỉ dùng được trong cùng Wi-Fi.")
        return
    while True:
        try:
            proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:%d" % PORT],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL, creationflags=0x08000000)
            _kill_child_with_me(proc)
            for raw in proc.stderr:
                line = raw.decode("utf-8", "ignore")
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m and m.group(0) != PUBLIC_URL:
                    PUBLIC_URL = m.group(0)
                    time.sleep(3)   # chờ đường hầm sẵn sàng
                    ok = publish_url()
                    print("  [i] %s  Internet: %s" % (time.strftime("%H:%M:%S"),
                          "SẴN SÀNG - điện thoại nhập ID để kết nối" if ok else "đã mở nhưng chưa đăng ký được ID, đang thử lại"))
            proc.wait()
        except Exception as e:
            print("  [!] Lỗi kết nối Internet:", e)
        PUBLIC_URL = None
        print("  [i] Mất kết nối Internet, thử lại sau 10 giây...")
        time.sleep(10)

def republish_loop():
    last_ok = 0
    while True:
        time.sleep(30)
        if PUBLIC_URL and time.time() - last_ok > 20 * 60:   # ntfy.sh giữ tin 12 giờ
            if publish_url():
                last_ok = time.time()

# ---------- WebSocket (tự viết, không cần thư viện) ----------
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

class WsSession:
    def __init__(self, rfile, sock):
        self.rfile, self.sock = rfile, sock
        self.lock = threading.Lock()
        self.alive = True
        self.sem = threading.BoundedSemaphore(2)   # tối đa 2 khung hình đang trên đường đi
        self.cfg = {"q": 50, "w": 1280, "fps": 20}
        self.view = {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0, "pw": 1280}
        self.force = True

    def send(self, data, opcode):
        n = len(data)
        if n < 126:
            head = struct.pack("!BB", 0x80 | opcode, n)
        elif n < 65536:
            head = struct.pack("!BBH", 0x80 | opcode, 126, n)
        else:
            head = struct.pack("!BBQ", 0x80 | opcode, 127, n)
        with self.lock:
            self.sock.sendall(head + data)

    def send_text(self, obj):
        self.send(json.dumps(obj).encode("utf-8"), 0x1)

    def recv(self):
        h = self.rfile.read(2)
        if len(h) < 2:
            return None, None
        op = h[0] & 0x0F
        n = h[1] & 0x7F
        if n == 126:
            n = struct.unpack("!H", self.rfile.read(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self.rfile.read(8))[0]
        if n > 1_000_000:
            return None, None
        mask = self.rfile.read(4) if h[1] & 0x80 else b"\0\0\0\0"
        data = bytearray(self.rfile.read(n))
        for i in range(len(data)):
            data[i] ^= mask[i & 3]
        return op, bytes(data)

def ws_reader(sess):
    while sess.alive:
        op, data = sess.recv()
        if op is None or op == 0x8:
            break
        if op == 0x9:
            sess.send(data, 0xA)
            continue
        if op != 0x1:
            continue
        if data == b"a":   # điện thoại báo đã nhận xong 1 khung hình
            try:
                sess.sem.release()
            except ValueError:
                pass
            continue
        try:
            m = json.loads(data.decode("utf-8"))
        except Exception:
            continue
        t = m.get("t")
        if t == "in":
            handle_events(m.get("ev", []))
        elif t == "view":
            with sess.lock:
                for k in ("x0", "y0", "x1", "y1", "pw"):
                    if k in m:
                        sess.view[k] = float(m[k])
            sess.force = True
        elif t == "cfg":
            with sess.lock:
                sess.cfg["q"] = max(10, min(95, int(m.get("q", 50))))
                sess.cfg["w"] = max(0, min(4000, int(m.get("w", 1280))))
                sess.cfg["fps"] = max(1, min(30, int(m.get("fps", 20))))
            sess.force = True
        elif t == "p":
            sess.send_text({"t": "p", "ts": m.get("ts")})
    sess.alive = False

def ws_sender(sess):
    cap = Capturer()
    prev_raw, prev_key, prev_cur = None, None, None
    last_full, last_ping, fid = 0.0, time.time(), 0
    try:
        while sess.alive:
            if not sess.sem.acquire(timeout=1.0):
                if time.time() - last_ping > 15:
                    sess.send(b"", 0x9)   # giữ kết nối qua Cloudflare
                    last_ping = time.time()
                continue
            sent = False
            t0 = time.time()
            with sess.lock:
                v = dict(sess.view)
                c = dict(sess.cfg)
            try:
                sw, sh = screen_size()
                vx0, vy0 = max(0.0, v["x0"]), max(0.0, v["y0"])
                vx1, vy1 = min(1.0, v["x1"]), min(1.0, v["y1"])
                zoomed = (vx1 - vx0) < 0.97 or (vy1 - vy0) < 0.97
                if not zoomed or t0 - last_full > 4:
                    # cả màn hình (khi phóng to: 4 giây làm mới nền 1 lần, độ nét thấp)
                    x0, y0, x1, y1 = 0.0, 0.0, 1.0, 1.0
                    want = v["pw"] / max(0.05, vx1 - vx0) if not zoomed else 960
                    full = True
                else:
                    mx, my = (vx1 - vx0) * 0.15, (vy1 - vy0) * 0.15
                    x0, y0 = max(0.0, vx0 - mx), max(0.0, vy0 - my)
                    x1, y1 = min(1.0, vx1 + mx), min(1.0, vy1 + my)
                    want = v["pw"] * (x1 - x0) / max(0.01, vx1 - vx0)
                    full = False
                rx, ry = int(x0 * sw), int(y0 * sh)
                rw, rh = max(1, int(x1 * sw) - rx), max(1, int(y1 * sh) - ry)
                ow = min(rw, max(160, int(want)))
                if c["w"] > 0:
                    ow = min(ow, c["w"])
                oh = max(1, round(rh * ow / rw))
                raw = cap.grab(rx, ry, rw, rh, ow, oh)
                key = (rx, ry, rw, rh, ow, oh)
                cx, cy = cursor_pos()
                if raw is not None and raw == prev_raw and key == prev_key and not sess.force:
                    if (cx, cy) != prev_cur:   # chỉ con trỏ đổi chỗ (chuột thật trên máy tính)
                        sess.send_text({"t": "c", "x": cx / max(1, sw - 1), "y": cy / max(1, sh - 1)})
                        prev_cur = (cx, cy)
                else:
                    sess.force = False
                    jpg = encode_jpeg(raw, ow, oh, c["q"])
                    fid += 1
                    head = struct.pack("<IHHHHHHhh", fid, sw, sh, rx, ry, rw, rh,
                                       max(-32768, min(32767, cx)), max(-32768, min(32767, cy)))
                    sess.send(head + jpg, 0x2)
                    sent = True
                    prev_raw, prev_key, prev_cur = raw, key, (cx, cy)
                    if full:
                        last_full = t0
            except (OSError, ConnectionError):
                break
            except Exception:
                time.sleep(0.3)
            finally:
                if not sent:
                    try:
                        sess.sem.release()
                    except ValueError:
                        pass
            time.sleep(max(0.004, 1.0 / c["fps"] - (time.time() - t0)))
    finally:
        sess.alive = False
        cap.close()

# ---------- Máy chủ HTTP ----------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DieuKhienMay/1.0"

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 1_000_000:
            return None
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return None

    def _token_ok(self, qs):
        return qs.get("t", [""])[0] in TOKENS

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            try:
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    body = f.read()
            except Exception:
                body = b"Missing web/index.html"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/info":
            if not self._token_ok(qs):
                return self._json(403, {"ok": False})
            w, h = screen_size()
            self._json(200, {"ok": True, "w": w, "h": h})
        elif u.path == "/ws":
            if not self._token_ok(qs):
                return self._json(403, {"ok": False})
            self._websocket()
        else:
            self._json(404, {"ok": False})

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/login":
            ip = self.headers.get("CF-Connecting-IP") or self.client_address[0]
            now = time.time()
            with fail_lock:
                rec = FAILS.get(ip, [0, 0])
                GLOBAL_FAILS[:] = [t for t in GLOBAL_FAILS if now - t < 600]
                if rec[1] > now:
                    return self._json(429, {"ok": False, "msg": "Sai quá nhiều lần, chờ %d giây" % (rec[1] - now)})
                if len(GLOBAL_FAILS) >= 30:
                    return self._json(429, {"ok": False, "msg": "Có người dò mật khẩu, tạm khóa 10 phút"})
            data = self._read_body() or {}
            if str(data.get("pw", "")).strip() == PASSWORD:
                tok = secrets.token_urlsafe(18)
                TOKENS.add(tok)
                with fail_lock:
                    FAILS.pop(ip, None)
                w, h = screen_size()
                print("  [+] %s  Điện thoại đã kết nối: %s" % (time.strftime("%H:%M:%S"), ip))
                return self._json(200, {"ok": True, "token": tok, "w": w, "h": h})
            with fail_lock:
                GLOBAL_FAILS.append(now)
                rec[0] += 1
                if rec[0] >= 5:
                    rec = [0, now + 60]
                FAILS[ip] = rec
            return self._json(403, {"ok": False, "msg": "Sai mật khẩu"})
        elif u.path == "/input":
            if not self._token_ok(qs):
                return self._json(403, {"ok": False})
            events = self._read_body()
            if not isinstance(events, list):
                return self._json(400, {"ok": False})
            try:
                res = handle_events(events)
            except Exception as e:
                res = {"err": str(e)}
            res["ok"] = True
            self._json(200, res)
        else:
            self._json(404, {"ok": False})

    def _websocket(self):
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or "websocket" not in (self.headers.get("Upgrade") or "").lower():
            return self._json(400, {"ok": False})
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.close_connection = True
        sock = self.connection
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        sess = WsSession(self.rfile, sock)
        th = threading.Thread(target=ws_sender, args=(sess,), daemon=True)
        th.start()
        try:
            ws_reader(sess)
        except Exception:
            pass
        sess.alive = False
        th.join(timeout=3)

# ---------- Khởi động cùng Windows ----------
import winreg
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "DieuKhienMay"
CONFIG_FILE = os.path.join(APP_DIR, "caidat.json")

def startup_cmd():
    if getattr(sys, "frozen", False):
        return '"%s" --startup' % sys.executable
    return '"%s" "%s" --startup' % (sys.executable, os.path.abspath(__file__))

def autostart_get():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, RUN_NAME)[0]
    except OSError:
        return None

def autostart_set(on):
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, startup_cmd())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except OSError:
                    pass
        return True
    except OSError:
        return False

def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(c):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(c, f)
    except Exception:
        pass

def local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips or ["(không tìm thấy - kiểm tra Wi-Fi)"]

def print_banner(ips):
    print("=" * 56)
    print("          ĐIỀU KHIỂN MÁY - ĐANG CHẠY")
    print("=" * 56)
    print("  ID         :  %s     (dùng qua Internet)" % ID_SHOW)
    print("  Địa chỉ IP :  %s     (dùng trong Wi-Fi)" % ips[0])
    for ip in ips[1:]:
        print("                %s" % ip)
    print("  Mật khẩu   :  %s" % PASSWORD)
    print("  Khởi động cùng Windows: %s" % ("BẬT" if autostart_get() else "TẮT"))
    print("-" * 56)
    print("  Phím tắt trong cửa sổ này:")
    print("   [K] Bật/tắt khởi động cùng Windows")
    print("   [P] Đổi mật khẩu      [I] Hiện lại thông tin")
    print("  Đóng cửa sổ này để dừng điều khiển.")
    print("=" * 56)

def console_loop(ips):
    import msvcrt
    global PASSWORD
    while True:
        ch = msvcrt.getwch().lower()
        if ch == "k":
            on = not autostart_get()
            autostart_set(on)
            print("  -> Khởi động cùng Windows: %s" % ("BẬT" if autostart_get() else "TẮT"))
            c = load_config(); c["autostart"] = bool(on); save_config(c)
        elif ch == "p":
            pw = input("  Nhập mật khẩu mới (ít nhất 6 ký tự, Enter để hủy): ").strip()
            if len(pw) >= 6:
                PASSWORD = pw
                try:
                    with open(PW_FILE, "w", encoding="utf-8") as f:
                        f.write(pw)
                    print("  -> Đã đổi mật khẩu.")
                except Exception:
                    print("  -> Không lưu được matkhau.txt (đặt file .exe ở thư mục có quyền ghi).")
            elif pw:
                print("  -> Mật khẩu quá ngắn.")
        elif ch == "i":
            print_banner(ips)

def main():
    startup = "--startup" in sys.argv
    os.system("title Dieu Khien May - dang chay")
    if startup:
        user32.ShowWindow(kernel32.GetConsoleWindow(), 6)   # tự chạy lúc mở máy: thu nhỏ cửa sổ
    # giữ máy không ngủ / tắt màn hình khi đang chạy
    kernel32.SetThreadExecutionState(0x80000000 | 0x00000002 | 0x00000001)
    # khởi động cùng Windows: bật sẵn lần đầu, và cập nhật đường dẫn nếu file .exe bị chuyển chỗ
    c = load_config()
    if "autostart" not in c:
        c["autostart"] = True
        save_config(c)
    if c.get("autostart"):
        if autostart_get() != startup_cmd():
            autostart_set(True)
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError:
        print("Cổng %d đang bị dùng. Có thể chương trình đã chạy rồi." % PORT)
        if not startup:
            input("Nhấn Enter để thoát...")
        return
    srv.daemon_threads = True
    if startup:
        time.sleep(5)   # chờ mạng sẵn sàng sau khi mở máy
    ips = local_ips()
    print_banner(ips)
    if NEW_PW:
        print("  (Mật khẩu cố định đã lưu vào matkhau.txt - nhấn P để đổi)")
    threading.Thread(target=tunnel_loop, daemon=True).start()
    threading.Thread(target=republish_loop, daemon=True).start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        console_loop(ips)
    except (KeyboardInterrupt, EOFError):
        pass

if __name__ == "__main__":
    main()
