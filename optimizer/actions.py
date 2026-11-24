import os
import re
import winreg
from pathlib import Path

import psutil

from .windows import run, active_plan, guid, is_admin, psjson, powershell, rows

BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
HIGH = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def startup_entries():
    entries = []
    for label, hive in [("Current user", winreg.HKEY_CURRENT_USER), ("All users", winreg.HKEY_LOCAL_MACHINE)]:
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, RUN_KEY, 0, winreg.KEY_READ | view) as key:
                    i = 0
                    while True:
                        try:
                            name, value, kind = winreg.EnumValue(key, i)
                            item = dict(name=name, command=value, type=kind, scope=label, view=view, source="Registry Run")
                            if not any(x['name']==name and x['scope']==label and x['command']==value for x in entries):
                                entries.append(item)
                            i += 1
                        except OSError:
                            break
            except OSError:
                pass
    for scope, root in [("Current user", os.environ.get("APPDATA", "")), ("All users", os.environ.get("PROGRAMDATA", ""))]:
        folder = Path(root) / "Microsoft/Windows/Start Menu/Programs/Startup"
        try:
            for p in folder.iterdir():
                entries.append(dict(name=p.name,command=str(p),scope=scope,source="Startup folder (view only)"))
        except OSError:
            pass
    return entries


def protected(text):
    return bool(re.search(r"windows|microsoft|defender|antivirus|security|vanguard|vgc|vgk|riot|valorant|corsair|icue|cool|fan|asus|armoury|nvidia|amd|realtek|intel|sophos|crowdstrike|sentinel|avast|mcafee|norton|kaspersky|bitdefender|eset|malwarebytes", text, re.I))


def startup_change(store, item, restore=False):
    if item.get('source') != 'Registry Run' or item['scope'] != 'Current user':
        raise ValueError("Only current-user Registry Run entries support reversible changes. Use Task Manager for others.")
    if protected(item['name'] + ' ' + item['command']):
        raise ValueError("Protected system, security, game, or hardware entry. Changes are blocked.")
    key_id = "startup:" + str(item['view']) + ":" + item['name']
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE | item['view']) as key:
        if restore:
            backup = store.get(key_id)
            if not backup:
                raise ValueError("No saved startup backup")
            try:
                winreg.QueryValueEx(key, item['name'])
            except FileNotFoundError:
                pass
            else:
                raise ValueError("Entry already exists; refusing to overwrite it")
            winreg.SetValueEx(key, item['name'], 0, backup['type'], backup['command'])
            actual = winreg.QueryValueEx(key, item['name'])
            if actual != (backup['command'], backup['type']):
                raise RuntimeError("Startup restore verification failed")
            store.set(key_id, None)
        else:
            if store.get(key_id):
                raise ValueError("A rollback already exists; restore it first")
            value, kind = winreg.QueryValueEx(key, item['name'])
            if value != item['command']:
                raise ValueError("Startup entry changed since scan; rescan first")
            store.set(key_id, {**item, 'command':value, 'type':kind})
            winreg.DeleteValue(key, item['name'])
            try:
                winreg.QueryValueEx(key, item['name'])
            except FileNotFoundError:
                pass
            else:
                raise RuntimeError("Startup disable verification failed")
    store.action(key_id, "reverted" if restore else "applied", item)
    return "Startup entry restored and verified" if restore else "Startup entry disabled and verified; previous value saved"


def disabled_startups(store):
    with store.connect() as db:
        return [v for (k,) in db.execute("SELECT key FROM settings WHERE key LIKE 'startup:%'") if (v:=store.get(k))]


def terminate_process(item):
    p = psutil.Process(item['pid'])
    if p.pid in (0, 4, os.getpid()) or abs(p.create_time()-item['created']) > .01:
        raise ValueError("Process changed or is protected; refresh the list")
    exe = p.exe()
    windir = os.path.normcase(os.path.abspath(os.environ.get('SystemRoot', r'C:\Windows')))
    if os.path.normcase(exe).startswith(windir + os.sep) or protected(p.name()+' '+exe):
        raise ValueError("Protected process. This app cannot terminate it.")
    if p.username().casefold() != psutil.Process().username().casefold():
        raise ValueError("Only your own applications can be closed")
    p.terminate()
    try:
        p.wait(5)
    except psutil.TimeoutExpired:
        raise RuntimeError("Process did not exit. No forced kill was issued.")
    return "Process terminated; unsaved application data cannot be restored."


