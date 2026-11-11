"""The three requested stats, in ordinary/lockdown/fortified order."""
import math
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QFrame
from core import statistics

STANDARD_DIFFICULTIES=('普通','封锁区','强化封锁区')

def standard_rows(rows):
    return [r for r in rows if r['mode']=='战术行动' and r.get('difficulty') in STANDARD_DIFFICULTIES]

def ratio(v):
    if v is None: return '—'
    if math.isinf(v): return '∞'
    return f'{v:.1f}'.rstrip('0').rstrip('.')

class Dashboard(QWidget):
    def __init__(self):
        super().__init__(); root=QVBoxLayout(self); root.setContentsMargins(30,26,30,16); root.setSpacing(22)
        scope=QLabel('战术行动  /  常规难度'); scope.setObjectName('muted'); root.addWidget(scope)
        battle=QFrame(); battle.setObjectName('banner'); bl=QVBoxLayout(battle); bl.setContentsMargins(26,22,26,22)
        title=QLabel('战局数'); title.setObjectName('muted'); self.battles=QLabel('—'); self.battles.setStyleSheet('font-size:58px;font-weight:300;background:transparent;')
        bl.addWidget(title); bl.addWidget(self.battles); root.addWidget(battle)
        panel=QFrame(); panel.setObjectName('card'); box=QVBoxLayout(panel); box.setContentsMargins(26,22,26,22); box.setSpacing(20)
        label=QLabel('KD'); label.setObjectName('muted'); box.addWidget(label)
        values=QHBoxLayout(); values.setSpacing(0); self.kd_values=[]
        for i,title in enumerate(('普通','封锁','强化封锁')):
            if i:
                line=QLabel('|'); line.setStyleSheet('font-size:38px;color:#527267;background:transparent;'); values.addWidget(line)
            column=QVBoxLayout(); column.setSpacing(9)
            value=QLabel('—'); value.setStyleSheet('font-size:48px;color:#e5f4e9;font-weight:300;background:transparent;'); value.setAlignment(Qt.AlignCenter)
            name=QLabel(title); name.setObjectName('muted'); name.setAlignment(Qt.AlignCenter)
            column.addWidget(value); column.addWidget(name); values.addLayout(column,1); self.kd_values.append(value)
        box.addLayout(values); separator=QFrame(); separator.setFrameShape(QFrame.HLine); separator.setStyleSheet('color:#385347;'); box.addWidget(separator)
        defeated=QHBoxLayout(); title=QLabel('击败特遣队员数'); title.setObjectName('muted'); self.kills=QLabel('—'); self.kills.setStyleSheet('font-size:27px;color:#a6e7be;background:transparent;')
        defeated.addWidget(title); defeated.addStretch(); defeated.addWidget(self.kills); box.addLayout(defeated); root.addWidget(panel)
        self.note=QLabel('统计普通、封锁、强化封锁；活动和团队模式保留在历史战绩。\nKD = 特遣队员淘汰数 ÷ 撤离失败场次，未知字段不补零。'); self.note.setWordWrap(True); self.note.setObjectName('caption'); root.addWidget(self.note)
        root.addStretch(1)

    def update_data(self,rows,team=False):
        rows=standard_rows(rows); s=statistics(rows)
        self.battles.setText(str(s['total'])); self.kills.setText(str(s['kills']))
        self.kills.setToolTip(f'只统计特遣队员，不计 AI；淘汰数已知 {s["kill_samples"]}/{s["total"]} 场。')
        for difficulty,label in zip(STANDARD_DIFFICULTIES,self.kd_values):
            group=[r for r in rows if r['difficulty']==difficulty]; g=statistics(group); value=g['kd']
            label.setText(ratio(value))
            precision='暂无完整数据' if value is None else '∞' if math.isinf(value) else f'{value:.4f}'
            label.setToolTip(f'{difficulty}：{g["kd_kills"]} 次淘汰 ÷ {g["deaths"]} 次撤离失败\n精确 KD：{precision}\n完整样本 {g["valid"]}/{g["total"]} 场。\n此处采用撤离失败口径，不宣称等同于三角洲官方计算。')
