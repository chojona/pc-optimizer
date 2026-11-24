"""Bounded real workloads. Results identify caching and Python overhead explicitly."""
import csv
import hashlib
import json
import math
import os
import random
import shutil
import statistics
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import psutil

from .telemetry import ping, network_stats
from .windows import boot_measurement, run

PARAMETERS = {"protocol": 1, "repeats": 3, "cpu_iterations": 180000,
              "cpu_workers": min(4, os.cpu_count() or 1), "memory_mib": 32,
              "memory_copies": 48, "disk_mib": 64, "random_ops": 512,
              "network_host": "1.1.1.1", "network_count": 15}
TESTS = {
    'cpu_single': ('CPU · single worker', 'hashes/s', True),
    'cpu_multi': ('CPU · multiple workers', 'hashes/s', True),
    'memory': ('Memory · Python buffer copy', 'MiB/s', True),
    'disk': ('Storage · cached file I/O', 'MiB/s', True),
    'network': ('Network · ICMP probes', 'ms', False),
    'idle': ('Idle · 5-second observation', '%', False),
    'boot': ('Boot · latest recorded Windows event', 'ms', False),
    'compile': ('C++ · compilation only', 's', False),
}


class Cancelled(Exception):
    pass


def cpu_work(iterations):
    value = b'PCOptimizer deterministic CPU workload v1'
    start = time.perf_counter()
    for _ in range(iterations):
        value = hashlib.sha256(value).digest()
    return time.perf_counter()-start


def metric(samples, unit, higher, **extra):
    return dict(value=statistics.median(samples), unit=unit, higher=higher,
        samples=samples, cv=statistics.stdev(samples)/statistics.mean(samples) if len(samples)>1 and statistics.mean(samples) else 0, **extra)


def fingerprint(hardware):
    # Exclude settings intended to change; retain hardware, OS and driver identities.
    stable = {k:hardware.get(k) for k in ('cpu','board','bios','os','memory','disks','gpu')}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


class BenchmarkEngine:
    def __init__(self, store, hardware, temp_root, parameters=None):
        self.store, self.hardware, self.temp_root = store, hardware, Path(temp_root)
        self.parameters = dict(parameters or PARAMETERS)
        self.cancel = threading.Event()

    def check(self):
        if self.cancel.is_set():
            raise Cancelled('Cancelled between bounded benchmark operations')

    def suite(self, selected, kind, progress=lambda _:None):
        params = self.parameters.copy()
        output = dict(hardware=self.hardware, fingerprint=fingerprint(self.hardware), parameters=params,
                      optimization_state=self.store.actions()[:100], results={}, errors={}, complete=False,
                      notes='Close other workloads and use AC power. File I/O uses OS caches; it is not raw device throughput.')
        for test in selected:
            if self.cancel.is_set():
                output['errors']['cancelled'] = 'Stopped by user; partial results retained'
                break
            progress('Running ' + TESTS[test][0])
            try:
                output['results'][test] = self.execute(test)
            except Cancelled as e:
                output['errors']['cancelled'] = str(e)
                break
            except Exception as e:
                output['errors'][test] = str(e)
        output['complete'] = not output['errors']
        output['id'] = self.store.save_run(kind, output)
        return output

    def execute(self, test):
        p = self.parameters
        samples = []
        if test in ('cpu_single', 'cpu_multi'):
            workers = 1 if test=='cpu_single' else p['cpu_workers']
            if workers == 1:
                for _ in range(p['repeats']):
                    self.check()
                    samples.append(p['cpu_iterations']/cpu_work(p['cpu_iterations']))
            else:
                with ProcessPoolExecutor(max_workers=workers) as pool:
                    # Warm process creation before timing; task startup remains part of this protocol.
                    list(pool.map(cpu_work, [1000]*workers))
                    for _ in range(p['repeats']):
                        self.check()
                        start = time.perf_counter()
                        list(pool.map(cpu_work, [p['cpu_iterations']]*workers))
                        samples.append(p['cpu_iterations']*workers/(time.perf_counter()-start))
            return metric(samples, 'hashes/s', True, workers=workers, workload='Python SHA-256 chain, protocol v1')
        if test == 'memory':
            source = bytearray(os.urandom(p['memory_mib']*1024*1024))
            target = bytearray(len(source))
            for _ in range(p['repeats']):
                self.check()
                start = time.perf_counter()
                for _ in range(p['memory_copies']):
                    target[:] = source
                samples.append(p['memory_mib']*p['memory_copies']/(time.perf_counter()-start))
            return metric(samples,'MiB/s',True, workload='Python bytearray copy; includes runtime/cache effects')
        if test == 'disk':
            self.temp_root.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.temp_root).free < (p['disk_mib']+512)*1024*1024:
                raise RuntimeError('At least test size + 512 MiB free space required')
            detail = {k:[] for k in ('sequential_write','sequential_read','random_write_iops','random_read_iops')}
            block = os.urandom(1024*1024)
            rng = random.Random(42)
            with tempfile.TemporaryDirectory(prefix='pcopt-', dir=self.temp_root) as folder:
                path = Path(folder)/'bounded-test.bin'
                for _ in range(p['repeats']):
                    self.check()
                    with path.open('w+b', buffering=0) as f:
                        start=time.perf_counter()
                        for _ in range(p['disk_mib']):
                            self.check()
                            f.write(block)
                        os.fsync(f.fileno())
                        detail['sequential_write'].append(p['disk_mib']/(time.perf_counter()-start))
                        f.seek(0)
                        start=time.perf_counter()
                        while f.read(1024*1024): self.check()
                        detail['sequential_read'].append(p['disk_mib']/(time.perf_counter()-start))
                        for mode in ('write','read'):
                            start=time.perf_counter()
                            for _ in range(p['random_ops']):
                                self.check()
                                f.seek(rng.randrange(p['disk_mib']*256)*4096)
                                if mode=='write': f.write(block[:4096])
                                else: f.read(4096)
                            if mode=='write': os.fsync(f.fileno())
                            detail['random_'+mode+'_iops'].append(p['random_ops']/(time.perf_counter()-start))
            volume = str(self.temp_root.resolve().anchor)
            return metric(detail['sequential_read'],'MiB/s',True,detail=detail,volume=volume,
                          workload='Cached OS file I/O; writes flushed once per phase. 4 KiB random operations. Not raw SSD speeds.')
        if test == 'network':
            probes=[]
            for _ in range(p['network_count']):
                self.check()
                probes.append(ping(p['network_host']))
                time.sleep(.1)
            stats=network_stats(probes)
            if stats['latency_ms'] is None:
                raise RuntimeError(f"No ICMP replies from {p['network_host']}; loss 100%. Network may block ICMP.")
            return metric([x for x in probes if x is not None], 'ms', False, **stats, target=p['network_host'])
        if test == 'idle':
            for _ in range(5):
                self.check()
                samples.append(psutil.cpu_percent(interval=1))
            return metric(samples,'%',False, memory_percent=psutil.virtual_memory().percent,
                          note='Observed workload, not guaranteed idle; close applications first.')
        if test == 'boot':
            event=boot_measurement()
            if not event or not event.get('milliseconds'):
                raise RuntimeError('No readable boot timing event. Enable Diagnostics-Performance logging or run as administrator.')
            return metric([event.pop('milliseconds')],'ms',False, **event)
        if test == 'compile':
            compiler=self.hardware.get('compiler')
            if not compiler or not Path(compiler).is_file():
                raise RuntimeError('C++ compiler unavailable on PATH. Install official Build Tools, then launch from Developer Command Prompt.')
            version=run([compiler, '--version']) if 'cl.exe' != Path(compiler).name.lower() else run(['cmd.exe','/d','/c', '"'+compiler+'" 2>&1'],10)
            self.temp_root.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='pcopt-cpp-', dir=self.temp_root) as d:
                src=Path(d)/'benchmark.cpp'
                src.write_text('\n'.join(f'int f{i}(int x){{return (x*{i+1}) ^ (x >> 2);}}' for i in range(3000)))
                for _ in range(p['repeats']):
                    self.check()
                    obj=Path(d)/'benchmark.obj'
                    args=[compiler,'/nologo','/c','/O2',str(src),'/Fo'+str(obj)] if Path(compiler).name.lower()=='cl.exe' else [compiler,'-O2','-c',str(src),'-o',str(obj)]
                    start=time.perf_counter()
                    run(args,180)
                    samples.append(time.perf_counter()-start)
            return metric(samples,'s',False,compiler=compiler,version=version,workload='3000 integer functions; compile only, no executable run')
        raise ValueError('Unknown benchmark')


