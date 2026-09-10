import io,json,time
import numpy as np
import pytest
import soundfile as sf
import zipfile
import httpx
from fastapi.testclient import TestClient
from studio import store,providers,engine,audio
from studio.models import Project,Character,Event,Point,Settings
from studio.app import app

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False);monkeypatch.delenv('MINIMAX_API_KEY',raising=False)
    store.init()
    return tmp_path

def configured():
    store.write(store.DATA/'settings.json',Settings(deepseek_key='fake',minimax_key='fake',rates_confirmed=True).model_dump())

def project(text='“别动。”门后响起脚步。'):
    return Project(source=text,characters=[Character(id='narrator',name='旁白')],events=[Event(id='s0',character_id='narrator',text=text,original=text)])

def wav_bytes():
    b=io.BytesIO();sf.write(b,np.sin(np.arange(3200)*.1)*.2,32000,format='FLAC');return b.getvalue()

def unknown_length_flac():
    raw=bytearray(wav_bytes())
    raw[18:26]=(int.from_bytes(raw[18:26],'big') & ~((1<<36)-1)).to_bytes(8,'big')
    return bytes(raw)

def test_streaming_flac_decodes_without_unbounded_allocation():
    raw=unknown_length_flac()
    assert sf.info(io.BytesIO(raw)).frames>10**12
    decoded,sr=audio.decode_audio(io.BytesIO(raw))
    expected,_=sf.read(io.BytesIO(wav_bytes()),always_2d=True,dtype='float32')
    assert sr==32000 and len(decoded)==3200
    np.testing.assert_array_equal(decoded,expected)
    with pytest.raises(ValueError,match='时长超过'):audio.decode_audio(io.BytesIO(raw),max_seconds=.05)

def test_raw_tts_cache_survives_decode_failure_without_rebilling(isolated,monkeypatch):
    configured();e=project().events[0];calls=[]
    def response(*args):
        calls.append(1)
        return dict(base_resp={'status_code':0},data={'audio':unknown_length_flac().hex()},extra_info={'usage_characters':8})
    monkeypatch.setattr(providers,'post_json',response)
    actual=providers.decode_audio
    monkeypatch.setattr(providers,'decode_audio',lambda *a:(_ for _ in ()).throw(ValueError('模拟解码失败')))
    with pytest.raises(ValueError,match='模拟解码失败'):providers.synthesize(e,'voice')
    assert len(store.ledger())==1 and store.ledger()[0]['status']=='complete'
    monkeypatch.setattr(providers,'decode_audio',actual)
    path,hit=providers.synthesize(e,'voice',False)
    assert hit and len(calls)==1 and sf.info(path).samplerate==48000
    assert len(store.ledger())==1

def test_lossless_segmentation_500_2000():
    for n in [500,2000]:
        text=('“你听见了吗？”他问。\n她没有回答。「楼上有人！」\n'*100)[:n]
        spans=providers.split_source(text)
        assert ''.join(s['text'] for s in spans)==text
        assert all(text[s['start']:s['end']]==s['text'] for s in spans)
    assert max(len(s['text']) for s in providers.split_source('雨'*2000))<=180

@pytest.mark.parametrize('n',[500,2000])
@pytest.mark.parametrize('mode',['faithful','drama'])
def test_end_to_end_script_speech_render_export_and_free_retry(isolated,monkeypatch,n,mode):
    from studio import sample
    configured();p=Project(source=(sample.TEXT*5)[:n],mode=mode)
    calls=[]
    def response(url,key,body):
        calls.append(url)
        if 'deepseek' in url:
            spans=providers.split_source(p.source)
            result={'segments':[dict(index=s['index'],speaker='旁白',adapted=s['text'],emotion='neutral',position=[0,0,2]) for s in spans],'effects':[]}
            return {'choices':[{'message':{'content':json.dumps(result)}}],'usage':{'prompt_tokens':100,'completion_tokens':100}}
        return dict(base_resp={'status_code':0},data={'audio':wav_bytes().hex()},extra_info={'usage_characters':8})
    monkeypatch.setattr(providers,'post_json',response)
    # Exercise full render/export with a minimal measured-profile substitute; real SOFA is checked below.
    (isolated/'hrtf'/'H3.sofa').touch()
    monkeypatch.setattr(audio,'get_hrir',lambda p:IdentityHRIR())
    providers.make_script(p,[],True)
    output,timeline=engine.generate(p,True,lambda *a:None)
    audio_path=store.path_for('renders',output['id'],'wav')
    a,sr=sf.read(audio_path)
    assert a.shape[1]==2 and sr==48000 and np.isfinite(a).all() and np.max(abs(a))<=.941
    with zipfile.ZipFile(audio_path.with_suffix('.zip')) as z:
        assert 'mix.wav' in z.namelist() and 'project.json' in z.namelist()
        assert sum(x.startswith('stems/') for x in z.namelist())==len(timeline)
    count=len(calls);p.events[0].gain_db=-9
    engine.generate(p,False,lambda *a:None)
    assert len(calls)==count

