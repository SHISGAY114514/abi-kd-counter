from datetime import datetime
from pathlib import Path
import json
import pytest
from PIL import Image
from capture import history_date, identity, classify, merge_selected, save_manifest, Collector, is_report
from capture_windows import CaptureStopped, CaptureError, viewport
from core import Store


def row(**kw):
    r = dict(played_at='2026-01-01 12:00',mode='战术行动',map='电视台',difficulty='封锁区',kills=2,extracted=True)
    r.update(kw); return r


def test_date_rollover_and_invalid_date():
    assert history_date('电视台-封锁区11.1106:23',datetime(2026,11,11))=='2026-11-11 06:23'
    assert history_date('12.3123:59',datetime(2027,1,1))=='2026-12-31 23:59'
    assert history_date('电视台-封锁区11.022043',datetime(2026,11,11))=='2026-11-02 20:43'
    assert history_date('电视台-封锁区103108:01',datetime(2026,11,11))=='2026-10-31 08:01'
    assert history_date('11.9925:99',datetime(2026,11,11)) is None
    assert history_date('11.11',datetime(2026,11,11)) is None
    assert viewport((1440,1080))==(0,135,1440,810)
    assert viewport((1920,1080))==(0,0,1920,1080)


def test_staging_never_changes_store_and_merge_never_overwrites(tmp_path):
    store=Store(tmp_path/'database',seed=False); old=store.save(row())
    folder=tmp_path/'capture';folder.mkdir()
    image=folder/'report.png';Image.new('RGB',(20,20),'green').save(image)
    items=[dict(row=row(kills=99),image=image.name),dict(row=row(played_at='2026-01-01 13:00',extracted=False),image=image.name),
           dict(row=row(played_at='2026-01-01 14:00',kills=None),image=image.name)]
    save_manifest(folder,dict(items=items,state='complete'))
    assert store.all()==[old]
    assert classify(items[0]['row'],store.all())=='已有记录（数值不同）'
    assert classify(items[2]['row'],store.all())=='待核对'
    assert merge_selected(store,folder,items)==1
    assert next(r for r in store.all() if r['id']==old['id'])==old
    assert len(list(store.path.glob('before-capture-*.zip')))==1
    assert merge_selected(store,folder,items)==0
    assert len(store.all())==2
    store.close()


def test_cancel_keeps_partial_manifest_without_claiming_bottom(tmp_path,monkeypatch):
    import capture
    monkeypatch.setattr(capture,'Reader',lambda:None)
    class Stop:
        def activate(self):raise CaptureStopped('test stop')
    collector=Collector(Stop(),tmp_path/'session')
    result=collector.run()
    assert result['state']=='stopped' and result['bottom_verified'] is False
    assert json.loads((tmp_path/'session/manifest.json').read_text(encoding='utf8'))['state']=='stopped'


def test_complete_requires_repeated_unchanged_bottom(tmp_path,monkeypatch):
    import capture
    monkeypatch.setattr(capture,'Reader',lambda:None)
    image=Image.new('RGB',(20,20))
    class Desktop:
        def __init__(self):self.scrolls=0
        def activate(self):pass
        def scroll(self,amount):self.scrolls+=1
        def wait(self,n):pass
    desktop=Desktop(); c=Collector(desktop,tmp_path/'session');c.seen={'a'}
    c.start_page=lambda:image;c.to_top=lambda i:i;c.history_screen=lambda:image;c.inventory=lambda i:i;c.expected={'a'}
    c.signature=lambda i:(('a',),[dict(capture_key='a')])
    r=c.run()
    assert desktop.scrolls==2 and r['bottom_verified'] is True and r['state']=='complete'
    c=Collector(desktop,tmp_path/'missing');c.seen={'a'};c.expected={'a','missing'}
    c.start_page=lambda:image;c.to_top=lambda i:i;c.history_screen=lambda:image;c.inventory=lambda i:i
    c.signature=lambda i:(('a',),[dict(capture_key='a')])
    r=c.run()
    assert r['state']=='error' and r['bottom_verified'] is False


def test_resume_preserves_original_staging_and_seen_keys(tmp_path):
    folder=tmp_path/'session';folder.mkdir();(folder/'report.png').write_bytes(b'sample')
    manifest=dict(version=1,state='stopped',items=[dict(row=row(),image='report.png',list_entry=dict(capture_key='seen'))])
    save_manifest(folder,manifest)
    collector=Collector(None,folder,resume=True)
    assert collector.seen=={'seen'} and collector.manifest['items']==manifest['items']
    assert collector.manifest['state']=='running' and collector.manifest['bottom_verified'] is False


def test_report_page_gate_accepts_synthetic_report_modes():
    assert is_report(dict(row(),ocr_text='作战历程 行动成功'))
    assert is_report(dict(row(mode='团队竞技',deaths=2),ocr_text='队伍信息 被击败'))
    assert not is_report(dict(row(),ocr_text='历史战绩'))


def test_back_retry_only_when_still_on_report(tmp_path):
    class Desktop:
        def __init__(self):self.clicks=0
        def click(self,*_):self.clicks+=1
        def wait(self,*_):pass
        def screenshot(self):return self.clicks
    class Reader:
        def is_history(self,image):return image>=2
        def text(self,*_):return [dict(text='作战历程 行动成功')]
    d=Desktop();c=Collector(d,tmp_path/'retry');c.reader=Reader()
    c.history_screen=lambda:'history';c.collapse=lambda image:image
    assert c.return_to_history()=='history' and d.clicks==2
    d.clicks=0;c.reader.text=lambda *_:[dict(text='仓库')]
    with pytest.raises(CaptureError):c.return_to_history()
    assert d.clicks==1


def test_history_waits_for_delayed_rows_without_clicking(tmp_path):
    class Desktop:
        def screenshot(self):return 'frame'
        def wait(self,*_):pass
    class Reader:
        calls=0
        def is_history(self,image):return True
        def rows(self,*_):
            self.calls+=1
            return [dict(capture_key='ready')] if self.calls>=6 else []
    c=Collector(Desktop(),tmp_path/'delayed');c.reader=Reader()
    assert c.history_screen()=='frame' and c.reader.calls==6
