"""Deterministic, provider-independent binaural baseline. Coordinates: right/up/front."""
import math, time
from functools import lru_cache
from pathlib import Path
import numpy as np
import soundfile as sf
import h5py
from scipy.signal import resample_poly, fftconvolve
from scipy.spatial import cKDTree

SR=48000
VERSION='hrir-ola-1.1'
DECODER_VERSION='bounded-stream-1'

class SequentialAudioFile(sf.SoundFile):
    def seekable(self):
        # libsndfile may report INT64_MAX frames for streaming FLAC. SoundFile's
        # automatic post-read seek also fails at EOF for these streams.
        return False

def decode_audio(source,max_seconds=180):
    chunks=[];total=0
    with SequentialAudioFile(source) as stream:
        sr=stream.samplerate
        if not 8000<=sr<=192000 or not 1<=stream.channels<=2:
            raise ValueError('音频采样率或声道数不受支持')
        limit=int(sr*max_seconds)
        while True:
            block=stream.read(frames=min(65536,limit-total+1),dtype='float32',always_2d=True)
            if not len(block):break
            total+=len(block)
            if total>limit:raise ValueError(f'音频实际时长超过{max_seconds}秒限制')
            if not np.isfinite(block).all():raise ValueError('音频含无效数值')
            chunks.append(block)
    if not chunks:raise ValueError('音频为空')
    return np.concatenate(chunks),sr

