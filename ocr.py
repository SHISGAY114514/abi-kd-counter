"""Offline report recognition. Never substitute total eliminations for operator kills."""
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from core import MAPS, DIFFICULTIES, TEAM_MODES

def normalize(s):
    return re.sub(r'\s+', '', s).replace('：', ':').replace('，', ',')

def boxes(raw):
    return [dict(text=normalize(t), score=float(c), x=min(p[0] for p in quad), y=min(p[1] for p in quad),
                 right=max(p[0] for p in quad), bottom=max(p[1] for p in quad)) for quad,t,c in raw]

def numeric_below(items, label):
    if not label: return None, 0
    h = max(label['bottom']-label['y'], 8)
    candidates = []
    for b in items:
        text = b['text'].replace(',', '')
        if not re.fullmatch(r'\d+', text): continue
        dy = b['y']-label['bottom']
        dx = abs(b['x']-label['x'])
        if -h*.45 <= dy <= h*3.5 and dx < h*1.6:
            candidates.append((dx + abs(dy)*.5, int(text), b['score']))
    if not candidates: return None, 0
    _,value,score = min(candidates)
    return value, score

def find_label(items, kind):
    def quality(b):
        t=b['text']
        if kind=='kills':
            if '特' not in t or ('队' not in t and '员' not in t): return 0
            return SequenceMatcher(None,t,'淘汰特遣队员数').ratio()
        if kind=='total': return SequenceMatcher(None,t,'总淘汰').ratio() if t.startswith('总') else 0
        if kind=='deaths': return SequenceMatcher(None,t,'被击败').ratio() if '败' in t else 0
        if kind=='loot': return SequenceMatcher(None,t,'带出总价值').ratio() if '价值' in t else 0
        return 0
    ranked = sorted(items,key=quality,reverse=True)
    return ranked[0] if ranked and quality(ranked[0]) >= .55 else None

def parse(raw):
    items=boxes(raw)
    texts=[b['text'] for b in items]
    joined='\n'.join(texts)
    row=dict(played_at=datetime.now().strftime('%Y-%m-%d %H:%M'), map='', difficulty='', mode='战术行动',
             kills=None, deaths=None, extracted=None, victory=None, duration_seconds=None, loot=None,
             source='截图离线识别', note='', reviewed=False)
    warnings=['报告通常不含开局日期；时间暂用导入时刻，请核对。']
    header=next((b for b in items if any(m in b['text'] for m in MAPS) and ('行动' in b['text'] or '-' in b['text'])),None)
    if not header: header=next((b for b in items if any(m in b['text'] for m in MAPS)),None)
    ht=header['text'] if header else ''
    row['map']=next((m for m in MAPS if m in ht),'')
    row['difficulty']=next((d for d in sorted(DIFFICULTIES,key=len,reverse=True) if d in ht),'')
    if row['difficulty'] in TEAM_MODES: row['mode']=row['difficulty']
    team=row['mode'] in TEAM_MODES
    # Restrict outcomes to report heading, avoiding unrelated teammate text.
    outcome_text=' '.join(b['text'] for b in items if header and b['y']>=header['y'] and b['y']<header['bottom']+140 and abs(b['x']-header['x'])<100)
    if any(t in outcome_text for t in ('行动终止','撤离失败','撤出失败','行动失败','败退')): result=False
    elif any(t in outcome_text for t in ('行动成功','成功撤离','成功撤出')): result=True
    else: result=None
    row['victory' if team else 'extracted']=result
    label=find_label(items,'total' if team else 'kills')
    row['kills'], confidence=numeric_below(items,label)
    if confidence < .80:
        row['kills']=None
        warnings.append('特遣队员淘汰数不清晰，需核对；没有使用总淘汰数。' if not team else '团队淘汰数不清晰，需核对。')
    if team: row['deaths'],_=numeric_below(items,find_label(items,'deaths'))
    else: row['loot'],_=numeric_below(items,find_label(items,'loot'))
    # A separator can be read as a leading 1. Durations are two minute digits.
    match=re.search(r'(\d{2})[:;](\d{2})(?:\D*)$', ht)
    if match and int(match[2])<60: row['duration_seconds']=int(match[1])*60+int(match[2])
    if not row['map']: warnings.append('未识别地图，请选择。')
    if not row['difficulty']: warnings.append('未识别难度，请选择。')
    if result is None: warnings.append('未识别行动结果，请核对。')
    if not label: warnings.append('请导入个人作战报告；历史列表的总淘汰数包含 AI，不能用于此 KD。')
    row['ocr_warnings']=warnings
    row['ocr_text']=joined
    if '历史战绩' in joined:
        row.update(kills=None,deaths=None,extracted=None,victory=None,duration_seconds=None,loot=None)
    return row