def test_real_profiles_channel_orientation_and_distance():
    for profile in ['H3','H4','H5']:
        path=store.ROOT/'data'/'hrtf'/f'{profile}.sofa'
        if not path.exists():pytest.skip('SOFA data not installed')
        h=audio.HRIR(path)
        left=h.at([-2,0,0]);right=h.at([2,0,0])
        assert np.sum(left[0]**2)>np.sum(left[1]**2)*2
        assert np.sum(right[1]**2)>np.sum(right[0]**2)*2
        probe=np.random.default_rng(0).normal(0,.03,4800)
        near=audio.spatialize(probe,[dict(t=0,x=0,y=0,z=1)],h,0)
        far=audio.spatialize(probe,[dict(t=0,x=0,y=0,z=6)],h,0)
        assert np.sqrt(np.mean(near**2))==pytest.approx(np.sqrt(np.mean(far**2))*6,rel=.001)
        assert not np.allclose(h.at([0,2,.2]),h.at([0,-2,.2]))

def test_faithful_ignores_llm_rewrite_and_drama_keeps_original(isolated,monkeypatch):
    configured();p=project()
    def response(*args):
        spans=providers.split_source(p.source)
        return {'choices':[{'message':{'content':json.dumps({'segments':[dict(index=s['index'],speaker='旁白',adapted='改写',emotion='calm',position=[0,0,2]) for s in spans],'effects':[]})}}],'usage':{'prompt_tokens':10,'completion_tokens':10}}
    monkeypatch.setattr(providers,'post_json',response)
    providers.make_script(p,[],True)
    assert ''.join(e.text for e in p.events)==p.source
    p.mode='drama';providers.make_script(p,[],True)
    assert ''.join(e.original for e in p.events)==p.source
    assert all(e.text=='改写' for e in p.events)

def test_invalid_script_not_cached(isolated,monkeypatch):
    configured();monkeypatch.setattr(providers,'post_json',lambda *args:{'choices':[{'message':{'content':'{"segments":[],"effects":[]}'}}]})
    with pytest.raises(ValueError,match='遗漏'):providers.make_script(project(),[],True)
    assert not list((isolated/'cache').glob('*.json'))

@pytest.mark.parametrize('raw,expected',[
    ('during','within'),(' DURING ','within'),('\tWithin\n','within'),
    ('before','before'),('after','after'),('within','within'),('absolute','absolute'),
    (' BEFORE ','before'),('After','after'),(' ABSOLUTE ','absolute'),
])
def test_normalize_placement(raw,expected):
    assert providers.normalize_placement(raw,'脚步')==expected

@pytest.mark.parametrize('raw',['unknown','',None,42,[]])
def test_unknown_placement_reports_effect(raw):
    with pytest.raises(ValueError) as err:providers.normalize_placement(raw,'第2条：脚步（steps）')
    assert '第2条：脚步（steps）' in str(err.value)
    assert repr(raw) in str(err.value)
    assert '播放位置无效' in str(err.value)

