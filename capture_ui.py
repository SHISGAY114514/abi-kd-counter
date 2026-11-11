"""User controls and review for isolated collection sessions."""
import json
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox, QMessageBox)
from capture import Collector, classify, merge_selected, save_manifest
from capture_windows import Desktop, game_windows
from dashboard import STANDARD_DIFFICULTIES, standard_rows, ratio
from core import statistics


class CaptureWorker(QThread):
    progress = Signal(str)
    result_ready = Signal(object)
    def __init__(self, window, folder, resume=False):
        super().__init__(); self.target = window; self.folder = folder; self.resume=resume
    def run(self):
        try:
            collector = Collector(Desktop(self.target, self.isInterruptionRequested), self.folder, self.progress.emit,resume=self.resume)
            self.result_ready.emit(collector.run())
        except Exception as error:
            self.result_ready.emit(dict(version=1,state='error',items=[],message=str(error),bottom_verified=False))


class CaptureDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner); self.owner = owner; self.store = owner.store
        self.worker = None; self.manifest = None; self.folder = None
        self.setWindowTitle('自动采集历史战绩 · 独立暂存'); self.resize(1160,780)
        layout = QVBoxLayout(self)
        intro = QLabel('先在游戏中打开“个人主页 → 历史战绩”（停在作战报告也可以）。\n'
            '开始后会自动展开各场报告、读取真实对局时间并滚动到底。采集期间请勿操作鼠标或切换窗口。\n'
            'F8 随时停止；切换窗口也会停止。采集结果独立暂存，只有点击“合并选中新增记录”才写入战绩库。')
        intro.setWordWrap(True); layout.addWidget(intro)
        controls = QHBoxLayout()
        self.start = QPushButton('开始自动采集'); self.start.setObjectName('primary'); self.start.clicked.connect(self.begin)
        self.stop = QPushButton('停止采集（F8）'); self.stop.setEnabled(False); self.stop.clicked.connect(self.request_stop)
        self.latest = QPushButton('查看上次采集结果'); self.latest.clicked.connect(self.open_latest)
        self.resume_button=QPushButton('继续上次采集'); self.resume_button.clicked.connect(lambda:self.begin(True))
        for button in (self.start,self.resume_button,self.stop,self.latest): controls.addWidget(button)
        controls.addStretch(); layout.addLayout(controls)
        self.status = QLabel('尚未开始。已有战绩不会因采集而被覆盖。'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.table = QTableWidget(0,7)
        self.table.setHorizontalHeaderLabels(['合并','对局时间','地图 / 难度','结果','特遣淘汰','状态','截图'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self.review); self.table.itemChanged.connect(self.preview)
        layout.addWidget(self.table,1)
        self.preview_label = QLabel(''); self.preview_label.setWordWrap(True); layout.addWidget(self.preview_label)
        self.confirm = QCheckBox('我已核对选中记录的时间、模式、难度、行动结果和特遣队员淘汰数'); layout.addWidget(self.confirm)
        bottom = QHBoxLayout()
        self.edit = QPushButton('核对选中行 / 查看截图'); self.edit.clicked.connect(lambda: self.review(self.table.currentRow(),0)); bottom.addWidget(self.edit)
        bottom.addStretch()
        self.merge = QPushButton('合并选中新增记录'); self.merge.setObjectName('primary'); self.merge.setEnabled(False); self.merge.clicked.connect(self.commit); bottom.addWidget(self.merge)
        self.close_button = QPushButton('关闭（保留暂存）'); self.close_button.clicked.connect(self.reject); bottom.addWidget(self.close_button)
        layout.addLayout(bottom)

    def begin(self,resume=False):
        try:
            targets = game_windows()
            if len(targets) != 1: raise ValueError(f'找到 {len(targets)} 个暗区突围游戏窗口，请保持一个游戏窗口运行。')
            if resume:
                sessions=sorted((self.store.path/'captures').glob('*/manifest.json'),reverse=True)
                if not sessions: raise ValueError('没有可继续的采集批次。')
                previous=json.loads(sessions[0].read_text(encoding='utf8'))
                if previous['state']=='complete': raise ValueError('上次已经采集完成，请查看结果或开始新采集。')
                self.folder=sessions[0].parent
            else: self.folder = self.store.path/'captures'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            self.worker = CaptureWorker(targets[0],self.folder,resume)
            self.worker.progress.connect(self.status.setText); self.worker.result_ready.connect(self.received)
            self.worker.finished.connect(self.on_worker_finished)
            for button in (self.start,self.resume_button,self.latest,self.merge,self.edit): button.setEnabled(False)
            self.stop.setEnabled(True); self.confirm.setChecked(False)
            self.hide(); self.owner.showMinimized(); self.worker.start()
        except Exception as error: QMessageBox.warning(self,'无法开始',str(error))

    def request_stop(self):
        if self.worker and self.worker.isRunning(): self.worker.requestInterruption(); self.status.setText('正在停止，请稍候……')

    def received(self, manifest): self.manifest = manifest

    def on_worker_finished(self):
        self.start.setEnabled(True); self.resume_button.setEnabled(True); self.latest.setEnabled(True); self.edit.setEnabled(True); self.stop.setEnabled(False)
        self.owner.showNormal(); self.owner.raise_(); self.showNormal(); self.raise_(); self.activateWindow()
        self.populate()

    def open_latest(self):
        sessions = sorted((self.store.path/'captures').glob('*/manifest.json'), reverse=True)
        if not sessions: QMessageBox.information(self,'暂无结果','尚未保存自动采集结果。'); return
        try:
            self.folder = sessions[0].parent
            self.manifest = json.loads(sessions[0].read_text(encoding='utf8')); self.confirm.setChecked(False); self.populate()
        except Exception as error: QMessageBox.warning(self,'读取失败',str(error))

    def populate(self):
        if not self.manifest: return
        self.table.blockSignals(True)
        items = self.manifest['items']; existing = self.store.all(); self.table.setRowCount(len(items))
        counts = {'新增':0,'已有记录':0,'待核对':0}
        for i,item in enumerate(items):
            row = item['row']; status = classify(row,existing)
            counts['已有记录' if status.startswith('已有') else status] += 1
            check = QTableWidgetItem(); check.setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable|(Qt.ItemIsUserCheckable if status=='新增' else Qt.NoItemFlags))
            check.setCheckState(Qt.Checked if status=='新增' else Qt.Unchecked); self.table.setItem(i,0,check)
            outcome = row.get('victory') if row.get('mode') in ('团队竞技','武器升级','歼灭战') else row.get('extracted')
            values = [row['played_at'],row.get('map','')+' / '+row.get('difficulty',''),{True:'成功',False:'失败',None:'待核对'}[outcome],
                      str(row['kills']) if row.get('kills') is not None else '—',status,item['image']]
            for j,value in enumerate(values,1): self.table.setItem(i,j,QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.status.setText(f'{self.manifest["message"]}\n采集 {len(items)} 场：新增 {counts["新增"]}、已有 {counts["已有记录"]}、待核对 {counts["待核对"]}。双击行可查看截图和纠正。\n暂存目录：{self.folder}')
        self.merge.setEnabled(counts['新增'] > 0); self.preview()

    def selected_items(self):
        if not self.manifest: return []
        return [item for i,item in enumerate(self.manifest['items']) if self.table.item(i,0).checkState()==Qt.Checked]

    def preview(self,*_):
        if not self.manifest: return
        combined = self.store.all()
        for item in self.selected_items():
            if classify(item['row'],combined)=='新增': combined.append(item['row'])
        rows = standard_rows(combined); s = statistics(rows)
        kd = [ratio(statistics([r for r in rows if r['difficulty']==d])['kd']) for d in STANDARD_DIFFICULTIES]
        self.preview_label.setText(f'合并后预览（尚未写入）：战局数 {s["total"]}   KD 普通 / 封锁 / 强化封锁：{" / ".join(kd)}   击败特遣队员 {s["kills"]}')

    def review(self,index,*_):
        if not self.manifest or index < 0: return
        from app import Review
        item = self.manifest['items'][index]
        dialog = Review(item['row'],self.folder/Path(item['image']).name,self)
        if dialog.exec()==QDialog.Accepted:
            item['row'] = dialog.row; item['row']['capture_needs_review'] = False
            save_manifest(self.folder,self.manifest); self.confirm.setChecked(False); self.populate()

    def commit(self):
        if not self.confirm.isChecked():
            QMessageBox.information(self,'请先核对','核对选中记录后，勾选下方确认框再合并。'); return
        try:
            n = merge_selected(self.store,self.folder,self.selected_items())
            self.owner.reload_filters(); self.owner.refresh(); self.confirm.setChecked(False); self.populate()
            QMessageBox.information(self,'合并完成',f'新增 {n} 场；已有记录没有被覆盖。\n合并前已自动备份数据库和截图。')
        except Exception as error: QMessageBox.warning(self,'合并未完成',str(error)+'\n请检查当前列表；已写入记录会标记为已有，重试不会重复累计。')

    def reject(self):
        if self.worker and self.worker.isRunning(): self.request_stop(); return
        super().reject()

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning(): self.request_stop(); event.ignore(); return
        event.accept()
