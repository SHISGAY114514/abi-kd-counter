from __future__ import annotations
import csv
import json
import logging
import math
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QDateTime, QThread, Signal, QTimer, QLockFile, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QPixmap, QKeySequence, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox, QDialog, QFormLayout, QDateTimeEdit, QSpinBox, QTextEdit, QDialogButtonBox,
    QScrollArea, QSplitter, QFrame, QCheckBox, QProgressBar, QTabWidget)
from core import Store, statistics, complete, compact_money, MAPS, DIFFICULTIES, MODES, TEAM_MODES, default_data_dir, resources, sha256
from dashboard import Dashboard

STYLE = '''
QWidget { background:#111b1b; color:#e3eae7; font-family:"Microsoft YaHei UI"; font-size:13px; }
QMainWindow { background:#111b1b; }
QLabel#title { font-size:27px; font-weight:700; }
QLabel#muted { color:#94a6b6; }
QLabel#warning { color:#edc57d; background:#302a20; padding:12px; border-radius:6px; }
QFrame#card { background:#1b2928; border:1px solid #30443f; border-radius:5px; }
QFrame#card QLabel { background:transparent; }
QLabel#metric { font-size:29px; color:#94e9bd; font-weight:700; }
QLabel#caption { color:#8b9f94; font-size:11px; }
QLabel#section { font-size:16px; font-weight:600; }
QLabel#headline { font-size:26px; color:#e9f7ed; font-weight:600; }
QFrame#banner { background:#20352e; border-left:3px solid #90e2ae; }
QFrame#banner QLabel { background:transparent; }
QTabWidget::pane { border:0; }
QTabBar::tab { background:#182522; color:#9bb1a7; padding:10px 32px; margin-right:3px; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:#d4f5de; background:#253e32; border-bottom:2px solid #9be7ac; }
QPushButton { background:#243643; border:1px solid #36515e; border-radius:6px; padding:9px 14px; }
QPushButton:hover { background:#304b59; border-color:#66cfb2; }
QPushButton:disabled { color:#6e7c87; background:#1c2730; }
QPushButton#primary { color:#0b2422; background:#72dabe; border:none; font-weight:700; }
QLineEdit,QComboBox,QSpinBox,QDateTimeEdit,QTextEdit { background:#17232d; border:1px solid #364a59; border-radius:5px; padding:7px; selection-background-color:#316b63; }
QComboBox QAbstractItemView { background:#20313d; selection-background-color:#316b63; }
QTableWidget { background:#14202a; alternate-background-color:#192833; border:1px solid #2d414f; gridline-color:#223543; selection-background-color:#28594f; }
QHeaderView::section { background:#223440; color:#a8bcc9; padding:9px 6px; border:0; }
QTableWidget::item { padding:6px; }
QScrollBar:vertical { background:#14212b; width:12px; }
QScrollBar::handle:vertical { background:#405866; min-height:30px; border-radius:5px; }
QProgressBar { border:1px solid #3b5260; border-radius:5px; text-align:center; }
QProgressBar::chunk { background:#3d9b85; }
QToolTip { background:#243643; color:white; border:1px solid #5d7e8f; padding:6px; }
'''

def fmt(v, digits=2):
    if v is None: return '—'
    if isinstance(v,float) and math.isinf(v): return '∞'
    return f'{v:.{digits}f}' if isinstance(v,float) else str(v)

def outcome(r):
    if r['mode'] in TEAM_MODES:
        return {True:'胜利',False:'失败',None:'待核对'}.get(r.get('victory'))
    return {True:'成功撤离',False:'撤离失败',None:'待核对'}.get(r.get('extracted'))

def duration(v):
    return f'{v//60:02}:{v%60:02}' if v is not None else '—'

def combo(values, current='', editable=False):
    w=QComboBox(); w.addItems(values); w.setEditable(editable)
    if w.findText(current)<0 and current: w.addItem(current)
    w.setCurrentText(current)
    return w

def nullable_spin(maximum, value):
    w=QSpinBox(); w.setRange(-1,maximum); w.setSpecialValueText('未知 / 待核对')
    w.setValue(-1 if value is None else value); w.setMinimumWidth(170)
    return w