class ActionEngine:
    def __init__(self, store):
        self.store = store

    def execute(self, action, progress=lambda _: None, revert=False):
        progress("Reading current configuration…")
        self.store.action(action, "started", {'revert':revert})
        try:
            if action in ('balanced', 'performance'):
                key = 'rollback:' + action
                current = guid(active_plan())
                previous = self.store.get(key)
                target = previous['previous'] if revert and previous else (BALANCED if action=='balanced' else HIGH)
                if revert and not previous:
                    raise ValueError("No rollback is saved")
                if revert and current != previous['target']:
                    raise ValueError("Power plan changed since apply; refusing to overwrite a later change")
                if not revert:
                    if previous:
                        raise ValueError("Revert the existing change before applying again")
                    if current == target:
                        return "Already configured; no change required"
                    # Durable backup before any change.
                    self.store.set(key, dict(previous=current, target=target))
                progress("Applying power scheme…")
                run(['powercfg.exe', '/setactive', target])
                if guid(active_plan()) != target:
                    raise RuntimeError("Power scheme verification failed; rollback retained")
                if revert:
                    self.store.set(key, None)
                output = 'Active power scheme verified: ' + target
            else:
                if revert:
                    raise ValueError("This action has no reversible setting")
                if not is_admin():
                    raise PermissionError("Administrator rights required. Use Restart as administrator (Windows UAC).")
                progress("Running Windows tool; this may take several minutes…")
                if action == 'storage':
                    drive = os.environ.get('SystemDrive', 'C:')
                    if not re.fullmatch('[A-Za-z]:', drive):
                        raise ValueError('Invalid system drive')
                    # /O selects media-appropriate optimization, not forced SSD defragmentation.
                    output = run(['defrag.exe', drive, '/O', '/U', '/V'], 1800)
                elif action == 'integrity':
                    output = run(['sfc.exe', '/verifyonly'], 1800)
                elif action == 'image_health':
                    output = run(['DISM.exe', '/Online', '/Cleanup-Image', '/ScanHealth'], 1800)
                elif action == 'dns':
                    output = run(['ipconfig.exe', '/flushdns'])
                elif action == 'pagefile':
                    state=psjson('Get-CimInstance Win32_ComputerSystem | Select-Object AutomaticManagedPagefile')
                    key='rollback:pagefile'
                    if state['AutomaticManagedPagefile']:
                        return 'Pagefile policy is already system-managed; no change required'
                    if self.store.get(key):
                        raise ValueError('A pagefile rollback is already saved; review or revert it first')
                    settings=rows(psjson('Get-CimInstance Win32_PageFileSetting | Select-Object Name,InitialSize,MaximumSize'))
                    self.store.set(key,dict(previous=False,settings=settings))
                    powershell('Get-CimInstance Win32_ComputerSystem | Set-CimInstance -Property @{AutomaticManagedPagefile=$true}')
                    actual=psjson('Get-CimInstance Win32_ComputerSystem | Select-Object AutomaticManagedPagefile')
                    if not actual['AutomaticManagedPagefile']:
                        raise RuntimeError('Pagefile policy verification failed; backup retained')
                    output='System-managed pagefile policy verified. Restart required for allocation changes. Previous manual settings saved. No stability or performance improvement is assumed.'
                else:
                    raise ValueError("Unknown action")
                output = "Windows tool completed. Review the diagnostic output; completion alone does not prove a speed improvement or clean integrity.\n" + output
            self.store.action(action, 'reverted' if revert else 'applied', {'output':output})
            return output
        except Exception as e:
            self.store.action(action, 'failed', {'error':str(e)})
            raise

    def revert_pagefile(self, progress=lambda _:None):
        if not is_admin():
            raise PermissionError('Administrator rights required')
        backup=self.store.get('rollback:pagefile')
        if not backup:
            raise ValueError('No pagefile backup saved')
        state=psjson('Get-CimInstance Win32_ComputerSystem | Select-Object AutomaticManagedPagefile')
        if not state['AutomaticManagedPagefile']:
            raise ValueError('Pagefile policy changed since apply; refusing to overwrite it')
        script='Get-CimInstance Win32_ComputerSystem | Set-CimInstance -Property @{AutomaticManagedPagefile=$false}; '
        script+='Get-CimInstance Win32_PageFileSetting | Remove-CimInstance; '
        for item in backup['settings']:
            name=item['Name']
            if not re.fullmatch(r'[A-Za-z]:\\pagefile\.sys',name,re.I):
                raise ValueError('Unusual pagefile path; restore manually using saved settings')
            initial,maximum=int(item['InitialSize']),int(item['MaximumSize'])
            if min(initial,maximum)<0:
                raise ValueError('Invalid saved pagefile size')
            script+=f"New-CimInstance -ClassName Win32_PageFileSetting -Property @{{Name='{name}';InitialSize=[uint32]{initial};MaximumSize=[uint32]{maximum}}} | Out-Null; "
        progress('Restoring saved manual pagefile policy…')
        try:
            powershell(script)
            actual=rows(psjson('Get-CimInstance Win32_PageFileSetting | Select-Object Name,InitialSize,MaximumSize'))
            state=psjson('Get-CimInstance Win32_ComputerSystem | Select-Object AutomaticManagedPagefile')
            if state['AutomaticManagedPagefile'] or sorted(actual,key=lambda x:x['Name'])!=sorted(backup['settings'],key=lambda x:x['Name']):
                raise RuntimeError('Pagefile restore verification failed. Backup retained for manual recovery.')
            self.store.set('rollback:pagefile',None)
            self.store.action('pagefile','reverted',{'output':'Saved manual policy and sizes verified. Restart required.'})
            return 'Previous pagefile configuration restored and verified; restart required.'
        except Exception as e:
            self.store.action('pagefile','failed',{'error':str(e)})
            raise
