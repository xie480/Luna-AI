# memory_boost_ultra.py
# Windows-only aggressive memory optimizer
# Requires: pip install psutil
#
# What it does:
# 1) Self-elevates to Administrator if needed
# 2) Enables SeIncreaseQuotaPrivilege and SeProfileSingleProcessPrivilege
# 3) Empties system working sets
# 4) Purges standby list / low priority standby list
# 5) Flushes system file cache
# 6) Optionally trims top memory processes as a final punch
#
# NOTE:
# This is intentionally aggressive. It can improve the "available memory" number
# fast, but may cause temporary stutter/page faults for active apps.

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from dataclasses import dataclass
from typing import List

import psutil

MB = 1024 * 1024

# --- Windows constants ---
SE_INCREASE_QUOTA_PRIVILEGE = 5
SE_PROFILE_SINGLE_PROCESS_PRIVILEGE = 13

SYSTEM_MEMORY_LIST_INFORMATION = 0x50
SYSTEM_FILECACHE_INFORMATION = 0x51  # only for reference; not used directly

# SYSTEM_MEMORY_LIST_COMMAND values
MemoryEmptyWorkingSets = 2
MemoryFlushModifiedList = 3
MemoryPurgeStandbyList = 4
MemoryPurgeLowPriorityStandbyList = 5

# Process rights
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100

# --- Blocklist: don't touch these ---
BLOCKLIST = {
    "system",
    "registry",
    "idle",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "dwm.exe",
    "explorer.exe",
    "taskmgr.exe",
    "memory_boost_ultra.exe",
    "memory_boost_ultra.py",
    "python.exe",
    "pythonw.exe",
}

# Common large-user-process hints (only used to prioritize)
HINTS = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "idea64.exe",
    "code.exe",
    "java.exe",
    "javaw.exe",
    "pycharm64.exe",
    "wechat.exe",
    "qq.exe",
    "steam.exe",
    "discord.exe",
}

# --- WinAPI ---
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
OpenProcess.restype = ctypes.c_void_p

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [ctypes.c_void_p]
CloseHandle.restype = ctypes.c_int

EmptyWorkingSet = psapi.EmptyWorkingSet
EmptyWorkingSet.argtypes = [ctypes.c_void_p]
EmptyWorkingSet.restype = ctypes.c_int

SetSystemFileCacheSize = kernel32.SetSystemFileCacheSize
SetSystemFileCacheSize.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint32]
SetSystemFileCacheSize.restype = ctypes.c_int

NtSetSystemInformation = ntdll.NtSetSystemInformation
NtSetSystemInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
NtSetSystemInformation.restype = ctypes.c_long

RtlAdjustPrivilege = ntdll.RtlAdjustPrivilege
RtlAdjustPrivilege.argtypes = [ctypes.c_ulong, ctypes.c_ubyte, ctypes.c_ubyte, ctypes.POINTER(ctypes.c_ubyte)]
RtlAdjustPrivilege.restype = ctypes.c_long

IsUserAnAdmin = shell32.IsUserAnAdmin
IsUserAnAdmin.restype = ctypes.c_bool

ShellExecuteW = shell32.ShellExecuteW
ShellExecuteW.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.c_wchar_p,
    ctypes.c_wchar_p,
    ctypes.c_wchar_p,
    ctypes.c_int,
]
ShellExecuteW.restype = ctypes.c_void_p


@dataclass
class ProcInfo:
    pid: int
    name: str
    rss: int
    username: str
    status: str


def human_mb(n: int) -> float:
    return round(n / MB, 1)


def mem_avail_mb() -> float:
    return human_mb(psutil.virtual_memory().available)


def relaunch_as_admin() -> None:
    if os.name != "nt":
        return
    if IsUserAnAdmin():
        return

    script = os.path.abspath(sys.argv[0])
    params = " ".join(f'"{a}"' if " " in a else a for a in sys.argv[1:])
    rc = ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
    # If elevation is triggered, exit the current non-admin process.
    if int(rc) <= 32:
        raise RuntimeError("Failed to relaunch as Administrator.")
    raise SystemExit(0)


def enable_privileges() -> None:
    enabled = ctypes.c_ubyte(0)

    # Needed for cache and some memory operations
    RtlAdjustPrivilege(SE_INCREASE_QUOTA_PRIVILEGE, 1, 0, ctypes.byref(enabled))
    # Needed for memory list operations like empty working sets / standby purge
    RtlAdjustPrivilege(SE_PROFILE_SINGLE_PROCESS_PRIVILEGE, 1, 0, ctypes.byref(enabled))


def nt_success(status: int) -> bool:
    return status >= 0


def nt_memory_list_command(cmd: int) -> bool:
    val = ctypes.c_int(cmd)
    status = NtSetSystemInformation(
        SYSTEM_MEMORY_LIST_INFORMATION,
        ctypes.byref(val),
        ctypes.sizeof(val),
    )
    return nt_success(status)


def flush_file_cache() -> bool:
    # To flush the cache, pass -1 for min/max.
    max_size = ctypes.c_size_t(-1).value
    ok = SetSystemFileCacheSize(max_size, max_size, 0)
    return bool(ok)


