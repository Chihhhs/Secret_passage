#!/bin/bash

# 1. 使用 msfvenom 產生 calc.exe shellcode
echo "[*] Generating shellcode..."
msfvenom -p windows/x64/exec CMD=calc.exe EXITFUNC=none -f raw -o calc.bin 2>/dev/null

# 2. 將產生的 binary 轉為 base64 並輸出
echo "[*] Converting to base64..."
base64_result=$(base64 -w 0 calc.bin)

# 3. 顯示結果
echo -e "\n[+] Base64 Shellcode:"
echo "$base64_result"

# 4. 清理暫存檔案
rm calc.bin