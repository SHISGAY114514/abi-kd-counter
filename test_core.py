import json
import math
import zipfile
from pathlib import Path
import pytest
from core import Store,statistics,validate
from ocr import parse

def row(**kw):
    r=dict(played_at='2026-11-10 12:00',mode='战术行动',map='电视台',difficulty='封锁区',kills=3,extracted=True)
    r.update(kw); return r

def test_stats_unknown_and_modes_are_separate():
    data=[row(),row(kills=1,extracted=False),row(kills=None,extracted=False),row(kills=7,extracted=None),row(mode='团队竞技',kills=20,deaths=5,victory=True)]
    s=statistics(data); assert (s['kills'],s['kd_kills'],s['deaths'],s['valid'],s['pending'],s['kd'])==(11,4,1,2,2,4)
    assert s['rate']==pytest.approx(1/3)
    t=statistics(data,True); assert t['kd']==4 and t['total']==1

def test_zero_and_no_death_semantics():
    assert statistics([])['kd'] is None
    assert statistics([row(kills=0)])['kd'] is None
    assert math.isinf(statistics([row()])['kd'])
    assert statistics([row(kills=0,extracted=False)])['kd']==0

def test_money_and_time_use_independent_known_samples():
    data=[row(kills=None,extracted=True,loot=1_000_000,duration_seconds=120),row(kills=2,extracted=False,loot=0,duration_seconds=60),row(kills=7,extracted=None,loot=200_000),row(kills=0,extracted=False,loot=None)]
    s=statistics(data)
    assert s['loot_total']==1_200_000 and s['loot_average']==400_000 and s['loot_max']==1_000_000
    assert s['profit_ratio']==1_000_000 and s['profit_samples']==2
    assert s['duration_total']==180 and s['duration_average']==90
    assert s['rate']==pytest.approx(1/3) and s['outcome_samples']==3
    assert statistics([row(mode='团队竞技',deaths=1,loot=999)],True)['loot_total'] is None

def test_compact_units_and_unknown_money():
    from core import compact_money
    assert compact_money(None)=='—' and compact_money(0)=='0'
    assert compact_money(1200)=='1.2K' and compact_money(4_538_044)=='4.5M'
    assert compact_money(1_200_000_000)=='1.2B'
    assert statistics([row(loot=None)])['profit_ratio'] is None
    assert math.isinf(statistics([row(loot=100)])['profit_ratio'])

def test_persistence_duplicate_and_seed_once(tmp_path):
    s=Store(tmp_path,seed=False); saved=s.save(row()); s.close()
    s=Store(tmp_path,seed=False); assert len(s.all())==1
    with pytest.raises(ValueError): s.save(row())
    s.save(dict(saved,kills=5)); assert s.all()[0]['kills']==5
    s.delete(saved['id']); assert not s.all(); s.close()

def test_hash_dedup_backup_and_restore(tmp_path):
    a=Store(tmp_path/'a',seed=False); image=tmp_path/'test.png'; image.write_bytes(b'fake-image')
    saved=a.save(row(),image)
    with pytest.raises(ValueError): a.save(row(played_at='2026-11-11 12:00'),image)
    backup=tmp_path/'backup.zip'; a.backup(backup)
    b=Store(tmp_path/'b',seed=False); assert b.restore(backup)==1
    assert b.image(b.all()[0]).read_bytes()==b'fake-image'
    b.restore(backup); assert len(b.all())==1
    a.close(); b.close()

def test_malformed_backup_no_partial_records(tmp_path):
    s=Store(tmp_path/'data',seed=False); s.save(row())
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('manifest.json',json.dumps({'version':1,'matches':[row(id='x',evidence='../escape.png')]}))
    with pytest.raises(ValueError): s.restore(path)
    assert len(s.all())==1; s.close()

def test_public_install_starts_empty_and_upgrade_preserves_records(tmp_path):
    s=Store(tmp_path); assert s.all()==[]
    saved=s.save(row()); s.close()
    s=Store(tmp_path); assert s.all()==[saved]
    s.delete(saved['id']); s.close()
    s=Store(tmp_path); assert s.all()==[]; s.close()


def test_validation_rejects_negative_and_invalid_dates():
    for r in [row(kills=-1),row(kills='3'),row(played_at='yesterday'),row(mode='unknown')]:
        with pytest.raises((ValueError,TypeError)): validate(r)

def box(text,x,y,width=70,height=15,score=.99):
    return [[[x,y],[x+width,y],[x+width,y+height],[x,y+height]],text,score]

def test_player_count_never_uses_total_or_ai():
    raw=[box('战术行动-电视台-封锁区|18:30',100,100),box('行动成功',100,130),box('总淘汰数',200,300),box('淘汰特遣队员数',300,300),box('淘汰AI数',400,300),box('35',200,317,20),box('3',300,317,20),box('32',400,317,20)]
    r=parse(raw); assert r['kills']==3 and r['extracted'] is True and r['duration_seconds']==1110
    missing=[b for b in raw if b[1]!='3']; assert parse(missing)['kills'] is None
    assert parse([box('总淘汰数',200,300),box('35',200,317,20)])['kills'] is None

@pytest.mark.parametrize('map_name,difficulty', [('电视台','封锁区'),('农场','普通'),('山谷','强化封锁区')])
def test_synthetic_extraction_maps_and_difficulties(map_name,difficulty):
    raw=[box(f'战术行动-{map_name}-{difficulty}|18:30',100,100),box('行动成功',100,150)]
    r=parse(raw)
    assert r['map']==map_name and r['difficulty']==difficulty and r['extracted'] is True
