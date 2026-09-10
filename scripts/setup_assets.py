"""Download three measured SOFA profiles and create explicitly synthetic free demo effects."""
import sys, json, hashlib, urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import soundfile as sf
from scipy.signal import butter,sosfilt
from studio import store
from studio.audio import SR,fade,HRIR

def setup():
    store.init()
    license_path=store.DATA/'hrtf'/'LICENSE-APACHE-2.0.txt'
    if not license_path.exists():
        license_path.write_bytes(urllib.request.urlopen('https://www.apache.org/licenses/LICENSE-2.0.txt',timeout=30).read())
    for profile in ['H3','H4','H5']:
        path=store.DATA/'hrtf'/f'{profile}.sofa'
        url=f'https://sofacoustics.org/data/database/sadie/{profile}_48K_24bit_256tap_FIR_SOFA.sofa'
        if not path.exists():
            print('Downloading',profile,flush=True)
            tmp=path.with_suffix('.download')
            with urllib.request.urlopen(url,timeout=90) as response, tmp.open('wb') as f:
                while chunk:=response.read(1024*1024): f.write(chunk)
            HRIR(tmp); tmp.replace(path)
        print(profile,path.stat().st_size,flush=True)
        store.write(path.with_suffix('.json'),dict(profile=profile,url=url,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            source='SADIE II — University of York / AudioLab',license='Apache-2.0',citation='Armstrong et al., Applied Sciences 2018, 8(11), 2029. DOI:10.3390/app8112029'))
    rng=np.random.default_rng(20260908)
    catalog=[]
    def save(key,name,a,kind='sfx'):
        a=fade(a); a=.45*a/max(.001,float(np.max(np.abs(a))))
        sf.write(store.DATA/'assets'/f'{key}.wav',a,SR,subtype='PCM_16')
        catalog.append(dict(id=key,name=name,kind=kind,duration=len(a)/SR,filename=f'{key}.wav',
            source='本项目 scripts/setup_assets.py 程序合成；非实地录音',license='CC0-1.0',synthetic=True))
    def noise(seconds,hz):
        return sosfilt(butter(2,hz,fs=SR,output='sos'),rng.normal(size=int(SR*seconds)))
    t=np.arange(SR*3)/SR
    for key,name,hz in [('footstep','脚步（合成）',700),('knock','敲门（合成）',1700),('upstairs','楼上撞击（合成）',350),('heartbeat','心跳（合成）',130)]:
        a=np.zeros(len(t)); burst=noise(.16,hz)*np.exp(-np.arange(int(.16*SR))/SR*32)
        for start in [.2,.85,1.5,2.15]:
            i=int(start*SR); a[i:i+len(burst)]+=burst
        save(key,name,a)
    save('door_close','关门（合成）',noise(1.2,1500)*np.exp(-np.arange(int(1.2*SR))/SR*12))
    ts=np.arange(SR*2)/SR
    save('door_creak','门轴（合成）',np.sin(2*np.pi*(180*ts+20*np.sin(ts*9)))*np.sin(np.pi*ts/2)**2)
    save('rain','雨声（合成）',noise(8,9000),'ambience')
    ts=np.arange(SR*8)/SR
    save('wind','风声（合成）',noise(8,700)*(.5+.4*np.sin(ts*1.7)),'ambience')
    save('engine','远处引擎（合成）',np.sin(2*np.pi*65*ts)*.25+noise(8,400),'ambience')
    ts=np.arange(SR*2)/SR
    save('bell','铃声（合成）',sum(np.sin(2*np.pi*f*ts)/n for n,f in enumerate([880,1760,2464],1))*np.exp(-ts*3))
    save('rustle','衣物摩擦（合成）',noise(2,5000)*(np.sin(ts*10)**8))
    save('thunder','低沉雷声（合成）',noise(5,220)*np.sin(np.linspace(0,np.pi,SR*5)))
    for key,name,freqs in [('suspense','悬疑氛围（合成）',[55,58.27,82.41]),('calm','平静氛围（合成）',[130.81,164.81,196])]:
        ts=np.arange(SR*10)/SR
        save(key,name,sum(np.sin(2*np.pi*f*ts) for f in freqs)*(.7+.2*np.sin(ts*.7)),'music')
    store.write(store.DATA/'assets'/'builtin.json',catalog)
    print('Ready:',len(catalog),'synthetic CC0 assets',flush=True)

if __name__=='__main__': setup()
