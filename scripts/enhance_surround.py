"""Create and verify a local-only surround variant; preserve the source project."""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import soundfile as sf
from studio import audio, engine, store
from studio.models import Point, Project


def main():
    source_path = store.path_for('projects', 'demo_suspense')
    original = source_path.read_bytes()
    source = Project.model_validate_json(original)
    estimate = engine.estimate(source)
    if estimate['uncached_utterances']:
        raise RuntimeError(f"缺少 {estimate['uncached_utterances']} 条配音缓存，未调用付费 API。")
    ledger_before = store.digest(store.ledger())
    baseline, _ = engine.build_timeline(source, False, lambda *args: None)
    p = source.model_copy(deep=True)
    p.id = 'surround_' + store.uid()[:16]
    p.title = '十一点十七分 · 夸张环绕增强版'
    p.revision = 1
    p.outputs = []
    p.metrics = {}
    events = {e.id: e for e in p.events}
    routes = {
        'fx0': [(-4,1,3),(4,1,3)],
        'fx1': [(-6,0,-4),(0,0,-3),(6,0,-4)],
        'fx2': [(-2,4,0)],
        'fx3': [(-3,0,-6),(2,0,-3),(.8,0,-.6)],
        'fx4': [(3,0,2),(2,0,0)],
        'fx5': [(0,1,4),(-2,0,0),(0,1,-4)],
        'fx6': [(2,4,-1)],
        'fx7': [(-2,0,0)],
        'fx5ddc17bc218247acad945e4609966f54': [(-.8,0,-.6)],
        'fx22cd67e573c74d97a86a611d83204b42': [(2,0,0)],
        'fx482752c8357747f4898c00a1e5d8b322': [(0,0,-1.2)],
    }
    for eid, route in routes.items():
        e = events[eid]
        e.points = [Point(t=i * e.duration / (len(route)-1) if len(route)>1 else 0,
                          x=x,y=y,z=z) for i,(x,y,z) in enumerate(route)]
    events['fx0'].gain_db = 0
    events['fx1'].gain_db = -12
    assert events['fx3'].duration == 6
    step_path = engine.asset_path(events['fx3'].asset_id)
    step = audio.fade(audio.load_audio(step_path), samples=240)
    assert 0 < len(step) < int(.6 * audio.SR)
    sequence = np.zeros(6 * audio.SR, dtype=np.float32)
    for i in range(10):
        start = round(i * .6 * audio.SR)
        sequence[start:start+len(step)] = step
    aid = 'surround_steps_' + store.uid()[:16]
    target = store.path_for('assets', aid, 'wav')
    sf.write(target, sequence, audio.SR, subtype='PCM_24')
    records = store.read(store.DATA/'assets'/'uploads.json', [])
    records.append(dict(id=aid,name='环绕展示 · 连续水泥脚步（6秒10步）',kind='sfx',
        duration=6,filename=target.name,source='Derived from Kenney Impact Sounds: https://kenney.nl/assets/impact-sounds; 10 steps at 0.6s intervals, 5ms fades',
        license='CC0-1.0',synthetic=False))
    store.write(store.DATA/'assets'/'uploads.json', records)
    events['fx3'].asset_id = aid
    p.notes.append(f'夸张环绕副本，来源 {source.id} 版本 {source.revision}；扩大音效方向与运动，连续脚步为6秒10步；配音及时间编排不变。')
    p = Project.model_validate(p.model_dump())
    store.save_project(p)
    p = store.project(p.id)
    current, _ = engine.build_timeline(p, False, lambda *args: None)
    assert [(i['id'],i['start'],i['duration']) for i in baseline] == [(i['id'],i['start'],i['duration']) for i in current]
    assert [e.model_dump() for e in source.events if e.kind=='speech'] == [e.model_dump() for e in p.events if e.kind=='speech']
    assert p.render == source.render
    for eid, route in routes.items():
        pts = np.array(route, dtype=float)
        for a,b in zip(pts,pts[1:]):
            d=b-a
            u=np.clip(-np.dot(a,d)/np.dot(d,d),0,1)
            assert np.linalg.norm(a+u*d) >= .5
    reread, sr = sf.read(target, dtype='float32')
    assert sr == 48000 and len(reread) == 288000
    assert all(np.max(np.abs(reread[round(i*.6*sr):round(i*.6*sr)+len(step)]))>0 for i in range(10))
    print('Validated project, ten footsteps, unchanged speech/timing; rendering offline.', flush=True)
    output, _ = engine.generate(p, False, lambda m,v: print(m, flush=True) if v>=.7 else None)
    p.outputs.append(output)
    p.metrics = output['metrics']
    store.save_project(p)
    mix_path = store.path_for('renders', output['id'], 'wav')
    rendered, sr = sf.read(mix_path, dtype='float32', always_2d=True)
    assert sr == 48000 and rendered.shape[1] == 2
    assert np.isfinite(rendered).all() and np.max(np.abs(rendered)) <= .940001
    assert np.max(np.abs(rendered[:,0]-rendered[:,1])) > 0
    print('Verifying repeat rendering after reopening project.', flush=True)
    items, _ = engine.build_timeline(store.project(p.id), False, lambda *args: None)
    repeat, _ = audio.render(items, audio.get_hrir(str(store.DATA/'hrtf'/f'{p.render.profile}.sofa')), p.render.room)
    assert repeat.shape == rendered.shape and np.max(np.abs(repeat-rendered)) < 2e-7
    assert source_path.read_bytes() == original
    assert store.digest(store.ledger()) == ledger_before
    report = dict(project_id=p.id, render_id=output['id'], source_sha256=hashlib.sha256(original).hexdigest(),
        checks=['source preserved','speech and timeline unchanged','10 audible footsteps','trajectories avoid origin',
                'project reopened','48kHz stereo finite unclipped','deterministic repeat render','billing ledger unchanged'],
        metrics=p.metrics)
    store.write(store.path_for('renders',output['id']+'_verification'),report)
    print('RESULT',p.id,str(mix_path),flush=True)


if __name__ == '__main__':
    main()
