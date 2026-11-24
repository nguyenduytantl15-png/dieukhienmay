# Điều Khiển Máy (mức 1: cùng Wi-Fi)

Điều khiển máy tính Windows bằng điện thoại Android, giống UltraViewer nhưng chạy trong mạng Wi-Fi nhà.

## Cấu trúc
- `pc/` – chương trình cho máy tính (`server.py` + `web/index.html`)
- `android/` – app Android (APK)
- `.github/workflows/build.yml` – GitHub tự build ra **APK** và **DieuKhienMay.exe**

## Build trên GitHub
1. Tạo repo mới, tải **toàn bộ** thư mục này lên (giữ nguyên cả thư mục `.github`).
2. Vào tab **Actions** → đợi "Build APK va EXE" chạy xong (khoảng 3–5 phút).
3. Bấm vào lần chạy → mục **Artifacts** → tải `DieuKhienMay-APK` (cho điện thoại) và `DieuKhienMay-PC` (cho máy tính).

## Sử dụng
1. Máy tính: chạy `DieuKhienMay.exe`. Windows hỏi tường lửa → chọn **Allow** (mạng Private).
2. Cửa sổ hiện **IP** và **mật khẩu 6 số**.
3. Điện thoại: mở app, nhập IP + mật khẩu → Kết nối.
   (Không cài app vẫn dùng được: mở Chrome trên điện thoại, vào `http://IP:8765`)

## Mật khẩu cố định (cho máy nhà)
Tạo file `matkhau.txt` đặt cạnh file `.exe`, ghi mật khẩu vào (ví dụ `246810`). Lần sau mật khẩu không đổi, app có thể "Nhớ mật khẩu".

## Thao tác
| Chế độ Touchpad | Chế độ Chạm trực tiếp |
|---|---|
| Kéo 1 ngón: di chuột | Chạm: click tại chỗ chạm |
| Chạm: chuột trái | Kéo 1 ngón: kéo thả / bôi đen |
| **Nhấn giữ: chuột phải** | **Nhấn giữ: chuột phải** |
| Nhấn giữ rồi kéo: kéo thả | |

Cả hai chế độ: chạm 2 ngón = chuột phải, kéo 2 ngón = cuộn, chụm/mở 2 ngón = phóng to. Nút **Phải** trên thanh công cụ cũng là chuột phải. Nút ⌨️ mở bàn phím (gõ được tiếng Việt) và hàng phím Ctrl+C, Alt+Tab, Win…

## Lưu ý
- Nếu Windows Defender chặn file .exe (hay gặp với file đóng gói PyInstaller): chọn "More info → Run anyway", hoặc chạy bằng Python: cài Python, rồi bấm đúp `pc/chay.bat`.
- Không điều khiển được cửa sổ chạy quyền Admin / hộp thoại UAC, trừ khi chạy chương trình bằng "Run as administrator".
- Chỉ hiện màn hình chính nếu máy có nhiều màn hình.
