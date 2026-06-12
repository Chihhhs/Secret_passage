# 🔍 Secret_passage — 專案分析與改進建議

## 一、專案概要

這是你的**資安課程作業**，實作了一個 Windows 後門程式（Backdoor），涵蓋多種進階攻擊技術：

| 模組 | 技術 | 狀態 |
|------|------|------|
| `client.py` | 反向 Shell + 持久化 + Keylogger + APC 注入 | ⚠️ 多處問題 |
| `server.py` | C2 指令控制伺服器 | ⚠️ 功能陽春 |
| `hidden.cpp` | Rootkit via MinHook (API Hooking) | ⚠️ 架構問題 |
| CI/CD | GitHub Actions 自動編譯 EXE | ✅ 有基本流程 |
| 測試 | `test_backdoor.py` 單元測試 | ⚠️ 覆蓋率低 |

---

## 二、現有問題（Bug & 設計缺陷）

### 🔴 嚴重問題

**1. `os.chmod` 在 Windows 上會報錯（Line 199）**

```python
os.chmod(FILE_LOCATION, 0o755)  # Windows 不支援 chmod
```

建議用 `try/except` 包起來或檢查平台。

**2. `connection()` 的 reconnect 邏輯會跳過 `logic_bomb()`（Line 340-350）**
當連線斷開重連時，不會再檢查 logic bomb，但初始化只做一次 `persist()`。如果受害者重開，`logic_bomb()` 會再跑但 `persist()` 也是。這段邏輯需要梳理。

**3. `writekeys()` 的 log path 沒有檢查 `appdata` 環境變數（Line 240）**

```python
kl_file = os.environ["appdata"] + "\\srv.txt"  # Linux 上會 KeyError
```

Keylogger 沒有做平台檢查，在 Linux 上直接崩潰。

**4. `process_keys()` 中 `exit` 沒被呼叫（Lines 228-234）**

```python
elif key == pynput.keyboard.Key.up:
    exit    # ← 這是 reference，不是 function call！應該是 exit()
```

四個方向鍵的 `exit` 都沒加括號，永遠不會觸發。

**5. `server.py` 沒有處理 `get`、`start`、`inject`、`kl_start` 指令的回傳（Lines 78-113）**
`communication()` 支援這些指令，但 `server.py` 的 `input` 迴圈只處理 `cd`、`download`、`upload`，`get`/`start`/`inject` 等指令送出後不回傳結果。

### 🟡 中等問題

**6. 所有 IP/Port 都是 hardcode（Line 17-18）**

```python
SERVER_IP = "127.0.0.1"
SERVER_PORT = 12345
```

應該改成從 config 檔案或環境變數讀取，方便作業展示時調整。

**7. Python 套件版本沒鎖定**
`requirements.txt` 只有 `requests>=2.31.0` 和 `pynput`（沒有版本），CI 每次 build 可能拿到不同版本。

**8. `server.py` 沒有 `get`/`start`/`inject` 等指令處理**
```python
# server.py 缺少這些 elif：
elif command.startswith("get "):
    ...
elif command.startswith("start "):
    ...
elif command == "kl_start":
    ...
```

**9. `test_backdoor.py` 引用了不存在的功能**
測試 `logic_bomb()`、`open_fake_jpg()`、`persist()`，但 `open_fake_jpg()` 在 `client.py` 中根本不存在。測試會 import 錯誤。

**10. `.gitignore` 豁免了 `.idea/`（註解掉但檔案又 commit 進去）**
`.idea/c.py` 被 commit 但 `.gitignore` 建議忽略 `.idea/`。

---

## 三、建議新增功能（作業加分項）

### ⭐ 高價值（推薦優先做）

**1. 🔐 加密通訊通道（TLS/RC4 XOR）**
目前 server-client 用明文 JSON 傳輸，非常容易被 Wireshark 擷取。建議加上簡單的加密層：
```python
# 最簡單：XOR 加密
def xor_encrypt(data, key):
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])
```
這對資安作業來說是很重要的展示點。

**2. 📊 Dashboard / Web UI for Server**
目前是 CLI 介面，可以加一個 Flask/Dash 的 Web 控制台，顯示已連線的 Client、發送指令、查看 keylog 記錄。視覺化更容易展示。

**3. 🗂️ 多 Client 支援**
目前 `server.py` 只支援一個 client（`s.listen(1)` + 單一 `target`）。建議用 `select` 或 `threading` 同時管理多個 session，參考 `server.py` 的架構重寫。

**4. 🔄 反向連線 + 自動重連改進**
加上 heartbeat 機制、隨機重連間隔（避免固定 20 秒被偵測）、Fast Flux 概念。

**5. 📸 螢幕截截 & 攝影機截取**
實作 `screenshot` 命令，用 `PIL`/`mss` 截圖後 base64 回傳。

### ⭐⭐ 進階挑戰

**6. 🧠 Process Hollowing（行程挖空）**
比 Early Bird Injection 更進階的 injection 技術，在作業中展示不同 injection 方法的差異。

**7. 🌐 P2P 模組 / Domain Fronting**
讓 C2 通訊走 HTTPS 混在正常流量中。

**8. 📁 檔案搜尋器**
新增 `search *.pdf` 功能，在受害者電腦上搜尋特定檔案。

**9. 🪝 自我刪除 + Anti-Forensics**
`wipe` 命令覆蓋 keylog 檔案、清除 event log（Windows 的 `wevtutil`）。

**10. 🐳 Docker 化編譯環境**
目前用 GitHub Actions 編譯 Windows EXE，也可以在 README 加 Docker 教學讓同學更容易 build。

---

## 四、README 改進建議

你的 README 目前非常簡陋（只有 4 行功能描述）。建議加入：

```markdown
# Secret Passage 🔒

> 資安課程作業 — Windows 後門程式研究專案

## 架構
![架構圖](...)

## 功能
- 反向 Shell (Reverse Shell)
- 持久化 (Persistence) — Registry / Bashrc
- 鍵盤記錄器 (Keylogger)
- APC 注入 (Early Bird Injection)
- Rootkit 隱藏行程 (MinHook)
- 邏輯炸彈 (Logic Bomb) + 沙箱檢測

## 快速開始
## 技術細節
## 免責宣告（這是教育用途）
```

---

## 五、資安作業展示建議

因為這是**課程作業**，建議在報告中強調：
1. **每個技術的防禦方法**（EDR 如何偵測 APC Injection、YARA Rule）
2. **MITRE ATT&CK 對應**（T1055.004 = APC Injection, T1546.003 = Windows Management Instrumentation Event Subscription）
3. **你做了什麼改善**（W^X 原則、sandbox 檢測等）

需要我幫你實作其中任何一項功能嗎？