def test_placement_normalization_cache_timing_and_rejected_script(isolated,monkeypatch):
    configured();p=project('门后响起脚步。');p.outputs=[{'id':'previous'}]
    store.save_project(p);original=store.path_for('projects',p.id).read_bytes()
    sf.write(isolated/'assets'/'steps.wav',np.ones(4800)*.01,48000)
    assets=[dict(id='steps',name='脚步',kind='sfx',filename='steps.wav')]
    store.write(isolated/'assets'/'builtin.json',assets)
    result=dict(segments=[dict(index=0,speaker='旁白',adapted=p.source)],
        effects=[dict(asset_id='steps',anchor_index=0,placement=' DURING ',offset=.04,duration=.1)])
    calls=[]
    def response(*args):
        calls.append(1)
        return {'choices':[{'message':{'content':json.dumps(result)}}],'usage':{'prompt_tokens':10,'completion_tokens':10}}
    monkeypatch.setattr(providers,'post_json',response)
    providers.make_script(p,assets,True)
    assert p.events[-1].placement=='within'
    cache=next((isolated/'cache').glob('*.json'))
    assert store.read(cache)['effects'][0]['placement']=='within'
    p.events[0].asset_id='steps'
    timeline,_=engine.build_timeline(p,False,lambda *a:None)
    byid={e['id']:e for e in timeline}
    assert byid['fx0']['start']==pytest.approx(byid['s0']['start']+.04)
    # Cached aliases are repaired locally without a new provider request.
    cached=store.read(cache);cached['effects'][0]['placement']='During';store.write(cache,cached)
    providers.make_script(p,assets,True)
    assert len(calls)==1 and store.read(cache)['effects'][0]['placement']=='within'
    snapshot=p.model_dump()
    cached['effects'][0]['placement']='somewhere';store.write(cache,cached)
    with pytest.raises(ValueError,match='脚步'):providers.make_script(p,assets,True)
    assert p.model_dump()==snapshot and store.read(cache)['effects'][0]['placement']=='somewhere'
    assert store.path_for('projects',p.id).read_bytes()==original
    # A fresh invalid response is not cached either.
    p.source='另一个场景。';result['effects'][0]['placement']='somewhere'
    with pytest.raises(ValueError,match='somewhere'):providers.make_script(p,assets,True)
    assert len(list((isolated/'cache').glob('*.json')))==1

def test_synthesis_cache_spatial_edits_free(isolated,monkeypatch):
    configured();calls=[]
    def response(url,key,body):
        calls.append(body)
        assert body['audio_setting']['sample_rate']==32000
        assert 'emotion' not in body['voice_setting']
        return dict(base_resp={'status_code':0},data={'audio':wav_bytes().hex()},extra_info={'usage_characters':8})
    monkeypatch.setattr(providers,'post_json',response)
    e=project().events[0];path,hit=providers.synthesize(e,'voice')
    assert not hit and sf.info(path).samplerate==48000
    e.points=[Point(x=3)];e.gain_db=-10
    _,hit=providers.synthesize(e,'voice',False)
    assert hit and len(calls)==1
    e.text+='新句'
    with pytest.raises(ValueError,match='缓存'):providers.synthesize(e,'voice',False)
    assert len(calls)==1

def test_billing_chinese_and_budget_failure_reservation(isolated,monkeypatch):
    configured();assert providers.billable('你好!A')==6
    s=store.settings();s.budget=.01;store.write(isolated/'settings.json',s.model_dump())
    store.reserve('test',.009,{})
    with pytest.raises(ValueError,match='预算'):store.reserve('test',.002,{})
    monkeypatch.setattr(providers,'post_json',lambda *a:(_ for _ in ()).throw(ValueError('网络失败')))
    e=Event(character_id='narrator',text='测试')
    with pytest.raises(ValueError):providers.synthesize(e,'voice')
    assert sum(r['charged_estimate'] for r in store.ledger())>=.009

def test_invalid_key_and_timeout_are_sanitized(monkeypatch):
    monkeypatch.setattr(httpx,'post',lambda *a,**k:httpx.Response(401,text='sensitive provider echo'))
    with pytest.raises(ValueError,match='API Key无效'):providers.post_json('https://provider.invalid','SECRET',{})
    monkeypatch.setattr(httpx,'post',lambda *a,**k:(_ for _ in ()).throw(httpx.ReadTimeout('SECRET')))
    with pytest.raises(ValueError,match='超时') as err:providers.post_json('https://provider.invalid','SECRET',{})
    assert 'SECRET' not in str(err.value)

