import time, zipfile, json
from pathlib import Path
import soundfile as sf
from . import store,providers,audio

def assets():
    return store.read(store.DATA/'assets'/'builtin.json',[])+store.read(store.DATA/'assets'/'uploads.json',[])+store.read(store.DATA/'assets'/'recorded.json',[])+store.read(store.DATA/'assets'/'demo.json',[])

def asset_path(aid):
    asset=next((a for a in assets() if a['id']==aid),None)
    if asset is None: raise ValueError('素材不存在：'+aid)
    path=(store.DATA/'assets'/asset['filename']).resolve()
    if path.parent!=store.DATA/'assets' or not path.is_file(): raise ValueError('素材文件缺失：'+aid)
    return path

def estimate(p):
    s=store.settings(); chars={c.id:c.voice for c in p.characters}; total=0; misses=0
    for e in p.events:
        if e.enabled and e.kind=='speech' and e.text.strip() and not e.asset_id:
            sig=providers.tts_signature(e,chars[e.character_id],s)
            if not any(store.path_for('cache',sig,ext).exists() for ext in ('wav','flac')):
                total+=providers.billable(e.text)*s.tts_per_10k/10000*1.1; misses+=1
    return dict(tts_estimate=total,uncached_utterances=misses,cached_utterances=sum(e.enabled and e.kind=='speech' for e in p.events)-misses)

def build_timeline(p,allow_paid,progress):
    voices={c.id:c.voice for c in p.characters}; paths={}; durations={}; hits=0
    active=[e for e in p.events if e.enabled and (e.kind!='speech' or e.text.strip())]
    # Verify all explicit assets before incurring any synthesis cost.
    for e in active:
        if e.asset_id or e.kind!='speech': paths[e.id]=asset_path(e.asset_id)
    for idx,e in enumerate(active):
        progress(f'准备声音 {idx+1}/{len(active)}',.1+.55*idx/max(1,len(active)))
        if e.id not in paths:
            paths[e.id],hit=providers.synthesize(e,voices[e.character_id],allow_paid); hits+=int(hit)
        info=sf.info(paths[e.id]); dur=info.frames/info.samplerate
        durations[e.id]=dur if e.kind=='speech' else e.duration or dur
    starts={}; cursor=0
    # Disabled adapted speech still acts as a zero-length anchor for replacement SFX.
    for e in p.events:
        if e.kind!='speech': continue
        before=[fx for fx in active if fx.kind!='speech' and fx.anchor_id==e.id and fx.placement=='before' and fx.start is None]
        for fx in before:
            starts[fx.id]=cursor+fx.offset
            cursor=starts[fx.id]+durations[fx.id]+.12
        starts[e.id]=e.start if e.start is not None else cursor
        end=starts[e.id]+durations.get(e.id,0)
        cursor=max(cursor,end+(.2 if e.id in durations else 0))
        after=[fx for fx in active if fx.kind=='sfx' and fx.anchor_id==e.id and fx.placement=='after' and fx.start is None]
        for fx in after:
            starts[fx.id]=cursor+fx.offset; cursor=starts[fx.id]+durations[fx.id]+.12
    for e in active:
        if e.start is not None: starts[e.id]=e.start
        elif e.id not in starts:
            anchor=starts.get(e.anchor_id,0)
            if e.placement=='absolute': starts[e.id]=e.offset
            elif e.placement=='within': starts[e.id]=anchor+e.offset
            else: starts[e.id]=anchor+durations.get(e.anchor_id,0)+e.offset
    items=[dict(id=e.id,kind=e.kind,path=str(paths[e.id]),start=starts[e.id],duration=durations[e.id],gain_db=e.gain_db,
        points=[x.model_dump() for x in e.points],narrator=e.character_id=='narrator' and e.kind=='speech') for e in active]
    audio.enforce_polyphony(items)
    return items,hits

def generate(p,allow_paid,progress):
    start=time.perf_counter()
    path=store.DATA/'hrtf'/f'{p.render.profile}.sofa'
    if not path.exists(): raise ValueError('HRTF数据尚未安装，请运行素材安装脚本')
    items,hits=build_timeline(p,allow_paid,progress)
    progress('空间卷积与混音',.72)
    mix,metrics=audio.render(items,audio.get_hrir(str(path)),p.render.room)
    rid=store.uid(); target=store.path_for('renders',rid,'wav')
    tmp=target.with_suffix('.part.wav'); sf.write(tmp,mix,audio.SR,subtype='PCM_24'); tmp.replace(target)
    metrics.update(cache_hits=hits,total_seconds=time.perf_counter()-start,profile=p.render.profile,project_revision=p.revision)
    timeline=[{**i,'path':str(Path(i['path']).relative_to(store.DATA)).replace('\\','/')} for i in items]
    used_assets={e.asset_id for e in p.events if e.enabled and e.asset_id}
    asset_names={a['id']:a.get('name',a['id']) for a in assets() if a['id'] in used_assets}
    manifest=dict(id=rid,project=p.model_dump(),timeline=timeline,metrics=metrics,created_at=time.time(),asset_names=asset_names)
    store.write(target.with_suffix('.json'),manifest)
    with zipfile.ZipFile(target.with_suffix('.zip'),'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('project.json',json.dumps(p.model_dump(),ensure_ascii=False,indent=2))
        z.writestr('render.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        z.write(target,'mix.wav')
        for item in items: z.write(item['path'],f'stems/{item["id"]}.wav')
    return dict(id=rid,created_at=time.time(),revision=p.revision,metrics=metrics),timeline
