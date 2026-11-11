import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from app import Window, Review, STYLE
from core import Store

def test_ui_filter_edit_and_stats(tmp_path):
    app=QApplication.instance() or QApplication([]); app.setStyleSheet(STYLE)
    store=Store(tmp_path)
    store.save(dict(played_at='2026-01-01 12:00',mode='战术行动',map='电视台',difficulty='封锁区',kills=3,extracted=True))
    store.save(dict(played_at='2026-01-01 13:00',mode='战术行动',map='电视台',difficulty='封锁区',kills=1,extracted=False))
    store.save(dict(played_at='2026-01-01 14:00',mode='团队竞技',map='农场',difficulty='团队竞技',kills=8,deaths=2,victory=True))
    window=Window(store)
    assert window.table.rowCount()==2
    assert window.dashboard.battles.text()=='2'
    assert window.dashboard.kills.text()=='4'
    assert [w.text() for w in window.dashboard.kd_values]==['—','4','—']
    assert window.tabs.count()==2 and not window.windowIcon().isNull()
    window.mode_filter.setCurrentIndex(1)
    assert window.table.rowCount()==1
    assert window.dashboard.battles.text()=='2'
    window.mode_filter.setCurrentIndex(0); window.search.setText('2026-01-01')
    assert window.table.rowCount()>0
    r=store.all()[0]; dialog=Review(r,store.image(r),window)
    dialog.kills.setValue(4); dialog.accept_checked()
    assert dialog.row['kills']==4 and dialog.row['played_at']==r['played_at']
    window.close()


def test_capture_dialog_staging_preview_and_worker_signal(tmp_path):
    from capture_ui import CaptureDialog, CaptureWorker
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path); window=Window(store); dialog=CaptureDialog(window)
    worker=CaptureWorker(None,tmp_path/'session')
    worker.finished.connect(dialog.on_worker_finished)
    dialog.manifest=dict(message='测试',items=[dict(row=dict(played_at='2026-01-02 12:00',mode='战术行动',map='电视台',difficulty='封锁区',kills=2,extracted=True),image='test.png')])
    dialog.folder=tmp_path/'session'; dialog.populate()
    assert len(store.all())==0
    assert len(dialog.selected_items())==1
    assert '战局数 1' in dialog.preview_label.text()
    assert '击败特遣队员 2' in dialog.preview_label.text()
    dialog.reject(); window.close()


def test_infection_groups_dashboard_preview_and_original_records(tmp_path):
    from copy import deepcopy
    from capture_ui import CaptureDialog
    from capture import identity
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path)
    samples=[('普通',2,False),('封锁区',4,False),('感染区',3,True),
             ('感染区',5,False),('感染区',None,False),('强化封锁区',6,True),
             ('重度感染区',2,False),('物资争夺战',100,False)]
    for n,(difficulty,kills,extracted) in enumerate(samples):
        store.save(dict(played_at=f'2026-01-01 {n:02}:00',mode='战术行动',map='农场',
                        difficulty=difficulty,kills=kills,extracted=extracted))
    store.save(dict(played_at='2026-01-01 10:00',mode='团队竞技',map='农场',
                    difficulty='团队竞技',kills=100,deaths=1,victory=True))
    before=deepcopy(store.all()); identities=[identity(r) for r in before]
    window=Window(store)
    assert window.dashboard.battles.text()=='7' and window.dashboard.kills.text()=='22'
    assert [w.text() for w in window.dashboard.kd_values]==['2','6','8']
    assert '含感染区' in window.dashboard.kd_values[1].toolTip()
    assert '含重度感染区' in window.dashboard.kd_values[2].toolTip()
    window.diff_filter.setCurrentText('感染区')
    assert window.table.rowCount()==3 and window.dashboard.battles.text()=='7'
    dialog=CaptureDialog(window); dialog.folder=tmp_path/'capture'
    additions=[dict(played_at=f'2026-01-02 {n:02}:00',mode='战术行动',map='农场',
                    difficulty=difficulty,kills=kills,extracted=False)
               for n,(difficulty,kills) in enumerate([('感染区',4),('重度感染区',1)])]
    dialog.manifest=dict(message='合成测试',items=[dict(row=r,image=f'{n}.png') for n,r in enumerate(additions)])
    dialog.populate()
    assert '战局数 9' in dialog.preview_label.text()
    assert '2 / 5.3 / 4.5' in dialog.preview_label.text()
    assert '击败特遣队员 27' in dialog.preview_label.text()
    assert store.all()==before and [identity(r) for r in store.all()]==identities
    dialog.reject(); window.close()
    reopened=Store(tmp_path); assert reopened.all()==before; reopened.close()
