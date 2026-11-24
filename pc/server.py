# -*- coding: utf-8 -*-
"""
Điều Khiển Máy - chương trình chạy trên máy tính Windows.
Điện thoại (cùng Wi-Fi) kết nối vào để xem màn hình và điều khiển chuột/bàn phím.
Chạy: python server.py   (cần: pip install pillow)
"""
import sys, os, io, json, time, secrets, socket, threading

if os.name != "nt":
    print("Chương trình này chỉ chạy trên Windows.")
    sys.exit(1)

import ctypes
import ctypes.wintypes as wt
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from PIL import ImageGrab, Image, ImageDraw

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

# ---------- Chụp màn hình ----------
CURSOR_SHAPE = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]

def grab_jpeg(quality, max_w):
    img = ImageGrab.grab()   # màn hình chính
    W, H = img.size
    # vẽ con trỏ chuột (ảnh chụp không có sẵn con trỏ)
    cx, cy = cursor_pos()
    sw, sh = screen_size()
    if sw and sh:
        cx = cx * W / sw
        cy = cy * H / sh
    k = max(1.0, W / 1100.0)
    pts = [(cx + x * k, cy + y * k) for x, y in CURSOR_SHAPE]
    d = ImageDraw.Draw(img)
    d.polygon(pts, fill=(255, 255, 255), outline=(0, 0, 0))
    d.line(pts + [pts[0]], fill=(0, 0, 0), width=max(1, int(k)))
    if max_w and W > max_w:
        img = img.resize((max_w, int(H * max_w / W)), Image.BILINEAR)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()

# ---------- Mật khẩu & phiên ----------
PW_FILE = os.path.join(APP_DIR, "matkhau.txt")
PASSWORD = None
try:
    with open(PW_FILE, "r", encoding="utf-8") as f:
        PASSWORD = f.read().strip() or None
except Exception:
    pass
FIXED_PW = PASSWORD is not None
if not PASSWORD:
    PASSWORD = "%06d" % secrets.randbelow(1000000)

TOKENS = set()
FAILS = {}   # ip -> [số lần sai, khóa đến lúc]
fail_lock = threading.Lock()

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
        elif u.path == "/stream":
            if not self._token_ok(qs):
                return self._json(403, {"ok": False})
            self._stream(qs)
        else:
            self._json(404, {"ok": False})

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/login":
            ip = self.client_address[0]
            now = time.time()
            with fail_lock:
                rec = FAILS.get(ip, [0, 0])
                if rec[1] > now:
                    return self._json(429, {"ok": False, "msg": "Sai quá nhiều lần, chờ %d giây" % (rec[1] - now)})
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

    def _stream(self, qs):
        def num(key, default, lo, hi):
            try:
                return max(lo, min(hi, int(qs.get(key, [default])[0])))
            except Exception:
                return default
        quality = num("q", 50, 10, 95)
        max_w = num("w", 1280, 0, 4000)
        fps = num("fps", 12, 1, 30)
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store, no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        last, last_sent = None, 0
        try:
            self.wfile.write(b"--frame\r\n")
            while True:
                t0 = time.time()
                try:
                    jpg = grab_jpeg(quality, max_w)
                except Exception:
                    time.sleep(0.5)   # ví dụ: màn hình khóa / hộp thoại UAC
                    continue
                if jpg != last or t0 - last_sent > 2:
                    self.wfile.write(b"Content-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpg))
                    self.wfile.write(jpg)
                    self.wfile.write(b"\r\n--frame\r\n")
                    self.wfile.flush()
                    last, last_sent = jpg, t0
                time.sleep(max(0.0, 1.0 / fps - (time.time() - t0)))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
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

def main():
    os.system("title Dieu Khien May - dang chay")
    # giữ máy không ngủ / tắt màn hình khi đang chạy
    kernel32.SetThreadExecutionState(0x80000000 | 0x00000002 | 0x00000001)
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError:
        print("Cổng %d đang bị dùng. Có thể chương trình đã chạy rồi." % PORT)
        input("Nhấn Enter để thoát...")
        return
    srv.daemon_threads = True
    ips = local_ips()
    print("=" * 52)
    print("        ĐIỀU KHIỂN MÁY - ĐANG CHẠY")
    print("=" * 52)
    print("  Địa chỉ IP :  %s" % ips[0])
    for ip in ips[1:]:
        print("                %s" % ip)
    print("  Cổng       :  %d" % PORT)
    print("  Mật khẩu   :  %s%s" % (PASSWORD, "  (cố định từ matkhau.txt)" if FIXED_PW else ""))
    print("-" * 52)
    print("  Điện thoại phải dùng CHUNG Wi-Fi với máy này.")
    print("  Nếu Windows hỏi tường lửa: chọn Cho phép (Allow).")
    print("  Đóng cửa sổ này để dừng điều khiển.")
    print("=" * 52)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
