import ctypes

kernel32 = ctypes.windll.kernel32

# 設定 GetModuleHandleW 這個 API 的規則
kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p] # 輸入參數必須是寬字元字串
kernel32.GetModuleHandleW.restype = ctypes.c_void_p    # 回傳值是一個 memory 指標

# 安全地呼叫
handle = kernel32.GetModuleHandleW(None)
print(f"目前模組的 memory 位置代碼: {handle}")

# 建立一個 C 型態的 32位元整數，初始值為 0
count = ctypes.c_long(0)

# 假設有一個 Windows API 需要傳入 count 的指標來修改它
# kernel32.SomeFunction(ctypes.byref(count))

# 獲取該變數在 memory 中的實際地址
memory_address = ctypes.addressof(count)
print(f"該變數的 memory 地址為: {memory_address}")