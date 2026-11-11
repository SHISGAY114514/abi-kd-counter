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