def load_audio(path):
    data,sr=decode_audio(path)
    mono=data.mean(axis=1)
    if sr!=SR:
        g=math.gcd(sr,SR); mono=resample_poly(mono,SR//g,sr//g).astype('float32')
    return mono

def fade(a, samples=480):
    a=a.copy(); n=min(samples,len(a)//2)
    if n:
        shape=(n,)+(1,)*(a.ndim-1)
        a[:n]*=np.linspace(0,1,n).reshape(shape)
        a[-n:]*=np.linspace(1,0,n).reshape(shape)
    return a

class HRIR:
    def __init__(self,path):
        with h5py.File(path,'r') as f:
            sr=float(np.array(f['Data.SamplingRate']).ravel()[0])
            ir=np.array(f['Data.IR'],dtype='float32')
            pos=np.array(f['SourcePosition'])
            typ=f['SourcePosition'].attrs.get('Type',b'spherical')
            if isinstance(typ,bytes): typ=typ.decode()
            delay=np.array(f['Data.Delay']) if 'Data.Delay' in f else np.zeros((1,2))
        if ir.ndim!=3 or ir.shape[1]!=2: raise ValueError('仅支持双耳 SimpleFreeFieldHRIR 数据')
        if np.any(delay!=0): raise ValueError('此基线要求SOFA的延迟已包含在IR中')
        if str(typ).lower()!='spherical': raise ValueError('需要球坐标SOFA数据')
        az,el=np.deg2rad(pos[:,0]),np.deg2rad(pos[:,1])
        # SOFA: +X front, +Y left, +Z up; project: +X right, +Y up, +Z front.
        self.directions=np.column_stack((-np.sin(az)*np.cos(el),np.sin(el),np.cos(az)*np.cos(el)))
        if sr!=SR:
            g=math.gcd(int(sr),SR); ir=resample_poly(ir,SR//g,int(sr)//g,axis=-1)
        self.ir=ir.astype('float32')
        self.tree=cKDTree(self.directions)
        self.taps=self.ir.shape[-1]

    def at(self,position):
        p=np.asarray(position,dtype=float); norm=np.linalg.norm(p)
        if norm<.15: p=np.array([0,0,.15]); norm=.15
        ds,ids=self.tree.query(p/norm,k=3)
        if ds[0]<1e-7: return self.ir[ids[0]]
        w=1/np.maximum(ds,1e-5)**2; w/=w.sum()
        return np.sum(self.ir[ids]*w[:,None,None],axis=0).astype('float32')

@lru_cache(maxsize=3)
def get_hrir(path):
    return HRIR(path)

def position_at(points,t):
    ts=[p['t'] for p in points]
    return np.array([np.interp(t,ts,[p[k] for p in points]) for k in ['x','y','z']])

def spatialize(mono,points,hrir,room=0):
    """Windowed overlap-add time-varying FIR; weights partition the input signal."""
    mono=fade(np.asarray(mono,dtype='float32'))
    n=len(mono); hop=512; size=2*hop
    out=np.zeros((n+hrir.taps+1,2),dtype='float32')
    window=np.hanning(size+1)[:-1].astype('float32')
    static=all(all(p[k]==points[0][k] for k in ('x','y','z')) for p in points)
    if static:
        pos=position_at(points,0);ir=hrir.at(pos)
        attenuation=1/max(.5,float(np.linalg.norm(pos)))
        for ear in range(2):
            conv=fftconvolve(mono*attenuation,ir[ear]);out[:len(conv),ear]=conv
    for start in (() if static else range(-hop,n,hop)):
        a=max(0,start); b=min(n,start+size)
        if b<=a: continue
        center=max(0,min(n-1,start+hop))
        pos=position_at(points,center/SR)
        attenuation=1/max(.5,float(np.linalg.norm(pos)))
        ir=hrir.at(pos)
        chunk=mono[a:b]*window[a-start:b-start]*attenuation
        for ear in range(2):
            conv=fftconvolve(chunk,ir[ear])
            out[a:a+len(conv),ear]+=conv
    if room>0:
        # Explicit lightweight room approximation, not a measured room simulation.
        dry=out; out=np.pad(dry,((0,int(.32*SR)),(0,0)))
        for i,delay in enumerate([.017,.031,.047,.073,.113,.173,.251]):
            d=int(delay*SR)
            out[d:d+len(dry)]+=dry[:,::-1] * (room*.45*(.68**i))
    return out

def enforce_polyphony(items):
    boundaries=[]
    for item in items:
        if item['kind'] in ('speech','sfx') and not item.get('narrator'):
            boundaries.extend([(item['start'],1),(item['start']+item['duration'],-1)])
    count=0
    for _,change in sorted(boundaries,key=lambda x:(x[0],x[1])):
        count+=change
        if count>8: raise ValueError('同时活动的点声源超过8个，请调整开始时间或禁用部分事件')

def render(items,hrir,room=0.18):
    began=time.perf_counter()
    if not items: raise ValueError('没有可渲染的声音事件')
    enforce_polyphony(items)
    duration=max(i['start']+i['duration'] for i in items)
    if duration>1200: raise ValueError('首版限制成品为20分钟以内')
    mix=np.zeros((int((duration+.5)*SR)+hrir.taps+4,2),dtype='float32')
    speech=[(i['start'],i['start']+i['duration']) for i in items if i['kind']=='speech']
    for item in items:
        mono=load_audio(item['path']); count=max(1,round(item['duration']*SR))
        if item['kind'] in ('music','ambience') and len(mono)<count:
            # Overlap-crossfaded loops, avoiding hard cuts at the wrap boundary.
            overlap=min(2400,len(mono)//4)
            if overlap==0:
                mono=np.tile(mono,math.ceil(count/len(mono)))[:count]
            else:
                loop=np.zeros(count,dtype='float32');loop[:len(mono)]=mono
                step=len(mono)-overlap
                ramp=np.linspace(0,1,overlap,dtype='float32')
                for start in range(step,count,step):
                    take=min(len(mono),count-start);blend=min(overlap,take)
                    loop[start:start+blend]=loop[start:start+blend]*(1-ramp[:blend])+mono[:blend]*ramp[:blend]
                    loop[start+blend:start+take]=mono[blend:take]
                mono=loop
        mono=np.pad(mono[:count],(0,max(0,count-len(mono))))
        if item['kind'] in ('music','ambience'):
            times=item['start']+np.arange(len(mono))/SR
            envelope=np.ones(len(mono),dtype='float32')
            for a,b in speech:
                # Smooth 80ms ramps preserve background continuity.
                activity=np.clip((times-(a-.08))/.08,0,1)*np.clip(((b+.08)-times)/.08,0,1)
                envelope=np.minimum(envelope,1-activity*(.72 if item['kind']=='music' else .4))
            mono*=envelope
        mono*=10**(item['gain_db']/20)
        if item.get('narrator'):
            out=np.repeat(fade(mono)[:,None],2,axis=1)*.7
        else:
            out=spatialize(mono,item['points'],hrir,room)
        start=round(item['start']*SR)
        mix[start:start+len(out)]+=out
    if not np.isfinite(mix).all(): raise ValueError('渲染出现非有限值')
    peak=float(np.max(np.abs(mix))); scale=min(1,.94/max(peak,1e-9))
    mix=fade(mix*scale)
    seconds=time.perf_counter()-began
    return mix,dict(renderer=VERSION,sample_rate=SR,duration=len(mix)/SR,render_seconds=seconds,
        real_time_factor=seconds/(len(mix)/SR),peak_before=peak,peak_after=float(abs(mix).max()),
        gain_reduction_db=20*math.log10(scale),events=len(items))
