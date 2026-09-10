"""Create a free, explicitly labelled Windows system-voice example; never calls an API."""
import sys,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import store,providers,engine,sample
from studio.models import Project,Character,Event,Point
import soundfile as sf

def main():
    store.init()
    p=Project(id='demo_suspense',title='十一点十七分 · 免费系统配音示例',source=sample.TEXT,
        characters=[Character(id='narrator',name='旁白'),Character(id='lin',name='林舟',voice=providers.VOICES[1][0]),Character(id='xu',name='许宁',voice=providers.VOICES[2][0])])
    # Authored demo casting, not a claim of offline AI scene understanding.
    speakers=iter(['xu','lin','xu','xu','xu','xu'])
    for span in providers.split_source(p.source):
        text=span['text'];speaker=next(speakers,'xu') if text.startswith('“') else 'narrator'
        x=-1.4 if speaker=='lin' else 1.4 if speaker=='xu' else 0
        p.events.append(Event(id='s'+str(span['index']),character_id=speaker,text=text,original=text,
            source_start=span['start'],source_end=span['end'],asset_id='demo_s'+str(span['index']),points=[Point(x=x,z=2)],gain_db=-1))
    def anchor(term):return next(e.id for e in p.events if term in e.text)
    p.events.extend([
        Event(id='rain',kind='ambience',asset_id='rain',start=0,duration=180,gain_db=-27,points=[Point(x=0,z=5)]),
        Event(id='upstairs',kind='sfx',asset_id='kenney_impactWood_heavy_000',anchor_id=anchor('楼上传来一下'),placement='after',gain_db=-9,points=[Point(y=2,z=.4)]),
        Event(id='steps',kind='sfx',asset_id='footstep',anchor_id=anchor('身后的走廊里'),placement='within',offset=2,duration=3,gain_db=-9,points=[Point(z=-5),Point(t=3,z=-1.2)]),
        Event(id='knock',kind='sfx',asset_id='knock',anchor_id=anchor('轻轻敲了三下'),placement='after',gain_db=-12,points=[Point(z=2)]),
    ])
    p.notes=['示例配音来自 Windows 系统语音（缺少可用角色音色时回退为同一旁白音色），仅用于免费验证流程，不代表 MiniMax 情感配音质量。角色和音效由示例脚本预先编排。']
    store.save_project(p)
    command=Path(__file__).with_name('speak_demo.ps1')
    subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(command),'-DataDirectory',str(store.DATA)],check=True)
    records=[]
    for e in p.events:
        if e.kind!='speech':continue
        path=store.path_for('assets',e.asset_id,'wav')
        info=sf.info(path)
        records.append(dict(id=e.asset_id,name='系统配音示例 · '+e.id,kind='speech',duration=info.duration,filename=path.name,source='Windows System.Speech；本项目原创文本',license='仅作本机演示，系统音色使用遵循设备许可',synthetic=True))
    store.write(store.DATA/'assets'/'demo.json',records)
    timeline,_=engine.build_timeline(p,False,lambda *args:None)
    end=max(i['start']+i['duration'] for i in timeline if i['kind']!='ambience')
    next(e for e in p.events if e.id=='rain').duration=min(180,end+.5)
    output,_=engine.generate(p,False,lambda m,v:print(m,flush=True))
    p.outputs.append(output);p.metrics=output['metrics'];store.save_project(p)
    print('DEMO_READY',output['id'],flush=True)
if __name__=='__main__':main()