class Recognizer:
    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        self.engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)

    def recognize(self,path,_retry=False):
        from PIL import Image, ImageEnhance, ImageOps
        import numpy as np
        import cv2
        with Image.open(path) as original:
            img=ImageOps.exif_transpose(original).convert('RGB')
        if img.width*img.height>40_000_000: raise ValueError('图片超过 4000 万像素，请缩小后导入')
        if _retry and img.width<1300:
            factor=min(2.5,1440/img.width)
            img=img.resize((round(img.width*factor),round(img.height*factor)),Image.Resampling.LANCZOS)
        enhanced=ImageEnhance.Contrast(ImageEnhance.Brightness(img).enhance(1.7)).enhance(1.2)
        raw,_=self.engine(np.array(enhanced),det_limit_side_len=1920)
        row=parse(raw or [])
        if '历史战绩' in row['ocr_text']: return row
        # Small numerals are sometimes omitted. Re-read the numeric area at 3×,
        # anchored only to the specific operator label, never the AI/total column.
        items=boxes(raw or [])
        label=find_label(items,'total' if row['mode'] in TEAM_MODES else 'kills')
        if label and row['kills'] is None:
            h=max(label['bottom']-label['y'],8)
            x,y=label['x'],label['bottom']
            crop=img.crop((max(0,x-h*.5), max(0,y-h*.25),min(img.width,x+h*3),min(img.height,y+h*2.5)))
            crop=crop.resize((crop.width*4,crop.height*4))
            cr,_=self.engine(np.array(crop),det_limit_side_len=960)
            nums=[(t,c) for _,t,c in cr or [] if re.fullmatch(r'\d{1,3}',t) and c>.85]
            if len(nums)==1:
                row['kills']=int(nums[0][0])
                row['ocr_warnings']=[w for w in row['ocr_warnings'] if '淘汰数不清晰' not in w]
        if label and row['kills'] is None:
            # Thin single digits may never form a text-detection box. Isolate the
            # numeric line and require agreement across binarization thresholds.
            h=max(label['bottom']-label['y'],8); x=label['x']; y=label['bottom']
            region=img.crop((max(0,x-h*.12),max(0,y-h*.25),min(img.width,x+h*2.65),min(img.height,y+h)))
            gray=cv2.cvtColor(np.array(region),cv2.COLOR_RGB2GRAY)
            votes=[]
            for threshold in (70,100,130):
                mask=(gray>threshold).astype('uint8')*255
                points=cv2.findNonZero(mask)
                if points is None: continue
                a,b,w,hh=cv2.boundingRect(points)
                if hh<4 or w<1: continue
                cut=mask[b:b+hh,a:a+w]
                cut=cv2.copyMakeBorder(cut,3,3,3,3,cv2.BORDER_CONSTANT,value=0)
                cut=cv2.cvtColor(255-cut,cv2.COLOR_GRAY2RGB)
                rec,_=self.engine(cut,use_det=False,use_cls=False)
                for t,c in rec or []:
                    if re.fullmatch(r'\d{1,3}',t) and c>.4: votes.append((int(t),c))
            if votes and len({v for v,c in votes})==1 and (len(votes)==3 or len(votes)>=2 and max(c for v,c in votes)>.85):
                row['kills']=votes[0][0]
                row['ocr_warnings']=[w for w in row['ocr_warnings'] if '淘汰数不清晰' not in w]
        header=next((b for b in items if row['map'] and row['map'] in b['text']),None)
        if header:
            crop=img.crop((header['x'],header['y'],header['right'],header['bottom']))
            crop=crop.resize((crop.width*3,crop.height*3))
            rec,_=self.engine(np.array(crop),use_det=False,use_cls=False)
            if rec:
                m=re.search(r'(\d{2})[:：;](\d{2})(?:\D*)$',rec[0][0])
                if m and int(m[2])<60 and rec[0][1]>.85: row['duration_seconds']=int(m[1])*60+int(m[2])
            if row['duration_seconds'] is None:
                width=header['right']-header['x']
                region=img.crop((header['right']-width*.18,header['y'],header['right']+3,header['bottom']))
                gray=cv2.cvtColor(np.array(region),cv2.COLOR_RGB2GRAY)
                mask=(gray>100).astype('uint8')*255; points=cv2.findNonZero(mask)
                if points is not None:
                    x,y,w,h=cv2.boundingRect(points)
                    cut=cv2.copyMakeBorder(mask[y:y+h,x:x+w],3,3,3,3,cv2.BORDER_CONSTANT,value=0)
                    rec,_=self.engine(cv2.cvtColor(255-cut,cv2.COLOR_GRAY2RGB),use_det=False,use_cls=False)
                    if rec:
                        m=re.fullmatch(r'(\d{2})[:.：](\d{2})',rec[0][0])
                        if m and int(m[2])<60 and rec[0][1]>.9: row['duration_seconds']=int(m[1])*60+int(m[2])
        if not _retry and img.width<1300 and any(row.get(k) in (None,'') for k in ('map','difficulty','kills','deaths' if row['mode'] in TEAM_MODES else 'extracted')):
            retry=self.recognize(path,True)
            if retry['mode']!=row['mode'] and not row['difficulty'] and retry['difficulty']:
                row=retry
            elif retry['mode']==row['mode']:
                for key in ('map','difficulty','kills','deaths','extracted','victory','duration_seconds','loot'):
                    if row.get(key) in (None,'') and retry.get(key) not in (None,''):
                        row[key]=retry[key]
            row['ocr_warnings']=[w for w in row['ocr_warnings'] if not (row['kills'] is not None and '淘汰数不清晰' in w or row['map'] and '未识别地图' in w or row['difficulty'] and '未识别难度' in w or (row['victory'] is not None if row['mode'] in TEAM_MODES else row['extracted'] is not None) and '未识别行动结果' in w)]
        return row