class Review(QDialog):
    def __init__(self,row,image=None,parent=None):
        super().__init__(parent)
        self.row=dict(row); self.image=Path(image) if image else None
        self.setWindowTitle('核对作战报告 · 只统计特遣队员')
        self.resize(1120,790)
        root=QVBoxLayout(self)
        info=QLabel('核对识别结果后保存。未知字段会保留为待核对，不会按 0 计入 KD。')
        info.setObjectName('muted'); root.addWidget(info)
        split=QSplitter(); root.addWidget(split,1)
        left=QWidget(); ll=QVBoxLayout(left)
        self.preview=QLabel(); self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumSize(420,300)
        if self.image and self.image.exists():
            self.pix=QPixmap(str(self.image)); self.preview.setPixmap(self.pix.scaled(600,570,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else: self.preview.setText('手动记录 · 暂无截图')
        ll.addWidget(self.preview,1)
        full=QPushButton('打开原始截图'); full.setEnabled(bool(self.image and self.image.exists()))
        full.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.image))))
        ll.addWidget(full); split.addWidget(left)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); right=QWidget(); form=QFormLayout(right); scroll.setWidget(right); split.addWidget(scroll)
        split.setSizes([620,460])
        warnings=row.get('ocr_warnings',[])
        if warnings:
            warning=QLabel('\n'.join('• '+w for w in warnings)); warning.setWordWrap(True); warning.setObjectName('warning'); form.addRow(warning)
        self.time=QDateTimeEdit(QDateTime.fromString(row.get('played_at',datetime.now().strftime('%Y-%m-%d %H:%M')),'yyyy-MM-dd HH:mm'))
        self.time.setDisplayFormat('yyyy-MM-dd HH:mm'); self.time.setCalendarPopup(True); form.addRow('对局日期 / 时间',self.time)
        self.mode=combo(MODES,row.get('mode','战术行动')); form.addRow('模式',self.mode)
        self.map=combo(['']+list(MAPS),row.get('map',''),True); form.addRow('地图',self.map)
        self.difficulty=combo(['']+list(DIFFICULTIES),row.get('difficulty',''),True); form.addRow('难度 / 活动',self.difficulty)
        self.result=combo(['待核对','成功撤离 / 胜利','撤离失败 / 失败'])
        value=row.get('victory') if row.get('mode') in TEAM_MODES else row.get('extracted')
        self.result.setCurrentIndex(0 if value is None else 1 if value else 2); form.addRow('行动结果',self.result)
        self.kills=nullable_spin(10000,row.get('kills')); form.addRow('特遣队员淘汰数',self.kills)
        self.deaths=nullable_spin(10000,row.get('deaths')); form.addRow('团队被击败次数',self.deaths)
        self.duration=QLineEdit('' if row.get('duration_seconds') is None else duration(row['duration_seconds'])); self.duration.setPlaceholderText('分:秒，例如 18:30'); form.addRow('生存 / 对局时长',self.duration)
        self.loot=nullable_spin(2_000_000_000,row.get('loot')); form.addRow('带出总价值',self.loot)
        self.note=QTextEdit(row.get('note','')); self.note.setMaximumHeight(75); form.addRow('备注',self.note)
        self.confirm=QCheckBox('我已核对时间及关键数据'); self.confirm.setChecked(not warnings); form.addRow(self.confirm)
        hint=QLabel('撤离战损比 = 特遣队员淘汰数 ÷ 撤离失败场次。\n团队战损比 = 淘汰数 ÷ 实际被击败次数。\n未知字段不补零，各指标按已知样本独立计算。')
        hint.setWordWrap(True); hint.setObjectName('muted'); form.addRow(hint)
        if row.get('ocr_text'):
            raw=QTextEdit(row['ocr_text']); raw.setReadOnly(True); raw.setMaximumHeight(100); form.addRow('识别原文',raw)
        self.mode.currentTextChanged.connect(self.update_mode); self.update_mode()
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存并更新统计')
        buttons.button(QDialogButtonBox.Cancel).setText('跳过 / 取消')
        buttons.accepted.connect(self.accept_checked); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def update_mode(self):
        team=self.mode.currentText() in TEAM_MODES
        self.deaths.setEnabled(team); self.loot.setEnabled(not team)

    def accept_checked(self):
        if not self.confirm.isChecked():
            QMessageBox.information(self,'请核对','请核对日期、淘汰数和行动结果，再勾选确认。'); return
        text=self.duration.text().strip(); seconds=None
        if text:
            import re
            m=re.fullmatch(r'(\d{1,3}):([0-5]\d)',text)
            if not m:
                QMessageBox.warning(self,'时长格式','请使用 分:秒，例如 18:30；未知可留空。'); return
            seconds=int(m[1])*60+int(m[2])
        result={0:None,1:True,2:False}[self.result.currentIndex()]
        team=self.mode.currentText() in TEAM_MODES
        self.row.update(played_at=self.time.dateTime().toString('yyyy-MM-dd HH:mm'),mode=self.mode.currentText(),
            map=self.map.currentText().strip(),difficulty=self.difficulty.currentText().strip(),
            kills=None if self.kills.value()<0 else self.kills.value(),
            deaths=(None if self.deaths.value()<0 else self.deaths.value()) if team else None,
            extracted=None if team else result,victory=result if team else None,
            duration_seconds=seconds,loot=None if team or self.loot.value()<0 else self.loot.value(),
            note=self.note.toPlainText().strip(),reviewed=True)
        super().accept()

