import json, os, threading, hashlib, time
from pathlib import Path
from .models import Settings, Project, uid

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('SPATIAL_DATA', ROOT/'data')).resolve()
LOCK = threading.RLock()

def init():
    for folder in ['projects','assets','hrtf','cache','renders','jobs','calibration']:
        (DATA/folder).mkdir(parents=True, exist_ok=True)

def read(path, default=None):
    return json.loads(path.read_text('utf-8')) if path.exists() else default

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_name(path.name+'.'+uid()+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2), 'utf-8')
    temp.replace(path)

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def path_for(folder, name, ext='json'):
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',name):
        raise ValueError('无效的文件ID')
    return DATA/folder/f'{name}.{ext}'

def settings():
    s=Settings.model_validate(read(DATA/'settings.json',{}))
    s.deepseek_key=os.environ.get('DEEPSEEK_API_KEY') or s.deepseek_key
    s.minimax_key=os.environ.get('MINIMAX_API_KEY') or s.minimax_key
    return s

def save_project(p):
    write(path_for('projects',p.id),p.model_dump())

def project(pid):
    v=read(path_for('projects',pid))
    if v is None: raise FileNotFoundError('工程不存在')
    return Project.model_validate(v)

def ledger():
    return read(DATA/'ledger.json',[])

def reserve(provider, estimate, metadata):
    with LOCK:
        rows=ledger()
        spent=sum(r['charged_estimate'] for r in rows)
        if spent+estimate>settings().budget:
            raise ValueError('费用估算将超过预算，已暂停付费调用。仍可编辑和渲染已有素材。')
        row=dict(id=uid(),provider=provider,charged_estimate=estimate,reserved=estimate,status='reserved',timestamp=time.time(),metadata=metadata)
        rows.append(row); write(DATA/'ledger.json',rows)
        return row['id']

def settle(rid, actual=None, usage=None, status='complete'):
    with LOCK:
        rows=ledger()
        row=next(r for r in rows if r['id']==rid)
        # Unknown network outcomes retain the entire reservation to avoid under-counting.
        if actual is not None: row['charged_estimate']=actual
        row.update(status=status,usage=usage or {})
        write(DATA/'ledger.json',rows)
