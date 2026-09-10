import io, time, threading, secrets
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import numpy as np
import soundfile as sf
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import Field
from . import store,engine,providers,audio,sample,reports
from .models import Project,Settings,Strict,RenderConfig

POOL=ThreadPoolExecutor(max_workers=1)
BUSY=set()

@asynccontextmanager
async def lifespan(app):
    store.init()
    for f in (store.DATA/'jobs').glob('*.json'):
        job=store.read(f)
        if job.get('status') in ('queued','running'):
            job.update(status='failed',message='程序上次中断；可重新提交，已完成的配音缓存保留')
            store.write(f,job)
    yield

app=FastAPI(title='循意生境 · 本机工作台',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=store.ROOT/'web'),name='static')

@app.middleware('http')
async def local_only(request,call_next):
    host=request.headers.get('host','').split(':')[0]
    if host not in ('127.0.0.1','localhost','testserver'):
        return JSONResponse({'detail':'仅允许本机访问'},status_code=403)
    origin=request.headers.get('origin')
    if origin and urlparse(origin).netloc!=request.headers.get('host'):
        return JSONResponse({'detail':'禁止跨站请求'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"
    return response

@app.exception_handler(ValueError)
async def invalid(request,exc): return JSONResponse({'detail':str(exc)[:500]},status_code=400)

@app.exception_handler(FileNotFoundError)
async def missing(request,exc): return JSONResponse({'detail':'文件或工程不存在'},status_code=404)

@app.exception_handler(RequestValidationError)
async def validation(request,exc):
    # Do not echo submitted credentials in FastAPI's default error payload.
    return JSONResponse({'detail':'输入无效：'+'；'.join('.'.join(map(str,e['loc']))+': '+e['msg'] for e in exc.errors())[:800]},status_code=422)

@app.get('/')
def index(): return FileResponse(store.ROOT/'web'/'index.html')

@app.get('/api/status')
def status():
    s=store.settings(); rows=store.ledger()
    return dict(audio_decoder_version=audio.DECODER_VERSION,script_parser_version=providers.PARSER_VERSION,profiles=[dict(id=p,available=(store.DATA/'hrtf'/f'{p}.sofa').exists()) for p in ['H3','H4','H5']],
        deepseek_configured=bool(s.deepseek_key),minimax_configured=bool(s.minimax_key),
        spent_estimate=sum(r['charged_estimate'] for r in rows),budget=s.budget,rates_confirmed=s.rates_confirmed,voices=providers.VOICES)

@app.get('/api/settings')
def get_settings():
    s=store.settings().model_dump(); s.pop('deepseek_key'); s.pop('minimax_key')
    return s

@app.put('/api/settings')
def set_settings(value:Settings):
    with store.LOCK:
        if BUSY: raise HTTPException(409,'任务进行中，结束后再修改服务设置')
        old=store.settings()
        if not value.deepseek_key: value.deepseek_key=old.deepseek_key
        if not value.minimax_key: value.minimax_key=old.minimax_key
        store.write(store.DATA/'settings.json',value.model_dump())
    return {'saved':True}

@app.get('/api/ledger')
def get_ledger(): return store.ledger()

@app.get('/api/assets')
def get_assets(): return engine.assets()

@app.post('/api/assets')
async def upload(file:UploadFile=File(...)):
    raw=await file.read(20*1024*1024+1)
    if len(raw)>20*1024*1024: raise ValueError('上传文件最大20MB')
    try:
        info=sf.info(io.BytesIO(raw))
        if info.duration>180 or info.channels>2 or info.duration<=0: raise ValueError()
        a,sr=sf.read(io.BytesIO(raw),dtype='float32',always_2d=True)
        if not np.isfinite(a).all(): raise ValueError()
    except Exception: raise ValueError('请上传不超过180秒、单声道或双声道的有效 WAV/FLAC/OGG 文件') from None
    aid='upload_'+store.uid(); path=store.path_for('assets',aid,'wav')
    sf.write(path,a,sr,subtype='PCM_16')
    asset=dict(id=aid,name=(file.filename or '用户素材')[:100],kind='sfx',filename=path.name,duration=info.duration,source='用户上传',license='用户提供；自行确认使用权',synthetic=False)
    with store.LOCK:
        rows=store.read(store.DATA/'assets'/'uploads.json',[]); rows.append(asset); store.write(store.DATA/'assets'/'uploads.json',rows)
    return asset

@app.get('/api/assets/{aid}/audio')
def asset_audio(aid:str): return FileResponse(engine.asset_path(aid),media_type='audio/wav')

@app.get('/api/projects')
def list_projects():
    rows=[store.read(f) for f in (store.DATA/'projects').glob('*.json')]
    return [dict(id=p['id'],title=p['title'],revision=p['revision'],outputs=len(p['outputs'])) for p in sorted(rows,key=lambda p:p.get('revision',0),reverse=True)]

@app.post('/api/projects')
def create_project(p:Project):
    p.id=store.uid(); p.revision=0; p.outputs=[]
    store.save_project(p); return p

@app.get('/api/example')
def example(): return dict(title='十一点十七分',source=sample.TEXT)

@app.get('/api/projects/{pid}')
def get_project(pid:str): return store.project(pid)

@app.put('/api/projects/{pid}')
def update_project(pid:str,p:Project):
    with store.LOCK:
        if pid in BUSY: raise HTTPException(409,'工程任务进行中，请等待完成再保存')
        old=store.project(pid)
        if p.id!=pid or p.revision!=old.revision: raise HTTPException(409,'工程版本已更新，请重新打开')
        p.outputs=old.outputs; p.revision+=1
        store.save_project(p)
    return p

def submit(pid,operation):
    with store.LOCK:
        if pid in BUSY: raise HTTPException(409,'该工程已有任务运行')
        BUSY.add(pid)
        jid=store.uid(); job=dict(id=jid,project_id=pid,status='queued',message='等待处理',progress=0,created_at=time.time())
        store.write(store.path_for('jobs',jid),job)
    def work():
        def progress(message,value):
            job.update(status='running',message=message,progress=value); store.write(store.path_for('jobs',jid),job)
        try:
            progress('开始处理',.02)
            result=operation(progress)
            job.update(status='complete',message='已完成',progress=1,result=result)
        except Exception as exc:
            # Provider adapters return sanitized messages; unexpected errors never expose payloads.
            message=str(exc)[:500] if isinstance(exc,(ValueError,FileNotFoundError)) else f'处理失败（{type(exc).__name__}），已有成品与缓存保留'
            job.update(status='failed',message=message)
        finally:
            store.write(store.path_for('jobs',jid),job)
            with store.LOCK: BUSY.discard(pid)
    POOL.submit(work)
    return job

class ScriptRequest(Strict):
    online: bool = True

@app.post('/api/projects/{pid}/script')
def script(pid:str,request:ScriptRequest):
    store.project(pid)
    def operation(progress):
        p=store.project(pid)
        progress('分析角色、改编与空间事件',.15)
        result=providers.make_script(p,engine.assets(),request.online)
        result.revision+=1; store.save_project(result)
        return {'project_id':pid}
    return submit(pid,operation)

class GenerateRequest(Strict):
    allow_paid: bool = True

@app.get('/api/projects/{pid}/estimate')
def estimate(pid:str): return engine.estimate(store.project(pid))

@app.post('/api/projects/{pid}/generate')
def generate(pid:str,request:GenerateRequest):
    store.project(pid)
    def operation(progress):
        p=store.project(pid)
        output,timeline=engine.generate(p,request.allow_paid,progress)
        p.outputs.append(output); p.metrics=output['metrics']; store.save_project(p)
        return dict(output=output,timeline=timeline)
    return submit(pid,operation)

@app.get('/api/jobs/{jid}')
def get_job(jid:str):
    result=store.read(store.path_for('jobs',jid))
    if result is None: raise FileNotFoundError()
    return result

@app.get('/api/jobs')
def jobs(): return sorted([store.read(p) for p in (store.DATA/'jobs').glob('*.json')],key=lambda j:j['created_at'],reverse=True)[:30]

@app.get('/api/renders/{rid}/{kind}')
def download(rid:str,kind:str):
    if kind in ('report','csv'):
        path=store.path_for('renders',rid,'json')
        if not path.exists(): raise FileNotFoundError()
        manifest=store.read(path)
        content=reports.html_text(manifest,engine.assets()) if kind=='report' else reports.csv_bytes(manifest,engine.assets())
        ext='html' if kind=='report' else 'csv'
        return Response(content,media_type='text/html' if kind=='report' else 'text/csv',
            headers={'Content-Disposition':f'attachment; filename="{rid}-timeline.{ext}"'})
    mapping={'audio':'wav','manifest':'json','bundle':'zip'}
    if kind not in mapping: raise HTTPException(404)
    path=store.path_for('renders',rid,mapping[kind])
    if not path.exists(): raise FileNotFoundError()
    return FileResponse(path,media_type='audio/wav' if kind=='audio' else None,filename=None if kind=='audio' else path.name)

class CalibrationRequest(Strict):
    profile: str = Field('H3',pattern='^H[345]$')
    direction: str = Field('front',pattern='^(front|back|up|down|left|right|near|far|move)$')
    room: float = Field(.18,ge=0,le=.6)
    blind: bool = False

DIRECTIONS={'front':(0,0,2),'back':(0,0,-2),'up':(0,2,.2),'down':(0,-2,.2),'left':(-2,0,0),'right':(2,0,0),'near':(0,0,.6),'far':(0,0,6),'move':(-3,0,2)}

@app.post('/api/calibration')
def calibration(req:CalibrationRequest):
    trial=store.uid(); direction=secrets.choice(list(DIRECTIONS)) if req.blind else req.direction
    def operation(progress):
        path=store.DATA/'hrtf'/f'{req.profile}.sofa'
        if not path.exists(): raise ValueError('请先安装HRTF素材')
        pos=DIRECTIONS[direction]; points=[dict(t=0,x=pos[0],y=pos[1],z=pos[2])]
        if direction=='move': points.append(dict(t=3,x=3,y=0,z=2))
        # Same deterministic broadband probe for all directions; no loudness normalization per trial.
        rng=np.random.default_rng(42); t=np.arange(audio.SR*4)/audio.SR
        probe=rng.normal(0,.07,len(t))*(.25+.75*(np.sin(t*np.pi*2)**8))
        out=audio.spatialize(probe,points,audio.get_hrir(str(path)),req.room)
        peak=float(abs(out).max())
        if peak>.94: out*=.94/peak
        sf.write(store.path_for('calibration',trial,'wav'),out,audio.SR,subtype='PCM_24')
        store.write(store.path_for('calibration',trial),dict(id=trial,profile=req.profile,direction=direction,room=req.room,blind=req.blind,created_at=time.time()))
        return dict(trial=trial,audio=f'/api/calibration/{trial}/audio',direction=None if req.blind else direction)
    return submit('calibration',operation)

@app.get('/api/calibration/{trial}/audio')
def calibration_audio(trial:str): return FileResponse(store.path_for('calibration',trial,'wav'),media_type='audio/wav')

class Feedback(Strict):
    guess: str = Field(max_length=30)
    rating: int = Field(3,ge=1,le=5)
    notes: str = Field('',max_length=500)

@app.post('/api/calibration/{trial}/feedback')
def feedback(trial:str,value:Feedback):
    path=store.path_for('calibration',trial); row=store.read(path)
    if row is None: raise FileNotFoundError()
    row['feedback']=value.model_dump(); store.write(path,row)
    return dict(direction=row['direction'],correct=value.guess==row['direction'])

@app.get('/api/calibration-results')
def calibration_results():
    return [store.read(f) for f in (store.DATA/'calibration').glob('*.json') if store.read(f).get('feedback')]