class OCRWorker(QThread):
    ready=Signal(object,object)
    progress=Signal(int,int,str)
    def __init__(self,paths): super().__init__(); self.paths=paths
    def run(self):
        from ocr import Recognizer
        results=[]; errors=[]
        try: engine=Recognizer()
        except Exception as e:
            self.ready.emit([],[(str(p),str(e)) for p in self.paths]); return
        for i,path in enumerate(self.paths):
            if self.isInterruptionRequested(): break
            self.progress.emit(i,len(self.paths),Path(path).name)
            try: results.append((str(path),engine.recognize(path)))
            except Exception as e:
                logging.exception('OCR failed'); errors.append((str(path),str(e)))
        self.ready.emit(results,errors)

class Window(QMainWindow):
    def __init__(self,store):
        super().__init__(); self.store=store; self.worker=None; self.queue=[]; self.visible_rows=[]; self.tempfiles=[]
        self.setWindowTitle('暗区战绩 · KD 计数器 1.2.2'); self.resize(1280,920); self.setMinimumSize(1080,820); self.setAcceptDrops(True)
        self.setWindowIcon(QIcon(str(resources()/'assets/app-icon.ico')))
        root=QWidget(); self.setCentralWidget(root); layout=QVBoxLayout(root); layout.setContentsMargins(26,24,26,20); layout.setSpacing(15)
        top=QHBoxLayout(); mark=QLabel(); mark.setPixmap(QPixmap(str(resources()/'assets/app-icon.png')).scaled(58,58,Qt.KeepAspectRatio,Qt.SmoothTransformation)); top.addWidget(mark); top.addSpacing(10)
        heading=QVBoxLayout(); title=QLabel('暗区战绩'); title.setObjectName('title'); heading.addWidget(title)
        subtitle=QLabel('ARENA BREAKOUT INFINITE  /  特遣队员 KD'); subtitle.setObjectName('muted'); heading.addWidget(subtitle); top.addLayout(heading); top.addStretch()
        self.import_button=QPushButton('＋ 导入作战报告'); self.import_button.setObjectName('primary'); self.import_button.clicked.connect(self.choose_images); top.addWidget(self.import_button)
        self.paste_button=QPushButton('粘贴截图'); self.paste_button.clicked.connect(self.paste); top.addWidget(self.paste_button)
        self.manual_button=QPushButton('手动记录'); self.manual_button.clicked.connect(self.manual); top.addWidget(self.manual_button); layout.addLayout(top)
        self.capture_button=QPushButton('自动采集'); self.capture_button.clicked.connect(self.capture_history); top.addWidget(self.capture_button)
        self.drop_hint=QLabel('拖入图片、选择多张截图或按 Ctrl+V 粘贴  ·  离线识别  ·  保存后自动更新统计')
        self.drop_hint.setObjectName('muted'); layout.addWidget(self.drop_hint)
        filters=QHBoxLayout()
        self.mode_filter=combo(['撤离类（战术行动）','团队模式（全部）']+list(TEAM_MODES),'撤离类（战术行动）')
        self.map_filter=combo(['全部地图'],'全部地图'); self.diff_filter=combo(['全部难度'],'全部难度')
        self.period_filter=combo(['全部时间','最近 7 天','最近 30 天'],'全部时间')
        self.search=QLineEdit(); self.search.setPlaceholderText('搜索日期、地图或备注')
        for w in (self.mode_filter,self.map_filter,self.diff_filter,self.period_filter): filters.addWidget(w); w.currentTextChanged.connect(self.refresh)
        filters.addWidget(self.search,1); self.search.textChanged.connect(self.refresh)
        self.filter_bar=QWidget(); self.filter_bar.setLayout(filters); layout.addWidget(self.filter_bar)
        self.tabs=QTabWidget(); layout.addWidget(self.tabs,1)
        self.dashboard=Dashboard()
        self.tabs.addTab(self.dashboard,'数据总览')
        history_page=QWidget(); history_layout=QVBoxLayout(history_page); history_layout.setContentsMargins(0,12,0,0); self.tabs.addTab(history_page,'历史战绩')
        self.tabs.currentChanged.connect(lambda i:self.filter_bar.setVisible(i==1)); self.filter_bar.hide()
        self.formula=QLabel(); self.formula.setWordWrap(True); self.formula.setObjectName('muted'); history_layout.addWidget(self.formula)
        bar=QHBoxLayout(); label=QLabel('对局记录'); label.setStyleSheet('font-size:17px;font-weight:600'); bar.addWidget(label); bar.addStretch()
        self.edit_button=QPushButton('查看 / 修改'); self.edit_button.clicked.connect(self.edit); bar.addWidget(self.edit_button)
        self.delete_button=QPushButton('删除记录'); self.delete_button.clicked.connect(self.delete); bar.addWidget(self.delete_button); history_layout.addLayout(bar)
        self.table=QTableWidget(0,9)
        self.table.setHorizontalHeaderLabels(['对局时间','地图','难度 / 活动','结果','特遣淘汰','被击败','时长','带出价值','状态'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False); self.table.verticalHeader().setDefaultSectionSize(39)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
        self.table.doubleClicked.connect(self.edit); history_layout.addWidget(self.table,1)
        self.progress=QProgressBar(); self.progress.hide(); layout.addWidget(self.progress)
        bottom=QHBoxLayout(); self.summary=QLabel(); self.summary.setObjectName('muted'); bottom.addWidget(self.summary,1)
        self.tabs.currentChanged.connect(self.update_summary)
        for text,fn in [('导出 CSV',self.export),('备份',self.backup),('恢复备份',self.restore),('使用说明',self.help)]:
            b=QPushButton(text); b.clicked.connect(fn); bottom.addWidget(b)
        layout.addLayout(bottom)
        paste=QAction(self); paste.setShortcut(QKeySequence.Paste); paste.triggered.connect(self.paste); self.addAction(paste)
        self.reload_filters(); self.refresh()

    def reload_filters(self):
        rows=self.store.all()
        for widget,field,label in [(self.map_filter,'map','全部地图'),(self.diff_filter,'difficulty','全部难度')]:
            current=widget.currentText(); widget.blockSignals(True); widget.clear(); widget.addItems([label]+sorted({r.get(field,'') for r in rows if r.get(field)}))
            widget.setCurrentText(current if widget.findText(current)>=0 else label); widget.blockSignals(False)

    def refresh(self,*_):
        team=self.mode_filter.currentIndex()>0; mode=self.mode_filter.currentText(); rows=self.store.all()
        rows=[r for r in rows if (r['mode'] in TEAM_MODES)==team and (mode not in TEAM_MODES or r['mode']==mode)]
        if self.map_filter.currentIndex()>0: rows=[r for r in rows if r.get('map')==self.map_filter.currentText()]
        if self.diff_filter.currentIndex()>0: rows=[r for r in rows if r.get('difficulty')==self.diff_filter.currentText()]
        days={1:7,2:30}.get(self.period_filter.currentIndex())
        if days:
            from datetime import timedelta
            cutoff=datetime.now()-timedelta(days=days); rows=[r for r in rows if datetime.strptime(r['played_at'],'%Y-%m-%d %H:%M')>=cutoff]
        term=self.search.text().strip().casefold()
        if term: rows=[r for r in rows if term in ' '.join(str(r.get(k,'')) for k in ('played_at','map','difficulty','note')).casefold()]
        s=statistics(rows,team); self.visible_rows=rows
        self.table.setHorizontalHeaderItem(5,QTableWidgetItem('被击败' if team else '失败计数'))
        self.dashboard.update_data(self.store.all())
        self.formula.setText(f'{"团队战损比 = 淘汰数 ÷ 实际被击败次数" if team else "撤离战损比 = 特遣队员淘汰数 ÷ 撤离失败场次"}  ·  {s["kd_kills"]} ÷ {s["deaths"]} = {fmt(s["kd"])}  ·  {s["pending"]} 场 KD 待核对  ·  AI 不参与统计')
        self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            vals=[r['played_at'],r.get('map') or '待核对',r.get('difficulty') or '待核对',outcome(r),fmt(r.get('kills')),
                  fmt(r.get('deaths')) if team else ('0' if r.get('extracted') is True else '1' if r.get('extracted') is False else '—'),
                  duration(r.get('duration_seconds')),compact_money(r.get('loot')), '已统计' if complete(r) else 'KD 待核对']
            for j,v in enumerate(vals):
                item=QTableWidgetItem(v); item.setToolTip(r.get('note') or r.get('source',''))
                if j==7 and r.get('loot') is not None: item.setToolTip(f'带出价值：{r["loot"]:,} 柯恩币（未扣除装备成本）')
                if j==3: item.setForeground(QColor('#78d9b5' if outcome(r) in ('成功撤离','胜利') else '#f29b8e' if outcome(r)!='待核对' else '#e7c17b'))
                if j==4: item.setForeground(QColor('#8fe5cb'))
                self.table.setItem(i,j,item)
        self.update_summary()

    def update_summary(self,*_):
        if self.tabs.currentIndex()==0:
            self.summary.setText(f'本机已保存 {len(self.store.all())} 场原始战绩 · 全部记录可在历史战绩中查看')
        else:
            self.summary.setText(f'当前显示 {len(self.visible_rows)} 场 / 库内共 {len(self.store.all())} 场  ·  双击查看报告')

    def selected(self):
        i=self.table.currentRow(); return self.visible_rows[i] if 0<=i<len(self.visible_rows) else None

    def edit(self,*_):
        row=self.selected()
        if not row: return
        dlg=Review(row,self.store.image(row),self)
        if dlg.exec()==QDialog.Accepted:
            try: self.store.save(dlg.row); self.reload_filters(); self.refresh()
            except Exception as e: QMessageBox.warning(self,'保存失败',str(e))

    def manual(self):
        row=dict(played_at=datetime.now().strftime('%Y-%m-%d %H:%M'),mode='战术行动',map='',difficulty='',source='手动记录')
        dlg=Review(row,None,self)
        if dlg.exec()==QDialog.Accepted:
            try: self.store.save(dlg.row); self.reload_filters(); self.refresh()
            except Exception as e: QMessageBox.warning(self,'保存失败',str(e))

    def delete(self):
        row=self.selected()
        if row and QMessageBox.question(self,'删除记录',f'删除 {row["played_at"]} {row.get("map","")} 的记录？\n建议先备份。截图文件仍保留在本机。',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
            self.store.delete(row['id']); self.refresh()

    def choose_images(self):
        paths,_=QFileDialog.getOpenFileNames(self,'选择个人作战报告截图','','图片 (*.png *.jpg *.jpeg *.bmp *.webp)')
        if paths: self.import_images(paths)

    def capture_history(self):
        if self.worker and self.worker.isRunning() or self.queue:
            QMessageBox.information(self,'正在导入','请完成当前截图导入后再自动采集。'); return
        from capture_ui import CaptureDialog
        self.capture_dialog=CaptureDialog(self); self.capture_dialog.exec()

    def paste(self):
        if self.worker and self.worker.isRunning(): return
        clip=QApplication.clipboard(); img=clip.image()
        if not img.isNull():
            fd,path=tempfile.mkstemp(suffix='.png',prefix='abi-kd-'); os.close(fd); img.save(path,'PNG'); self.tempfiles.append(path); self.import_images([path])
        elif clip.mimeData().hasUrls(): self.import_images([u.toLocalFile() for u in clip.mimeData().urls() if u.isLocalFile()])
        else: QMessageBox.information(self,'粘贴截图','剪贴板中没有图片。请先复制截图，或点击“导入作战报告”。')

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self,event):
        self.import_images([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]); event.acceptProposedAction()

    def import_images(self,paths):
        if self.worker and self.worker.isRunning() or self.queue:
            QMessageBox.information(self,'正在导入','请完成当前批次后继续导入。'); return
        valid=[]; duplicate=0; invalid=0; hashes=set()
        known={r.get('image_hash') for r in self.store.all()}
        for p in paths:
            p=Path(p)
            if p.suffix.lower() not in ('.png','.jpg','.jpeg','.bmp','.webp') or not p.is_file(): invalid+=1; continue
            h=sha256(p)
            if h in known or h in hashes: duplicate+=1; continue
            valid.append(str(p)); hashes.add(h)
        if duplicate or invalid:
            QMessageBox.information(self,'导入检查',f'已跳过 {duplicate} 张重复截图、{invalid} 个不支持的文件。\n其余 {len(valid)} 张将进入识别。')
        if not valid: return
        self.import_button.setEnabled(False); self.paste_button.setEnabled(False); self.manual_button.setEnabled(False)
        self.progress.setRange(0,len(valid)); self.progress.setValue(0); self.progress.show()
        self.worker=OCRWorker(valid); self.worker.progress.connect(self.ocr_progress); self.worker.ready.connect(self.ocr_ready); self.worker.start()

    def ocr_progress(self,i,n,name):
        self.progress.setValue(i); self.progress.setFormat(f'离线识别 {i+1}/{n} · {name}')

    def ocr_ready(self,results,errors):
        self.queue=list(results); self.progress.hide()
        if errors: QMessageBox.warning(self,'部分截图识别失败','\n'.join(Path(p).name+'：'+err for p,err in errors))
        QTimer.singleShot(0,self.next_review)

    def next_review(self):
        if not self.queue:
            self.import_button.setEnabled(True); self.paste_button.setEnabled(True); self.manual_button.setEnabled(True)
            self.drop_hint.setText('导入完成 · 拖入下一张报告，或按 Ctrl+V 粘贴截图')
            return
        path,row=self.queue.pop(0)
        keys=('mode','map','difficulty','kills','extracted','deaths','duration_seconds','loot')
        similar=[r for r in self.store.all() if row.get('duration_seconds') is not None and row.get('kills') is not None and all(r.get(k)==row.get(k) for k in keys)]
        if similar:
            row.setdefault('ocr_warnings',[]).append('与库中 '+similar[0]['played_at']+' 的战绩数值相同，可能已经收录；同一局请取消导入。')
        dlg=Review(row,path,self); dlg.setWindowTitle(f'核对作战报告 · 剩余 {len(self.queue)} 张')
        if dlg.exec()==QDialog.Accepted:
            try:
                self.store.save(dlg.row,path); self.reload_filters(); self.refresh()
            except Exception as e:
                QMessageBox.warning(self,'未保存',str(e))
        QTimer.singleShot(0,self.next_review)

    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'导出当前筛选结果','暗区战绩.csv','CSV (*.csv)')
        if not path: return
        try:
            with open(path,'w',encoding='utf-8-sig',newline='') as f:
                writer=csv.writer(f); writer.writerow(['时间','模式','地图','难度','结果','特遣队员淘汰','被击败','时长秒','带出价值','备注'])
                for r in self.visible_rows: writer.writerow([r['played_at'],r['mode'],r.get('map'),r.get('difficulty'),outcome(r),r.get('kills'),r.get('deaths') if r['mode'] in TEAM_MODES else (None if r.get('extracted') is None else int(not r['extracted'])),r.get('duration_seconds'),r.get('loot'),r.get('note','')])
            QMessageBox.information(self,'已导出',path)
        except Exception as e: QMessageBox.warning(self,'导出失败',str(e))

    def backup(self):
        path,_=QFileDialog.getSaveFileName(self,'备份全部记录和截图',f'暗区战绩备份-{datetime.now():%Y%m%d}.zip','ZIP (*.zip)')
        if path:
            try: self.store.backup(path); QMessageBox.information(self,'备份完成',path)
            except Exception as e: QMessageBox.warning(self,'备份失败',str(e))

    def restore(self):
        path,_=QFileDialog.getOpenFileName(self,'选择本软件导出的备份','','ZIP (*.zip)')
        if not path: return
        if QMessageBox.question(self,'恢复备份','备份中的相同 ID 记录会覆盖本机版本，其他记录保留。\n恢复前将自动备份当前数据库和截图。是否继续？',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
        try:
            before=self.store.path/f'before-restore-{datetime.now():%Y%m%d-%H%M%S}.zip'; self.store.backup(before)
            n=self.store.restore(path); self.reload_filters(); self.refresh(); QMessageBox.information(self,'恢复完成',f'已恢复 / 合并 {n} 场。\n恢复前备份：{before}')
        except Exception as e: QMessageBox.warning(self,'恢复失败',str(e))

    def help(self):
        QMessageBox.information(self,'使用说明',
            '1. 每场结束后保存个人作战报告截图，拖入本窗口或 Ctrl+V。\n'
            '2. 软件离线识别地图、难度、结果及特遣队员淘汰数，核对后保存。\n'
            '3. 作战报告里的 18:30 是对局时长，通常没有日期；导入时间需手动核对。\n'
            '4. 历史列表的总淘汰数含 AI，不能替代特遣队员淘汰数。\n'
            '5. 新用户从空数据开始；升级保留已有本机战绩。双击记录查看原图、纠错。\n'
            '6. 无死亡且有淘汰时 KD 显示 ∞；无可计算样本显示 —。未知关键字段不参与 KD。\n'
            '7. 重复原图会自动跳过；裁剪、重新压缩的同场截图请核对日期以防重复。\n\n'
            '1.2 新增自动采集：先打开游戏个人主页的历史战绩，再点击自动采集。\n'
            '采集期间勿操作鼠标，F8 或切换窗口停止。结果独立暂存，核对后才合并新增。\n'
            '主页仅显示战局数、三种难度的 KD、击败特遣队员数。\n'
            '感染区计入封锁，重度感染区计入强化封锁；其他活动和团队模式仅保留在历史中。\n'
            'KD 显示一位小数，整数省略小数；悬停查看精度、样本数和公式。\n'
            '历史筛选仅影响历史列表和 CSV，不改变主页的全部统计（含感染区）。\n\n'
            f'数据目录：{self.store.path}\n数据仅保存在本机，无需账号或 API Key。')

    def closeEvent(self,event):
        capture_worker=getattr(getattr(self,'capture_dialog',None),'worker',None)
        if capture_worker and capture_worker.isRunning():
            capture_worker.requestInterruption(); event.ignore(); return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'识别进行中','请等待当前识别完成后关闭。'); event.ignore(); return
        for p in self.tempfiles:
            try: Path(p).unlink(missing_ok=True)
            except OSError: pass
        self.store.close(); event.accept()

