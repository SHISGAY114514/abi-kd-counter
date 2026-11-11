"""Visual history crawler and isolated capture manifests (never writes Store)."""
import hashlib
import json
import re
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
from PIL import ImageEnhance
from core import MAPS, DIFFICULTIES, TEAM_MODES, complete
from ocr import Recognizer, normalize
from capture_windows import CaptureError, CaptureStopped, viewport


def history_date(text, now):
    m = re.search(r'(?<!\d)(\d{2})[./]?(\d{2})\s*(\d{2})[:：.]?(\d{2})(?!\d)', text)
    if not m: return None
    try:
        value = datetime(now.year, *map(int, m.groups()))
        if value > now+timedelta(days=1): value = value.replace(year=now.year-1)
        return value.strftime('%Y-%m-%d %H:%M')
    except ValueError: return None


def identity(row):
    return tuple(row.get(k, '') for k in ('played_at', 'mode', 'map', 'difficulty'))


def key_for(row):
    return hashlib.sha256(json.dumps(identity(row), ensure_ascii=False).encode()).hexdigest()[:24]


def is_report(row):
    text=row.get('ocr_text','')
    return bool('历史战绩' not in text and row.get('map') and row.get('difficulty') and
                (complete(row) or '作战历程' in text or '作战详情' in text or
                 row.get('mode') in TEAM_MODES and ('被击败' in text or '队伍信息' in text)))


def classify(row, existing):
    # An already-known timestamp/map/mode/difficulty is never overwritten even
    # when OCR disagrees about numbers. Report that disagreement for inspection.
    same = next((old for old in existing if identity(old) == identity(row)), None)
    if same:
        conflict = any(row.get(k) is not None and same.get(k) is not None and row[k] != same[k]
                       for k in ('kills', 'extracted', 'deaths'))
        return '已有记录（数值不同）' if conflict else '已有记录'
    if not complete(row) or not row.get('map') or not row.get('difficulty') or row.get('capture_needs_review'):
        return '待核对'
    return '新增'


def save_manifest(folder, manifest):
    folder = Path(folder); temporary = folder/'manifest.tmp'
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    temporary.replace(folder/'manifest.json')


class Reader:
    def __init__(self): self.recognizer = Recognizer()

    def text(self, image, region=(0, 0, 1, 1), scale=2):
        vx, vy, w, h = viewport(image.size)
        x1, y1, x2, y2 = region
        left, top = round(vx+x1*w), round(vy+y1*h)
        crop = image.crop((left, top, round(vx+x2*w), round(vy+y2*h)))
        crop = crop.resize((crop.width*scale, crop.height*scale))
        crop = ImageEnhance.Contrast(ImageEnhance.Brightness(crop).enhance(2)).enhance(1.2)
        raw, _ = self.recognizer.engine(np.array(crop), det_limit_side_len=1920)
        result = []
        for quad, text, score in raw or []:
            cx = sum(p[0] for p in quad)/4/scale+left
            cy = sum(p[1] for p in quad)/4/scale+top
            result.append(dict(text=normalize(text), score=float(score), x=(cx-vx)/w, y=(cy-vy)/h))
        return result

    def is_history(self, image):
        text = ''.join(b['text'] for b in self.text(image, (0.04, .01, .70, .14)))
        return '历史战绩' in text and '对局' in text and ('模式' in text or '结果' in text)

    def button(self, image, name):
        return next((b for b in self.text(image, (.84, .15, .96, .92)) if name in b['text']), None)

    def rows(self, image, now):
        items = self.text(image, (.255, .14, .49, .925))
        result = []
        for b in items:
            text = b['text']; date = history_date(text, now)
            # Clip edges can contain only fragments of a neighboring row.
            if not (.15 < b['y'] < .91): continue
            map_name = next((m for m in MAPS if m in text), '')
            if not date:
                if map_name and re.search(r'\d', text):
                    raise CaptureError('有历史行的日期未识别，已停止以免跳过：'+text)
                continue
            difficulty = next((d for d in sorted(DIFFICULTIES, key=len, reverse=True) if d in text), '')
            if not map_name or not difficulty:
                raise CaptureError('有历史行的地图或难度未识别，已停止以免错配：'+text)
            row = dict(played_at=date, map=map_name, difficulty=difficulty,
                       mode=difficulty if difficulty in TEAM_MODES else '战术行动', x=.35, y=b['y'])
            row['capture_key'] = key_for(row); result.append(row)
        return sorted(result, key=lambda r: r['y'])


