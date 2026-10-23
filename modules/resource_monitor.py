
"""WhisperShell ORIGINAL: lightweight system RAM monitor."""

import ctypes
import json
import subprocess
import sys
from pathlib import Path


def memory_snapshot():
    """Return physical RAM information in bytes."""

    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        data = MemoryStatus()
        data.dwLength = ctypes.sizeof(data)

        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(
            ctypes.byref(data)
        ):
            raise OSError("Cannot read Windows memory status")

        total = int(data.ullTotalPhys)
        available = int(data.ullAvailPhys)

    elif sys.platform.startswith("linux"):
        values = {}

        for line in Path("/proc/meminfo").read_text().splitlines():
            name, _, value = line.partition(":")
            values[name] = int(value.strip().split()[0]) * 1024

        total = values["MemTotal"]
        available = values["MemAvailable"]

    else:
        raise NotImplementedError("Platform monitor not available yet")

    used = total - available

    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "used_percent": round(100 * used / total, 1),
    }


def top_processes(limit=12):
    """Return processes ordered by resident memory use."""

    limit = max(1, min(int(limit), 50))

    if sys.platform == "win32":
        command = (
            "Get-Process | Sort-Object WorkingSet64 -Descending "
            f"| Select-Object -First {limit} "
            "Id,ProcessName,WorkingSet64 | ConvertTo-Json -Compress"
        )

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )

        records = json.loads(result.stdout)
        if isinstance(records, dict):
            records = [records]

        return [
            {
                "pid": int(item["Id"]),
                "name": item["ProcessName"],
                "memory_bytes": int(item["WorkingSet64"] or 0),
            }
            for item in records
        ]

    if sys.platform.startswith("linux"):
        result = subprocess.run(
            ["ps", "-eo", "pid=,comm=,rss=", "--sort=-rss"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )

        processes = []
        for line in result.stdout.splitlines()[:limit]:
            pid, name, rss = line.split(maxsplit=2)
            processes.append({
                "pid": int(pid),
                "name": name,
                "memory_bytes": int(rss) * 1024,
            })

        return processes

    return []


def gib(value):
    return round(value / (1024 ** 3), 2)


if __name__ == "__main__":
    ram = memory_snapshot()

    print("WHISPERSHELL RESOURCE MONITOR")
    print("Total RAM:    ", gib(ram["total_bytes"]), "GB")
    print("Used RAM:     ", gib(ram["used_bytes"]), "GB")
    print("Available RAM:", gib(ram["available_bytes"]), "GB")
    print("RAM load:     ", ram["used_percent"], "%")
    print()
    print("TOP PROCESSES")

    for process in top_processes():
        mb = process["memory_bytes"] / (1024 ** 2)
        print(f'{process["name"]:<28} {mb:>9.1f} MB')
