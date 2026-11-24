import csv
import json
from pathlib import Path

import pytest

from optimizer.store import Store
from optimizer.windows import guid, firmware_url
from optimizer.telemetry import network_stats
from optimizer.benchmarks import (BenchmarkEngine, PARAMETERS, compare_runs,
                                  import_presentmon, metric, fingerprint)
from optimizer.actions import ActionEngine, BALANCED, HIGH, protected
from optimizer import stability


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path/'test.sqlite3')


def test_store_round_trip_and_history(store):
    store.set('rollback',{'original':'saved'})
    assert store.get('rollback')=={'original':'saved'}
    store.action('power','applied',{'verified':True})
    store.save_run('baseline',{'results':{'cpu':12}})
    reopened=Store(store.path)
    assert reopened.actions()[0]['payload']['verified']
    assert reopened.runs()[0]['payload']['results']['cpu']==12


def test_rollback_durable_and_verified(store,monkeypatch):
    from optimizer import actions
    current=[HIGH]
    monkeypatch.setattr(actions,'active_plan',lambda:current[0])
    def command(args):
        assert store.get('rollback:balanced')['previous']==HIGH
        current[0]=args[-1]
    monkeypatch.setattr(actions,'run',command)
    engine=ActionEngine(store)
    engine.execute('balanced')
    assert current[0]==BALANCED
    engine.execute('balanced',revert=True)
    assert current[0]==HIGH
    assert store.get('rollback:balanced') is None


def test_rollback_refuses_later_changes(store,monkeypatch):
    from optimizer import actions
    store.set('rollback:balanced',{'previous':HIGH,'target':BALANCED})
    monkeypatch.setattr(actions,'active_plan',lambda:HIGH)
    monkeypatch.setattr(actions,'run',lambda _:pytest.fail('Must not mutate'))
    with pytest.raises(ValueError,match='changed since apply'):
        ActionEngine(store).execute('balanced',revert=True)


def test_failed_apply_retains_backup(store,monkeypatch):
    from optimizer import actions
    monkeypatch.setattr(actions,'active_plan',lambda:HIGH)
    def fail(_): raise RuntimeError('UAC denied')
    monkeypatch.setattr(actions,'run',fail)
    with pytest.raises(RuntimeError):ActionEngine(store).execute('balanced')
    assert store.get('rollback:balanced')['previous']==HIGH
    assert store.actions()[0]['status']=='failed'


@pytest.mark.parametrize('name',['vgc.exe','vgk','Riot Vanguard','Corsair iCUE','Windows Defender','Valorant.exe','ASUS fan control','SentinelAgent'])
def test_protected_components(name):
    assert protected(name)


def test_guid_and_exact_firmware():
    assert guid('Power Scheme GUID: '+BALANCED+' (Balanced)')==BALANCED
    with pytest.raises(ValueError): guid('no guid')
    assert 'b550-f-gaming-wi-fi-model' in firmware_url('ROG STRIX B550-F GAMING (WI-FI)')
    assert 'download-center' in firmware_url('ROG STRIX B550-F GAMING WIFI II')


def test_network_loss_and_jitter():
    result=network_stats([10,None,14,12])
    assert result['loss_percent']==25
    assert result['jitter_ms']==3
    assert network_stats([None])['latency_ms'] is None


def test_comparison_noise_and_identity():
    def saved(value,params=None,fp='same',cv=.001):
        return {'payload':{'parameters':params or {'v':1},'fingerprint':fp,
                           'results':{'cpu':metric([value],'ops/s',True)|{'cv':cv}}}}
    before=saved(100)
    assert compare_runs(before,saved(110))[0]['status']=='Improvement'
    assert compare_runs(before,saved(90))[0]['status']=='Regression'
    assert compare_runs(before,saved(101))[0]['status']=='Within observed variation'
    assert compare_runs(before,saved(110,{'v':2}))[0]['status']=='Not comparable'
    assert compare_runs(before,saved(110,fp='changed driver'))[0]['status']=='Not comparable'
    assert compare_runs(before,saved(110,cv=.2))[0]['status']=='Within observed variation'


def test_boot_same_event_not_improvement():
    a={'payload':{'parameters':{},'fingerprint':'same','results':{'boot':metric([1200],'ms',False)|{'event_time':'same'}}}}
    assert compare_runs(a,a)[0]['status']=='Same boot event'


def test_real_bounded_disk_and_cpu(store,tmp_path):
    p=dict(PARAMETERS,repeats=2,cpu_iterations=1000,disk_mib=1,random_ops=8,memory_mib=1,memory_copies=2)
    engine=BenchmarkEngine(store,{'cpu':[{'Name':'test'}]},tmp_path/'scratch',p)
    out=engine.suite(['cpu_single','memory','disk'],'test')
    assert not out['errors']
    assert out['results']['cpu_single']['value']>0
    assert out['results']['disk']['detail']['random_read_iops'][0]>0
    assert list((tmp_path/'scratch').iterdir())==[]
    assert store.runs()[0]['payload']['parameters']==p


def test_cancellation_saves_partial_run(store,tmp_path):
    engine=BenchmarkEngine(store,{},tmp_path)
    engine.cancel.set()
    out=engine.suite(['cpu_single'],'baseline')
    assert 'cancelled' in out['errors']
    assert not out['results']
    assert len(store.runs())==1


def test_presentmon_real_frames_and_multiple_process_guard(tmp_path):
    path=tmp_path/'frames.csv'
    path.write_text('Application,ProcessID,MsBetweenPresents\n'+'game.exe,42,10\n'*200)
    result=import_presentmon(path,'game 1080p medium route 60s')
    assert result['value']==100
    assert result['frametime_p99_ms']==10
    path.write_text(path.read_text()+'other.exe,43,5\n')
    with pytest.raises(ValueError,match='multiple processes'):
        import_presentmon(path,'same')


def test_prior_evidence_import_is_idempotent(store):
    stability.import_evidence(store)
    evidence=store.get('prior_evidence')
    stability.import_evidence(store)
    assert store.get('prior_evidence')==evidence
    assert not evidence['verified_by_app']
    assert any('No evidence establishes Vanguard' in s for s in evidence['findings'])


def test_transition_state_committed_before_shutdown(store,tmp_path,monkeypatch):
    calls=[]
    class FakeKey:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(stability.winreg,'CreateKey',lambda *args:FakeKey())
    monkeypatch.setattr(stability.winreg,'SetValueEx',lambda *args:None)
    def command(args):
        assert store.get('pending_transition')['mode']=='restart'
        assert store.actions()[0]['status']=='started'
        calls.append(args)
    monkeypatch.setattr(stability,'run',command)
    stability.initiate(store,'restart',tmp_path)
    assert '/r' in calls[0] and '/t' in calls[0]


def test_pagefile_backup_before_change(store,monkeypatch):
    from optimizer import actions
    state=[False]
    monkeypatch.setattr(actions,'is_admin',lambda:True)
    def query(script):
        if 'ComputerSystem' in script:return {'AutomaticManagedPagefile':state[0]}
        return [{'Name':r'C:\pagefile.sys','InitialSize':1024,'MaximumSize':4096}]
    def change(script):
        assert store.get('rollback:pagefile')['settings'][0]['InitialSize']==1024
        state[0]=True
    monkeypatch.setattr(actions,'psjson',query)
    monkeypatch.setattr(actions,'powershell',change)
    ActionEngine(store).execute('pagefile')
    assert state[0]
    assert store.get('rollback:pagefile')