def compare_runs(before, after):
    a,b=before['payload'],after['payload']
    compatible = a.get('parameters')==b.get('parameters') and a.get('fingerprint')==b.get('fingerprint')
    result=[]
    for key, old in a.get('results',{}).items():
        new=b.get('results',{}).get(key)
        if not new: continue
        valid=compatible and old.get('unit')==new.get('unit')
        if key=='compile': valid=valid and old.get('version')==new.get('version')
        if key=='gaming': valid=valid and old.get('capture_identity')==new.get('capture_identity')
        same_event=key=='boot' and old.get('event_time')==new.get('event_time')
        absolute=new['value']-old['value']
        percent=100*absolute/old['value'] if old['value'] else None
        noise=max(.03, 2*math.sqrt(old.get('cv',0)**2+new.get('cv',0)**2))*100
        status='Not comparable' if not valid else ('Same boot event' if same_event else ('Within observed variation' if percent is None or abs(percent)<=noise else ('Improvement' if (absolute>0)==old['higher'] else 'Regression')))
        result.append(dict(test=key,baseline=old['value'],current=new['value'],absolute=absolute,
                           percent=percent,status=status,unit=old['unit'],noise_threshold_percent=noise))
    return result


def import_presentmon(path, identity):
    values=[]
    applications=set()
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        if 'MsBetweenPresents' not in (reader.fieldnames or []):
            raise ValueError('Requires PresentMon CSV with MsBetweenPresents. Other formats are not silently converted.')
        for row in reader:
            applications.add((row.get('Application',''),row.get('ProcessID','')))
            try: value=float(row['MsBetweenPresents'])
            except (ValueError,TypeError): continue
            if math.isfinite(value) and value>0: values.append(value)
    if len(applications)>1:
        raise ValueError('Capture contains multiple processes. Export a single game process before importing.')
    if len(values)<100:
        raise ValueError('At least 100 positive frame intervals are needed')
    values.sort()
    p99=values[min(len(values)-1,math.ceil(.99*len(values))-1)]
    return metric([1000/statistics.mean(values)],'FPS',True,frames=len(values),
                  frametime_mean_ms=statistics.mean(values),frametime_p99_ms=p99,
                  one_percent_low_fps=1000/statistics.mean(values[-max(1,len(values)//100):]),
                  capture_identity=identity,application=list(applications)[0],
                  note='Imported capture; match game, resolution, preset, scene and duration manually. Variation unavailable for a single capture.')
