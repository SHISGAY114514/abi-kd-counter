"""Exercise real OCR and the import queue against an isolated database."""
import json
import os
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from app import Window, Review
from core import Store, statistics


def test_real_batch_import_review_save_dedup_and_reopen(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root = Path(__file__).parent
    expected = {
        'ocr-self-test.png':dict(played_at='2026-01-01 12:00',map='电视台',difficulty='封锁区',mode='战术行动',kills=3,extracted=True),
        'ocr-failure-test.png':dict(played_at='2026-01-01 13:00',map='电视台',difficulty='封锁区',mode='战术行动',kills=0,extracted=False),
    }
    store = Store(tmp_path/'database', seed=False)
    window = Window(store)
    messages, reviewed = [], []
    for method in ('information', 'warning'):
        monkeypatch.setattr(QMessageBox, method, lambda *args: messages.append(str(args[2])))

    def review(dialog):
        name = dialog.image.name
        # Recognition itself must never commit a record.
        assert len(store.all()) == len(reviewed)
        if name == 'blank.png':
            assert dialog.row['kills'] is None and dialog.row['extracted'] is None
            dialog.reject()
            return QDialog.Rejected
        original = expected[name]
        for field in ('map', 'difficulty', 'mode', 'kills', 'extracted'):
            assert dialog.row[field] == original[field]
        assert dialog.confirm.isChecked() is False
        dialog.accept_checked()
        assert QDialog.result(dialog) != QDialog.Accepted
        dialog.time.setDateTime(QDateTime.fromString(original['played_at'], 'yyyy-MM-dd HH:mm'))
        dialog.confirm.setChecked(True)
        dialog.accept_checked()
        assert QDialog.result(dialog) == QDialog.Accepted
        reviewed.append(name)
        return QDialog.Accepted

    monkeypatch.setattr(Review, 'exec', review)
    blank = tmp_path/'blank.png'
    Image.new('RGB', (800, 600), 'black').save(blank)
    corrupt = tmp_path/'corrupt.png'
    corrupt.write_bytes(b'not an image')
    invalid = tmp_path/'unsupported.txt'
    invalid.write_text('not an image')
    first, second = [root/'assets'/name for name in expected]
    window.import_images([first, first, second, blank, corrupt, invalid])
    deadline = time.monotonic()+60
    while time.monotonic() < deadline:
        app.processEvents()
        if window.worker and not window.worker.isRunning() and window.import_button.isEnabled() and not window.queue:
            break
        time.sleep(.01)
    else:
        window.worker.wait()
        raise AssertionError('Import did not finish within 60 seconds')
    assert set(reviewed) == set(expected)
    assert len(store.all()) == 2
    assert window.dashboard.battles.text() == '2'
    assert int(window.dashboard.kills.text()) == sum(r['kills'] for r in expected.values())
    assert statistics(store.all())['kills'] == sum(r['kills'] for r in expected.values())
    assert all(store.image(r).exists() and r['reviewed'] for r in store.all())
    assert any('重复截图' in m and '1 个不支持' in m for m in messages)
    assert any('corrupt.png' in m for m in messages)
    window.import_images([first])
    assert len(store.all()) == 2 and not window.worker.isRunning()
    window.close()
    reopened = Store(tmp_path/'database', seed=False)
    assert len(reopened.all()) == 2
    assert all(reopened.image(r).exists() for r in reopened.all())
    reopened.close()
