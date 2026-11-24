import ctypes
import json
import os
import sys
import time
import winreg
from datetime import datetime, timezone
from pathlib import Path

import psutil

from .store import timestamp
from .windows import psjson, rows, run, powershell

PRIOR_EVIDENCE = [
    'Three kernel crashes blocked the RTX 2060 power-down path during hibernation.',
    'One kernel crash blocked the Realtek audio path during shutdown.',
    'Several stacks show paging waits; two analyses implicate the SATA/storage path.',
    'All eight Vanguard application dumps attempted execution at invalid address 0x416a10 outside a loaded module.',
    'No evidence establishes Vanguard as the cause of the kernel crashes.',
    'Xilinx uninstall completed. Original FPGA projects and external source files remain present.',
    'Storage cleanup was performed manually; historical free-space measurements are obsolete.',
]


def import_evidence(store):
    if not store.get('prior_evidence'):
        store.set('prior_evidence', dict(imported=timestamp(),source='User-provided summary of previous diagnostic session',
                                      verified_by_app=False,findings=PRIOR_EVIDENCE))


def recent_events(since):
    # ISO timestamp is serialized and parsed rather than interpolating a free-form query.
    safe=datetime.fromisoformat(since).astimezone(timezone.utc).isoformat()
    return rows(psjson("$t=[datetime]::Parse('"+safe+"').ToLocalTime(); $f=@(@{LogName='System';StartTime=$t;Id=1001,41,6008},@{LogName='Application';StartTime=$t;Id=1000,1001,1002}); foreach($q in $f){ Get-WinEvent -FilterHashtable $q -MaxEvents 100 -ErrorAction SilentlyContinue | Select-Object @{n='Time';e={$_.TimeCreated.ToString('o')}},Id,ProviderName,Message };",60))


def transition_events(since):
    safe=datetime.fromisoformat(since).astimezone(timezone.utc).isoformat()
    return rows(psjson("$t=[datetime]::Parse('"+safe+"').ToLocalTime(); Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Diagnostics-Performance/Operational';Id=100,200,300,400;StartTime=$t} -MaxEvents 12 -ErrorAction SilentlyContinue | ForEach-Object { $x=[xml]$_.ToXml(); $v=@{}; foreach($d in $x.Event.EventData.Data){$v[$d.Name]=$d.'#text'}; [pscustomobject]@{Id=$_.Id;Time=$_.TimeCreated.ToString('o');Data=$v} }",45))


def observe(seconds=10, progress=lambda _:None):
    before=psutil.disk_io_counters()
    cpus=[]
    for i in range(seconds):
        progress(f'Observing paging, storage and CPU · {i+1}/{seconds} s')
        cpus.append(psutil.cpu_percent(interval=1))
    after=psutil.disk_io_counters()
    result={'cpu_percent_samples':cpus, 'memory_percent':psutil.virtual_memory().percent,
            'observed_seconds':seconds,'captured_at':timestamp()}
    if before and after:
        reads=after.read_count-before.read_count
        writes=after.write_count-before.write_count
        result.update(disk_read_latency_ms=(after.read_time-before.read_time)/reads if reads else None,
                      disk_write_latency_ms=(after.write_time-before.write_time)/writes if writes else None,
                      disk_read_operations=reads,disk_write_operations=writes)
    try:
        result['paging']=psjson('Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory | Select-Object PagesInputPersec,PagesOutputPersec,PageReadsPersec,PageWritesPersec,AvailableMBytes,CommittedBytes,CommitLimit')
    except Exception as e:
        result['paging_error']=str(e)
    result['interpretation']='Observed load only. Disk latency is aggregated across devices. Paging waits in old dumps do not establish a pagefile fault.'
    return result


def initiate(store, mode, app_root):
    if mode not in ('restart','shutdown','sleep','hibernate'):
        raise ValueError('Unknown transition')
    if store.get('pending_transition'):
        raise ValueError('Resolve the saved transition test first')
    pending=dict(mode=mode,started=timestamp(),boot_before=psutil.boot_time(),
                 state='requested',notes='Desktop interruptions are explicitly initiated by the user. Wall elapsed time includes time off/asleep and user delay.')
    store.set('pending_transition',pending)
    store.action('transition:'+mode,'started',pending)
    if mode in ('restart','shutdown'):
        # A user-level one-time launch, never a service or scheduled privileged task.
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\RunOnce') as key:
            winreg.SetValueEx(key,'PCOptimizerResume',0,winreg.REG_SZ,
                '"'+sys.executable+'" "'+str(Path(app_root)/'main.py')+'"')
        try:
            run(['shutdown.exe','/r' if mode=='restart' else '/s','/t','15','/d','p:0:0','/c','PC Optimizer user-initiated stability test'])
        except Exception:
            clear_transition(store)
            raise
        return 'Scheduled in 15 seconds. Save your work. Cancel transition is available before shutdown begins.'
    try:
        # Standby / hibernation via documented powrprof API. No force or wake-event override.
        api=ctypes.WinDLL('powrprof',use_last_error=True)
        api.SetSuspendState.argtypes=[ctypes.c_ubyte,ctypes.c_ubyte,ctypes.c_ubyte]
        api.SetSuspendState.restype=ctypes.c_ubyte
        if not api.SetSuspendState(mode=='hibernate',False,False):
            raise ctypes.WinError(ctypes.get_last_error())
        return 'Suspend API returned. Use Collect transition result to examine resume events.'
    except Exception:
        clear_transition(store)
        raise


def clear_transition(store):
    store.set('pending_transition',None)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\RunOnce',0,winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key,'PCOptimizerResume')
    except OSError:
        pass


def cancel_transition(store):
    pending=store.get('pending_transition')
    if not pending:
        return 'No transition is pending'
    if pending['mode'] in ('shutdown','restart'):
        run(['shutdown.exe','/a'])
    store.action('transition:'+pending['mode'],'cancelled',pending)
    clear_transition(store)
    return 'Transition cancelled and saved test cleared'


def collect(store, completed):
    pending=store.get('pending_transition')
    if not pending:
        raise ValueError('No pending transition test')
    events=recent_events(pending['started'])
    try: durations=transition_events(pending['started'])
    except Exception as e: durations={'unavailable':str(e)}
    output={**pending,'collected':timestamp(),'user_reports_completed':completed,
            'boot_changed':abs(psutil.boot_time()-pending['boot_before'])>1,
            'wall_elapsed_seconds':(datetime.now(timezone.utc)-datetime.fromisoformat(pending['started'])).total_seconds(),
            'new_events':events,'transition_events':durations,
            'conclusion':'Single observation. No driver causality established. Event 41 indicates an unclean restart, not necessarily a bugcheck.'}
    store.save_run('stability:'+pending['mode'],output)
    clear_transition(store)
    return output
