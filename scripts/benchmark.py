"""Portable deterministic baseline; run on desktop now, Raspberry Pi later."""
import sys,json,time,platform,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import soundfile as sf
from studio import store,audio

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=3);parser.add_argument('--out',default='data/benchmark.json');args=parser.parse_args()
    store.init();rng=np.random.default_rng(7)
    probe=store.DATA/'cache'/'benchmark_probe.wav';sf.write(probe,rng.normal(0,.03,audio.SR*args.seconds),audio.SR)
    results=[]
    for profile in ['H3','H4','H5']:
        h=audio.get_hrir(str(store.DATA/'hrtf'/f'{profile}.sofa'))
        for count in [1,4,8]:
            items=[dict(id=str(i),kind='sfx',path=str(probe),start=0,duration=args.seconds,gain_db=-12,
                points=[dict(t=0,x=-2+i*.5,y=0,z=2),dict(t=args.seconds,x=2-i*.5,y=1,z=2)]) for i in range(count)]
            cpu=time.process_time();out,metrics=audio.render(items,h,.18)
            metrics.update(profile=profile,sources=count,cpu_seconds=time.process_time()-cpu)
            results.append(metrics)
    result=dict(platform=platform.platform(),python=sys.version,renderer=audio.VERSION,seed=7,results=results,
        limitations='Offline render benchmark; does not measure audio-device latency, dropouts, thermal throttling or perceptual quality.')
    store.write(Path(args.out),result);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