def test_timeline_before_after_within_absolute_and_missing_assets(isolated,monkeypatch):
    configured();path=isolated/'assets'/'x.wav';sf.write(path,np.ones(4800)*.01,48000)
    store.write(isolated/'assets'/'builtin.json',[dict(id='x',filename='x.wav')])
    p=project();p.events[0].asset_id='x'
    for idx,placement in enumerate(['before','after','within','absolute']):
        p.events.append(Event(id=f'f{idx}',kind='sfx',asset_id='x',anchor_id='s0',placement=placement,offset=.02,duration=.1))
    items,_=engine.build_timeline(p,False,lambda *a:None);d={i['id']:i for i in items}
    assert d['f0']['start']<d['s0']['start']<d['f1']['start']
    assert d['f2']['start']==pytest.approx(d['s0']['start']+.02)
    assert d['f3']['start']==.02
    p.events[-1].asset_id='missing'
    with pytest.raises(ValueError,match='素材不存在'):engine.build_timeline(p,True,lambda *a:None)

def test_polyphony_and_validation():
    with pytest.raises(ValueError,match='8'):audio.enforce_polyphony([dict(kind='sfx',start=0,duration=1) for _ in range(9)])
    audio.enforce_polyphony([dict(kind='sfx',start=i,duration=1) for i in range(10)])
    with pytest.raises(ValueError):Point(x=float('nan'))
    with pytest.raises(ValueError):Event(points=[Point(t=1)])

class IdentityHRIR:
    taps=1
    def at(self,p):return np.ones((2,1),dtype='float32')

def test_overlap_add_constant_gain_and_no_nan():
    rng=np.random.default_rng(9);a=rng.normal(0,.05,20000).astype('float32')
    out=audio.spatialize(a,[dict(t=0,x=0,y=0,z=1)],IdentityHRIR(),0)
    np.testing.assert_allclose(out[:len(a),0],audio.fade(a),atol=1e-7)
    assert np.isfinite(out).all()
    moving=audio.spatialize(a,[dict(t=0,x=0,y=0,z=1),dict(t=1,x=0,y=0,z=1.000001)],IdentityHRIR(),0)
    np.testing.assert_allclose(moving[:len(a),0],audio.fade(a),atol=1e-7)

def test_api_security_and_project_revision(isolated):
    with TestClient(app) as c:
        p=c.post('/api/projects',json={'source':'雨夜'}).json()
        assert c.get('/api/projects/'+p['id']).status_code==200
        assert c.put('/api/projects/'+p['id'],json=p).status_code==200
        assert c.put('/api/projects/'+p['id'],json=p).status_code==409
        assert c.put('/api/settings',json={'deepseek_key':'SECRET','budget':99}).status_code==422
        assert 'SECRET' not in c.put('/api/settings',json={'deepseek_key':'SECRET','budget':99}).text
        assert c.get('/api/status',headers={'Host':'evil.test'}).status_code==403
        assert c.post('/api/projects',json={},headers={'Origin':'https://evil.test'}).status_code==403
        assert c.get('/api/settings').json().get('deepseek_key') is None
        assert c.get('/api/renders/whatever/not-a-format').status_code==404

def test_failed_job_preserves_outputs_and_restart_recovery(isolated,monkeypatch):
    from studio import app as app_module
    pending=[]; original_submit=app_module.POOL.submit
    def capture(*args,**kwargs):
        f=original_submit(*args,**kwargs);pending.append(f);return f
    monkeypatch.setattr(app_module.POOL,'submit',capture)
    p=project();p.outputs=[{'id':'old'}];store.save_project(p)
    with TestClient(app) as c:
        j=c.post(f'/api/projects/{p.id}/generate',json={'allow_paid':False}).json()
        for f in pending:f.result(timeout=15)
        for _ in range(300):
            job=c.get('/api/jobs/'+j['id']).json()
            if job['status']=='failed':break
            time.sleep(.05)
        assert job['status']=='failed'
        assert c.get('/api/projects/'+p.id).json()['outputs']==[{'id':'old'}]
    store.write(isolated/'jobs'/'interrupted.json',dict(id='interrupted',status='running'))
    with TestClient(app) as c:assert c.get('/api/jobs/interrupted').json()['status']=='failed'
