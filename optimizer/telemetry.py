import csv
import ctypes
import io
import os
import shutil
import socket
import statistics
import time
from collections import deque

import psutil

from .windows import run, psjson, rows


def ping(host="1.1.1.1", timeout=700):
    """ICMP through iphlpapi; return milliseconds or None. No localized text parsing."""
    if os.name != "nt":
        return None
    class Reply(ctypes.Structure):
        _fields_ = [("Address", ctypes.c_ulong), ("Status", ctypes.c_ulong),
                    ("RoundTripTime", ctypes.c_ulong), ("DataSize", ctypes.c_ushort),
                    ("Reserved", ctypes.c_ushort), ("Data", ctypes.c_void_p),
                    ("Options", ctypes.c_ubyte * 16)]
    api = ctypes.WinDLL("iphlpapi")
    api.IcmpCreateFile.restype = ctypes.c_void_p
    api.IcmpSendEcho.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
        ctypes.c_ushort, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
    api.IcmpCloseHandle.argtypes = [ctypes.c_void_p]
    handle = api.IcmpCreateFile()
    if handle == ctypes.c_void_p(-1).value:
        return None
    try:
        address = int.from_bytes(socket.inet_aton(host), "little")
        payload = ctypes.create_string_buffer(b"PCOptimizer")
        buf = ctypes.create_string_buffer(256)
        n = api.IcmpSendEcho(handle, address, payload, 11, None, buf, len(buf), timeout)
        reply = Reply.from_buffer(buf)
        return float(reply.RoundTripTime) if n and reply.Status == 0 else None
    finally:
        api.IcmpCloseHandle(handle)


def network_stats(samples):
    good = [x for x in samples if x is not None]
    return {"latency_ms": statistics.mean(good) if good else None,
            "jitter_ms": statistics.mean([abs(b-a) for a,b in zip(good, good[1:])]) if len(good)>1 else None,
            "loss_percent": 100 * (len(samples)-len(good))/len(samples) if samples else None,
            "sent": len(samples), "received": len(good)}


class Telemetry:
    def __init__(self):
        self.last_time = time.monotonic()
        self.net = psutil.net_io_counters()
        self.disk = psutil.disk_io_counters()
        self.probes = deque(maxlen=30)
        self.count = 0
        self.sensor = {"cpu_temp": None, "cpu_clock_sensor": None}
        self.gpu_exe = shutil.which("nvidia-smi.exe")
        if not self.gpu_exe:
            candidate = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "nvidia-smi.exe")
            if os.path.exists(candidate):
                self.gpu_exe = candidate

    def sample(self):
        now = time.monotonic()
        dt = max(.1, now-self.last_time)
        mem = psutil.virtual_memory()
        net, disk = psutil.net_io_counters(), psutil.disk_io_counters()
        freq = psutil.cpu_freq()
        result = dict(cpu=psutil.cpu_percent(), ram=mem.percent, ram_used=mem.used,
            ram_total=mem.total, cpu_mhz=freq.current if freq else None,
            upload=(net.bytes_sent-self.net.bytes_sent)/dt,
            download=(net.bytes_recv-self.net.bytes_recv)/dt,
            disk_read=(disk.read_bytes-self.disk.read_bytes)/dt if disk and self.disk else None,
            disk_write=(disk.write_bytes-self.disk.write_bytes)/dt if disk and self.disk else None,
            disk_busy=min(100, max(0,(disk.busy_time-self.disk.busy_time)/dt/10)) if disk and self.disk and hasattr(disk,'busy_time') else None,
            uptime=time.time()-psutil.boot_time(), processes=len(psutil.pids()))
        self.last_time, self.net, self.disk = now, net, disk
        self.count += 1
        if self.count % 3 == 1:
            self.probes.append(ping())
        result["network"] = network_stats(list(self.probes))
        result["gpu"] = {}
        if self.gpu_exe:
            try:
                fields = "name,utilization.gpu,temperature.gpu,clocks.current.graphics,memory.used,memory.total,driver_version"
                raw = run([self.gpu_exe, "--query-gpu="+fields, "--format=csv,noheader,nounits"], 3)
                v = next(csv.reader(io.StringIO(raw)))
                def num(x):
                    try: return float(x.strip())
                    except ValueError: return None
                result["gpu"] = dict(name=v[0].strip(), utilization=num(v[1]), temperature=num(v[2]),
                    clock=num(v[3]), memory_used=num(v[4]), memory_total=num(v[5]), driver=v[6].strip())
            except Exception as e:
                result["gpu_error"] = str(e)
        if self.count % 15 == 1:
            try:
                sensors = rows(psjson("Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor | Where-Object {$_.SensorType -eq 'Temperature' -and $_.Name -match 'CPU Package|CPU CCD|CPU Tctl'} | Select-Object Name,Value", 3))
                self.sensor["cpu_temp"] = max([float(s["Value"]) for s in sensors], default=None)
            except Exception:
                self.sensor["cpu_temp"] = None
        result.update(self.sensor)
        result["volumes"] = []
        for part in psutil.disk_partitions():
            if "fixed" in part.opts or part.fstype in ("NTFS", "ReFS"):
                try:
                    u = psutil.disk_usage(part.mountpoint)
                    result["volumes"].append(dict(path=part.mountpoint, total=u.total, free=u.free, percent=u.percent))
                except OSError:
                    pass
        return result


def process_list():
    result = []
    for p in psutil.process_iter(["pid", "name", "memory_info", "username", "exe", "create_time"]):
        try:
            result.append(dict(pid=p.pid, name=p.info['name'], cpu=p.cpu_percent(),
                memory=p.info['memory_info'].rss if p.info['memory_info'] else 0,
                user=p.info['username'], exe=p.info['exe'], created=p.info['create_time']))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return sorted(result, key=lambda p: p['memory'], reverse=True)


def publisher(path):
    if not path:
        return "Unavailable (access restricted)"
    escaped = path.replace("'", "''")
    return psjson(f"$f=Get-Item -LiteralPath '{escaped}'; $s=Get-AuthenticodeSignature -LiteralPath '{escaped}'; [pscustomobject]@{{Company=$f.VersionInfo.CompanyName; SignatureStatus=[string]$s.Status; Signer=if($s.SignerCertificate){{$s.SignerCertificate.Subject}}else{{'Unsigned'}}}}")