class Collector:
    def __init__(self, desktop, folder, progress=lambda message: None, limit=1000, resume=False):
        self.desktop = desktop; self.folder = Path(folder); self.progress = progress; self.limit = limit
        self.folder.mkdir(parents=True, exist_ok=True)
        self.now = datetime.now(); self.reader = None
        self.manifest = dict(version=1, started_at=self.now.isoformat(timespec='seconds'),
                             state='running', message='', items=[], bottom_verified=False)
        self.seen = set()
        self.expected = set()
        if resume:
            old=json.loads((self.folder/'manifest.json').read_text(encoding='utf8'))
            if old.get('version')!=1 or old.get('state')=='complete': raise CaptureError('该批次不支持继续，请开始新采集。')
            for item in old['items']:
                if not (self.folder/Path(item['image']).name).is_file(): raise CaptureError('上次采集缺少原图，无法继续。')
                self.seen.add(item['list_entry']['capture_key'])
            self.manifest=old
            self.manifest.update(state='running',bottom_verified=False,resumed_at=self.now.isoformat(timespec='seconds'))
            self.manifest.pop('error_detail',None)

    def note(self, message):
        self.manifest['message'] = message; save_manifest(self.folder, self.manifest); self.progress(message)

    def history_screen(self):
        # Returning from reports can leave only the table header visible for
        # several seconds. Wait for populated rows without sending more input.
        deadline=time.monotonic()+20
        for _ in range(24):
            image = self.desktop.screenshot()
            if self.reader.is_history(image):
                # The navigation bar appears before the list's fade-in finishes.
                self.desktop.wait(.35)
                image = self.desktop.screenshot()
                if self.reader.rows(image,self.now): return image
            if time.monotonic()>=deadline: break
            self.desktop.wait(.5)
        raise CaptureError('未检测到“个人主页 → 历史战绩”列表，采集已停止。请打开该页面后重试。')

    def collapse(self, image):
        button = self.reader.button(image, '收起')
        if button:
            self.desktop.click(button['x'], button['y']); self.desktop.wait(.65)
            return self.history_screen()
        return image

    def start_page(self):
        image = self.desktop.screenshot()
        if self.reader.is_history(image): return self.collapse(image)
        # Personal profile may be on a neighboring tab. Only click an OCR-verified tab.
        tabs = self.reader.text(image, (.02, .01, .45, .10))
        tab = next((b for b in tabs if '历史战绩' in b['text']), None)
        if tab:
            self.desktop.click(tab['x'], tab['y']); self.desktop.wait(.6)
            return self.collapse(self.history_screen())
        # A report can be returned to the history page through the visible back arrow.
        words = ''.join(b['text'] for b in self.reader.text(image, (.17, .13, .60, .93)))
        if ('作战历程' in words and '行动' in words or
            any(mode in words for mode in TEAM_MODES) and ('被击败' in words or '结算奖励' in words)):
            return self.return_to_history()
        raise CaptureError('请先将游戏打开到个人主页（历史战绩），再开始自动采集。')

    def return_to_history(self):
        for attempt in range(3):
            self.desktop.click(.0278,.978);self.desktop.wait(.8)
            for _ in range(4):
                image=self.desktop.screenshot()
                if self.reader.is_history(image): return self.collapse(self.history_screen())
                self.desktop.wait(.35)
            # Retry only when the screen still positively matches a report.
            words=''.join(b['text'] for b in self.reader.text(image,(.17,.13,.60,.93)))
            report=('作战历程' in words and '行动' in words or any(mode in words for mode in TEAM_MODES) and ('被击败' in words or '结算奖励' in words))
            if not report: break
        raise CaptureError('返回历史列表未成功，已保存报告并停止。')

    def signature(self, image):
        rows = self.reader.rows(image, self.now)
        for _ in range(3):
            if rows: break
            self.desktop.wait(.5); image = self.history_screen(); rows = self.reader.rows(image,self.now)
        if not rows: raise CaptureError('未识别到完整的历史行。请确认列表已加载、截图清晰且未被遮挡。')
        return tuple(r['capture_key'] for r in rows), rows

    def to_top(self, image):
        previous, _ = self.signature(image); unchanged = 0
        for _ in range(80):
            self.desktop.scroll(1200); self.desktop.wait(.4)
            image = self.history_screen(); current, _ = self.signature(image)
            unchanged = unchanged+1 if current == previous else 0
            if unchanged >= 2:
                image.save(self.folder/'history_top.png'); return image
            previous = current
        raise CaptureError('无法确认列表顶部，已停止。')

    def inventory(self,image):
        """Enumerate the collapsed list first, independent of expansion scrolls."""
        entries={};previous=None;unchanged=0
        for _ in range(500):
            signature,rows=self.signature(image)
            for row in rows: entries[row['capture_key']]=row
            self.manifest['history_index']=list(entries.values())
            self.note(f'正在建立历史条目清单：已发现 {len(entries)} 场，已保存 {len(self.seen)} 份报告 · F8 停止')
            unchanged=unchanged+1 if signature==previous else 0
            if unchanged>=2:
                self.expected=set(entries)
                self.manifest['inventory_count']=len(entries)
                image.save(self.folder/'history_inventory_bottom.png')
                self.note(f'历史清单共 {len(entries)} 场，开始逐一核对并读取报告 · F8 停止')
                return self.to_top(image)
            previous=signature
            self.desktop.scroll(-480);self.desktop.wait(.5);image=self.history_screen()
        raise CaptureError('历史清单扫描未到达底部，已停止。')

    def collect_one(self, entry):
        self.note(f'正在打开第 {len(self.seen)+1} 场：{entry["played_at"]} {entry["map"]} {entry["difficulty"]} · F8 停止')
        self.desktop.click(entry['x'], entry['y']); self.desktop.wait(.4)
        image = self.history_screen(); button = self.reader.button(image, '作战报告')
        for _ in range(3):
            if button: break
            self.desktop.scroll(-240); self.desktop.wait(.35)
            image = self.history_screen(); button = self.reader.button(image, '作战报告')
        if not button: raise CaptureError('未找到展开行的“作战报告”按钮，已停止。')
        # Verify that the expanded report belongs to the clicked row.
        above = [r for r in self.reader.rows(image, self.now) if r['y'] < button['y']]
        # Expanding a row can auto-scroll its heading just behind the fixed table
        # header. Bring the heading back into view before matching its timestamp.
        for _ in range(3):
            if above or button['y']>=.30: break
            self.desktop.scroll(120);self.desktop.wait(.4);image=self.history_screen()
            button=self.reader.button(image,'作战报告')
            if not button: raise CaptureError('滚动后报告按钮不可见，已停止。')
            above=[r for r in self.reader.rows(image,self.now) if r['y']<button['y']]
        if not above or above[-1]['capture_key'] != entry['capture_key']:
            raise CaptureError('展开行与目标对局不一致，已停止以防报告错配。')
        self.desktop.click(button['x'], button['y']); self.desktop.wait(.7)
        report_path = self.folder/f'report_{len(self.seen)+1:03}.png'
        for attempt in range(3):
            image = self.desktop.screenshot(); image.save(report_path)
            row = self.reader.recognizer.recognize(report_path)
            if is_report(row): break
            self.desktop.wait(.6)
        else: raise CaptureError('作战报告未加载或无法识别，已保留当前截图并停止。')
        conflicts = [k for k in ('map', 'difficulty', 'mode') if row.get(k) != entry.get(k)]
        row.update(played_at=entry['played_at'], capture_key=entry['capture_key'], source='游戏窗口自动采集',
                   capture_needs_review=bool(conflicts), reviewed=False)
        row['ocr_warnings'] = [w for w in row.get('ocr_warnings', []) if '时间暂用导入' not in w]
        row['ocr_warnings'].append('时间来自历史列表，年份按采集日期推断。')
        if conflicts: row['ocr_warnings'].append('报告与列表字段不一致，请核对：'+', '.join(conflicts))
        self.manifest['items'].append(dict(row=row, image=report_path.name, list_entry=entry))
        self.seen.add(entry['capture_key']); self.note(f'已采集 {len(self.seen)} 场 · 数据暂存，尚未合并到战绩库 · F8 停止')
        return self.return_to_history()

    def run(self):
        try:
            self.note('正在加载离线识别模型……')
            self.reader = Reader(); self.desktop.activate(); image = self.start_page()
            self.note('正在定位历史列表顶部……'); image = self.to_top(image)
            image=self.inventory(image)
            unchanged = 0; previous = None; passes=0; last_pass_count=-1
            for _ in range(self.limit*3):
                signature, rows = self.signature(image)
                pending = [r for r in rows if r['capture_key'] not in self.seen]
                if pending:
                    if len(self.seen) >= self.limit: raise CaptureError('达到采集上限，已保留结果；未标记为全部完成。')
                    entry = pending[0]
                    # Give low rows room to expand before selecting; re-read after scrolling.
                    if entry['y'] > .70:
                        self.desktop.scroll(-240); self.desktop.wait(.4); image = self.history_screen()
                        updated = self.reader.rows(image, self.now)
                        relocated = next((r for r in updated if r['capture_key'] == entry['capture_key']), None)
                        if relocated: entry = relocated
                        else: raise CaptureError('滚动后目标对局不可见，已停止以免漏采。')
                    image = self.collect_one(entry); unchanged = 0; previous = None; continue
                unchanged = unchanged+1 if signature == previous else 0
                if unchanged >= 2:
                    missing=self.expected-self.seen
                    if missing:
                        passes+=1
                        if passes>4 or len(self.seen)==last_pass_count:
                            raise CaptureError(f'清单中仍有 {len(missing)} 场未采集到，已保留结果；请继续采集，不会标记全部完成。')
                        last_pass_count=len(self.seen)
                        self.note(f'正在补扫 {len(missing)} 场未读取报告，确保历史清单完整 · F8 停止')
                        image=self.to_top(image);previous=None;unchanged=0;continue
                    image.save(self.folder/'history_bottom.png')
                    self.manifest.update(state='complete', bottom_verified=True,inventory_verified=True)
                    self.note(f'采集完成：{len(self.seen)} 场；已连续两次确认列表到底。请核对后合并新增记录。')
                    break
                previous = signature
                self.desktop.scroll(-480); self.desktop.wait(.5); image = self.history_screen()
            else: raise CaptureError('翻页次数达到保护上限，未标记为全部完成。')
        except CaptureStopped as error:
            self.manifest['state'] = 'stopped'; self.note(str(error))
        except Exception as error:
            self.manifest['state'] = 'error'; self.manifest['error_detail'] = traceback.format_exc(); self.note(str(error))
            try: self.desktop.screenshot().save(self.folder/'failure.png')
            except Exception: pass
        finally:
            self.manifest['finished_at'] = datetime.now().isoformat(timespec='seconds')
            save_manifest(self.folder, self.manifest)
        return self.manifest


def merge_selected(store, folder, items):
    """Explicit UI-only commit. Existing records are always retained unchanged."""
    existing = store.all(); eligible = []
    for item in items:
        row = dict(item['row'])
        if classify(row, existing) != '新增': continue
        source = Path(folder)/Path(item['image']).name
        if not source.is_file(): raise ValueError('采集原图缺失，未合并。')
        row.pop('id', None); row['reviewed'] = True
        eligible.append((row, source)); existing.append(row)
    if not eligible: return 0
    backup = store.path/f'before-capture-{datetime.now():%Y%m%d-%H%M%S-%f}.zip'
    store.backup(backup)
    saved = 0
    for row, source in eligible:
        if store.duplicate(row): continue
        store.save(row, source); saved += 1
    return saved