def list_processes() -> List[ProcInfo]:
    items: List[ProcInfo] = []
    for p in psutil.process_iter(attrs=["pid", "name", "username", "status", "memory_info"]):
        try:
            info = p.info
            name = (info.get("name") or "").lower()
            if not name:
                continue
            mem = info.get("memory_info")
            rss = int(mem.rss) if mem else 0
            items.append(
                ProcInfo(
                    pid=int(info["pid"]),
                    name=name,
                    rss=rss,
                    username=(info.get("username") or ""),
                    status=(info.get("status") or "").lower(),
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue
    return items


def score_proc(p: ProcInfo, mode: str) -> int:
    score = 0

    if p.name in HINTS:
        score += 100

    if p.rss >= 1000 * MB:
        score += 60
    elif p.rss >= 500 * MB:
        score += 40
    elif p.rss >= 200 * MB:
        score += 20
    elif p.rss >= 100 * MB:
        score += 8

    if mode == "balanced":
        if p.status in {"sleeping", "idle", "disk-sleep"}:
            score += 10
    elif mode == "aggressive":
        score += 20
    elif mode == "extreme":
        score += 40

    if p.name in BLOCKLIST:
        score -= 10000

    return score


def trim_process(pid: int) -> bool:
    h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
    if not h:
        return False
    try:
        ok = EmptyWorkingSet(h)
        return bool(ok)
    finally:
        CloseHandle(h)


def trim_top_processes(mode: str, top_n: int, min_rss_mb: int) -> int:
    me = os.getpid()
    current_user = (psutil.Process().username() or "").lower()

    candidates: List[ProcInfo] = []
    for p in list_processes():
        if p.pid == me:
            continue
        if p.name in BLOCKLIST:
            continue
        if current_user and p.username and current_user not in p.username.lower():
            continue
        if p.rss < min_rss_mb * MB:
            continue
        candidates.append(p)

    candidates.sort(key=lambda x: (score_proc(x, mode), x.rss), reverse=True)

    trimmed = 0
    for p in candidates[:top_n]:
        try:
            ok = trim_process(p.pid)
            print(
                f"[trim] pid={p.pid:<7} rss={human_mb(p.rss):>7}MB "
                f"status={p.status:<12} name={p.name:<20} -> {'ok' if ok else 'failed'}"
            )
            if ok:
                trimmed += 1
            time.sleep(0.03)
        except Exception as e:
            print(f"[warn] pid={p.pid} name={p.name} error={e}")

    return trimmed


def optimize(mode: str, top_n: int, min_rss_mb: int, rounds: int, pause_ms: int) -> None:
    before = mem_avail_mb()
    print(f"[before] available memory: {before} MB")

    total = 0

    for r in range(1, rounds + 1):
        print(f"[round {r}] start")

        # 1) Empty working sets system-wide.
        ok_ws = nt_memory_list_command(MemoryEmptyWorkingSets)
        print(f"  [ws] empty working sets -> {'ok' if ok_ws else 'failed'}")

        # 2) Purge standby list.
        ok_standby = nt_memory_list_command(MemoryPurgeStandbyList)
        print(f"  [standby] purge standby list -> {'ok' if ok_standby else 'failed'}")

        # 3) Purge low-priority standby list.
        ok_low = nt_memory_list_command(MemoryPurgeLowPriorityStandbyList)
        print(f"  [standby-low] purge low-priority standby list -> {'ok' if ok_low else 'failed'}")

        # 4) Flush system file cache.
        ok_cache = flush_file_cache()
        print(f"  [filecache] flush system file cache -> {'ok' if ok_cache else 'failed'}")

        # 5) Optional extreme mode: flush modified list too.
        if mode == "extreme":
            ok_mod = nt_memory_list_command(MemoryFlushModifiedList)
            print(f"  [modified] flush modified list -> {'ok' if ok_mod else 'failed'}")

        # 6) Final pass: trim the heaviest user processes.
        trimmed = trim_top_processes(mode=mode, top_n=top_n, min_rss_mb=min_rss_mb)
        total += trimmed
        print(f"  [process] trimmed {trimmed} processes")

        now = mem_avail_mb()
        print(f"[round {r}] available memory: {now} MB")

        time.sleep(max(0, pause_ms) / 1000.0)

    after = mem_avail_mb()
    print(f"[after] available memory: {after} MB")
    print(f"[summary] total trimmed processes: {total}")


def main() -> int:
    if os.name != "nt":
        print("Windows only.")
        return 2

    parser = argparse.ArgumentParser(description="Aggressive Windows memory optimizer")
    parser.add_argument("--mode", choices=["balanced", "aggressive", "extreme"], default="aggressive")
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--min-rss-mb", type=int, default=120)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--pause-ms", type=int, default=120)
    args = parser.parse_args()

    relaunch_as_admin()
    enable_privileges()

    optimize(
        mode=args.mode,
        top_n=args.top_n,
        min_rss_mb=args.min_rss_mb,
        rounds=args.rounds,
        pause_ms=args.pause_ms,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())