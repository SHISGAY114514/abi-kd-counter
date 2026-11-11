"""Local data, explicit statistical semantics, and portable backups."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

TEAM_MODES = ('团队竞技', '武器升级', '歼灭战')
MODES = ('战术行动',) + TEAM_MODES
MAPS = ('电视台', '农场', '山谷', '北部山区', '前线要塞', '机场')
DIFFICULTIES = ('普通', '封锁区', '强化封锁区', '机密', '绝密', '感染区', '重度感染区', '物资争夺战') + TEAM_MODES

def resources():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).parent))

def default_data_dir():
    return Path(os.environ.get('ABI_KD_DATA_DIR') or Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ABI-KD')

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()

def validate(r):
    r = dict(r)
    datetime.strptime(r['played_at'], '%Y-%m-%d %H:%M')
    if r.get('mode') not in MODES: raise ValueError('请选择有效模式')
    for key in ('kills', 'deaths', 'duration_seconds', 'loot'):
        v = r.get(key)
        if v is not None and (type(v) is not int or v < 0): raise ValueError(f'{key} 必须为非负整数或未知')
    for key in ('extracted', 'victory'):
        if r.get(key) is not None and type(r[key]) is not bool: raise ValueError(f'{key} 必须为布尔值或未知')
    if r['mode'] in TEAM_MODES: r['extracted'] = None
    else: r['deaths'] = None
    for key in ('map', 'difficulty', 'note'):
        if not isinstance(r.get(key, ''), str): raise ValueError(f'{key} 必须是文字')
    return r

def complete(r):
    return r.get('kills') is not None and (r.get('deaths') is not None if r['mode'] in TEAM_MODES else r.get('extracted') is not None)

def statistics(rows, team=False):
    relevant = [r for r in rows if (r['mode'] in TEAM_MODES) == team]
    valid = [r for r in relevant if complete(r)]
    kd_kills = sum(r['kills'] for r in valid)
    kill_rows = [r for r in relevant if r.get('kills') is not None]
    kills = sum(r['kills'] for r in kill_rows)
    deaths = sum(r['deaths'] if team else int(r['extracted'] is False) for r in valid)
    outcome_key = 'victory' if team else 'extracted'
    outcome_rows = [r for r in relevant if r.get(outcome_key) is not None]
    successes = sum(r[outcome_key] is True for r in outcome_rows)
    outcomes = len(outcome_rows)
    kd = kd_kills / deaths if deaths else (float('inf') if kd_kills else None)
    loot_rows = [] if team else [r for r in relevant if r.get('loot') is not None]
    loot_total = sum(r['loot'] for r in loot_rows)
    paired_loot = [r for r in loot_rows if r.get('extracted') is not None]
    loot_failures = sum(r['extracted'] is False for r in paired_loot)
    paired_value = sum(r['loot'] for r in paired_loot)
    profit_ratio = paired_value/loot_failures if loot_failures else (float('inf') if paired_value else None)
    durations = [r['duration_seconds'] for r in relevant if r.get('duration_seconds') is not None]
    return dict(total=len(relevant), valid=len(valid), pending=len(relevant)-len(valid), kills=kills, deaths=deaths,
                kd=kd, successes=successes, rate=successes/outcomes if outcomes else None,
                average=kills/len(kill_rows) if kill_rows else None, kd_kills=kd_kills, kill_samples=len(kill_rows),
                outcome_samples=outcomes, failures=outcomes-successes,
                loot_total=loot_total if loot_rows else None, loot_average=loot_total/len(loot_rows) if loot_rows else None,
                loot_max=max((r['loot'] for r in loot_rows),default=None),loot_samples=len(loot_rows),
                profit_ratio=profit_ratio,profit_samples=len(paired_loot),profit_failures=loot_failures,
                duration_total=sum(durations) if durations else None, duration_samples=len(durations),
                duration_average=sum(durations)/len(durations) if durations else None)

def compact_money(value):
    if value is None: return '—'
    if value == float('inf'): return '∞'
    for threshold,suffix in ((1_000_000_000,'B'),(1_000_000,'M'),(1_000,'K')):
        if abs(value)>=threshold: return f'{value/threshold:.1f}{suffix}'
    return f'{value:,.0f}'

def fingerprint(r):
    return tuple(r.get(k) for k in ('played_at', 'mode', 'map', 'difficulty', 'kills', 'extracted', 'deaths', 'duration_seconds'))

class Store:
    def __init__(self, path=None, seed=True):
        self.path = Path(path or default_data_dir())
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path/'images').mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.path/'matches.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS matches(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        # Public releases always start empty; existing databases are retained.
        self.db.commit()

    def all(self):
        return sorted([json.loads(v[0]) for v in self.db.execute('SELECT payload FROM matches')], key=lambda r:r['played_at'], reverse=True)

    def image(self, r):
        return self.path/'images'/Path(r.get('evidence') or '_missing').name

    def duplicate(self, r, image_hash=None):
        for old in self.all():
            if old['id'] == r.get('id'): continue
            if image_hash and old.get('image_hash') == image_hash: return old
            if fingerprint(old) == fingerprint(r): return old
        return None

    def save(self, row, source=None, allow_duplicate=False):
        r = validate(row)
        h = sha256(source) if source else r.get('image_hash')
        if not allow_duplicate and self.duplicate(r, h): raise ValueError('该截图或相同对局已经存在，请编辑已有记录，避免重复统计。')
        r['id'] = r.get('id') or str(uuid.uuid4())
        if source:
            name = h + Path(source).suffix.lower()
            target = self.path/'images'/name
            if Path(source).resolve() != target.resolve(): shutil.copy2(source, target)
            r.update(evidence=name, image_hash=h)
        self.db.execute('INSERT OR REPLACE INTO matches VALUES(?,?)', (r['id'], json.dumps(r, ensure_ascii=False)))
        self.db.commit()
        return r

    def delete(self, id_):
        self.db.execute('DELETE FROM matches WHERE id=?', (id_,))
        self.db.commit()

    def backup(self, dest):
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
            data = self.all()
            z.writestr('manifest.json', json.dumps({'version':1, 'matches':data}, ensure_ascii=False, indent=2))
            for name in {Path(r.get('evidence') or '').name for r in data}:
                p = self.path/'images'/name
                if p.is_file(): z.write(p, 'images/'+name)

    def restore(self, source):
        # Validate the entire archive before any mutation; merge by stable id.
        with zipfile.ZipFile(source) as z:
            if sum(i.file_size for i in z.infolist()) > 4_000_000_000: raise ValueError('备份过大')
            manifest = json.loads(z.read('manifest.json'))
            if manifest.get('version') != 1: raise ValueError('不支持的备份版本')
            rows = [validate(r) for r in manifest['matches']]
            images = {}
            for r in rows:
                if not isinstance(r.get('id'), str): raise ValueError('备份记录缺少 ID')
                name = r.get('evidence')
                if name:
                    if Path(name).name != name or '/' in name or '\\' in name: raise ValueError('无效图片路径')
                    key = 'images/'+name
                    if key not in z.namelist(): raise ValueError('备份缺少截图')
                    images[name] = z.read(key)
            for name, data in images.items(): (self.path/'images'/name).write_bytes(data)
            with self.db:
                for r in rows:
                    self.db.execute('INSERT OR REPLACE INTO matches VALUES(?,?)',(r['id'],json.dumps(r,ensure_ascii=False)))
            return len(rows)

    def close(self): self.db.close()
