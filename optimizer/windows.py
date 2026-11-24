"""Bounded subprocesses and read-only Windows inventory. No shell interpolation."""
import base64
import ctypes
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def run(args, timeout=30):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                       errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout or f"Exit code {p.returncode}")[-6000:])
    return p.stdout.strip()


def powershell(script, timeout=60):
    encoded = base64.b64encode(("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script).encode("utf-16le")).decode()
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], timeout)


def psjson(script, timeout=60):
    raw = powershell("& { " + script + " } | ConvertTo-Json -Depth 7 -Compress", timeout)
    return json.loads(raw) if raw else None


def rows(value):
    return value if isinstance(value, list) else ([value] if value else [])


def is_admin():
    return os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def guid(text):
    match = re.search(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", text)
    if not match:
        raise ValueError("No valid power scheme GUID returned")
    return match.group(0).lower()


def active_plan():
    return run(["powercfg.exe", "/getactivescheme"])


def inventory():
    data = {}
    queries = {
        "cpu": "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed",
        "board": "Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product,Version",
        "bios": "Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion,@{n='ReleaseDate';e={$_.ReleaseDate.ToString('yyyy-MM-dd')}}",
        "os": "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture",
        "memory": "Get-CimInstance Win32_PhysicalMemory | Select-Object Manufacturer,PartNumber,Capacity,Speed,ConfiguredClockSpeed",
        "disks": "Get-PhysicalDisk | Select-Object FriendlyName,MediaType,HealthStatus,OperationalStatus,Size,DeviceId",
        "health": "Get-PhysicalDisk | Get-StorageReliabilityCounter | Select-Object DeviceId,Temperature,Wear,ReadErrorsTotal,WriteErrorsTotal,PowerOnHours",
        "gpu": "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM",
        "network": "Get-NetAdapter | Select-Object Name,InterfaceDescription,Status,LinkSpeed,DriverVersion",
        "pagefile_policy": "Get-CimInstance Win32_ComputerSystem | Select-Object AutomaticManagedPagefile",
        "pagefile_usage": "Get-CimInstance Win32_PageFileUsage | Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage",
        "pagefile_settings": "Get-CimInstance Win32_PageFileSetting | Select-Object Name,InitialSize,MaximumSize",
    }
    # One PowerShell process; isolate unsupported providers so remaining data survives.
    script = "$r=@{}; "
    for key, query in queries.items():
        script += f"try {{$r['{key}']=@({query})}} catch {{$r['{key}_error']=$_.Exception.Message}}; "
    script += "$r"
    try:
        data = psjson(script, 90) or {}
    except Exception as e:
        data["error"] = str(e)
    try:
        data["power"] = active_plan()
    except Exception as e:
        data["power"] = str(e)
    data["compiler"] = shutil.which("cl.exe") or shutil.which("g++.exe") or shutil.which("clang++.exe")
    data["windbg"] = shutil.which("windbg.exe") or shutil.which("WinDbgX.exe")
    return data


def driver_inventory():
    return rows(psjson("Get-CimInstance Win32_PnPSignedDriver | Where-Object {$_.DeviceName} | Select-Object DeviceName,DeviceID,Manufacturer,DriverProviderName,DriverVersion,@{n='DriverDate';e={if($_.DriverDate){$_.DriverDate.ToString('yyyy-MM-dd')}}},DeviceClass,IsSigned", 90))


def update_search():
    # Read-only Windows Update Agent search. No download, installation, or reboot.
    return rows(psjson("$s=New-Object -ComObject Microsoft.Update.Session; $r=$s.CreateUpdateSearcher().Search('IsInstalled=0 and IsHidden=0'); @($r.Updates | ForEach-Object { [pscustomobject]@{Title=$_.Title; Type=$_.Type; Date=$_.LastDeploymentChangeTime.ToString('yyyy-MM-dd'); Description=$_.Description; ID=$_.Identity.UpdateID} })", 240))


def stability():
    return rows(psjson("$logs=@(@{LogName='System';Level=1,2;StartTime=(Get-Date).AddDays(-14)},@{LogName='Application';Level=1,2;StartTime=(Get-Date).AddDays(-14)}); foreach($f in $logs){Get-WinEvent -FilterHashtable $f -MaxEvents 60 -ErrorAction SilentlyContinue | Select-Object @{n='Time';e={$_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss')}},Id,ProviderName,LevelDisplayName,Message}", 60))


def boot_measurement():
    return psjson("$e=Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Diagnostics-Performance/Operational';Id=100} -MaxEvents 1; $x=[xml]$e.ToXml(); $v=@{}; foreach($d in $x.Event.EventData.Data){$v[$d.Name]=$d.'#text'}; [pscustomobject]@{milliseconds=[double]$v['BootTime']; event_time=$e.TimeCreated.ToString('o'); source='Diagnostics-Performance event 100'}")


OFFICIAL = {
    "AMD chipset": "https://www.amd.com/en/support/download/drivers.html",
    "NVIDIA graphics": "https://www.nvidia.com/en-us/drivers/",
    "ASUS board / audio / LAN / Wi-Fi / Bluetooth": "https://www.asus.com/support/download-center/",
    "Windows Update": "ms-settings:windowsupdate",
    "C++ Build Tools": "https://visualstudio.microsoft.com/visual-cpp-build-tools/",
    "PresentMon": "https://github.com/GameTechDev/PresentMon/releases",
    "GPU benchmark (UNIGINE)": "https://benchmark.unigine.com/superposition",
    "WinDbg": "https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/",
}


def firmware_url(board):
    # Exact non-II model only; never substitute a similar motherboard firmware.
    product = str(board).strip().upper()
    if product == "ROG STRIX B550-F GAMING (WI-FI)":
        return "https://rog.asus.com/motherboards/rog-strix/rog-strix-b550-f-gaming-wi-fi-model/helpdesk_bios/"
    return OFFICIAL["ASUS board / audio / LAN / Wi-Fi / Bluetooth"]