def main():
    app=QApplication(sys.argv); app.setApplicationName('ABI-KD'); app.setWindowIcon(QIcon(str(resources()/'assets/app-icon.ico'))); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    folder=default_data_dir(); folder.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=folder/'app.log',level=logging.INFO,encoding='utf-8')
    def exception_hook(kind,value,tb):
        logging.error('Unhandled exception',exc_info=(kind,value,tb))
        QMessageBox.critical(None,'操作未完成',f'{value}\n详细日志：{folder / "app.log"}')
    sys.excepthook=exception_hook
    lock=QLockFile(str(folder/'app.lock'))
    if not lock.tryLock(100):
        QMessageBox.information(None,'已在运行','该数据目录已有一个暗区战绩窗口，请使用现有窗口。'); return 0
    store=Store(folder); win=Window(store); win.show()
    if '--capture' in sys.argv: QTimer.singleShot(250,win.capture_history)
    if '--smoke-test' in sys.argv:
        # Packaging check exercises Qt, bundled models and a synthetic, non-personal OCR fixture.
        from ocr import Recognizer
        result=Recognizer().recognize(resources()/'assets'/'ocr-self-test.png')
        overview={'battles':win.dashboard.battles.text(),'kills':win.dashboard.kills.text(),'kd':[w.text() for w in win.dashboard.kd_values],'icon':not win.windowIcon().isNull()}
        (folder/'smoke-test.json').write_text(json.dumps({'count':len(store.all()),'stats':statistics(store.all()),'ocr':result,'overview':overview},ensure_ascii=False,indent=2),encoding='utf8')
        QTimer.singleShot(1500,win.close)
    return app.exec()

if __name__=='__main__': sys.exit(main())
