"""Import a small CC0 Foley library from Kenney's official distribution."""
import io,sys,zipfile,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import soundfile as sf
from studio import store
from studio.audio import load_audio,SR

URL='https://kenney.nl/media/pages/assets/impact-sounds/87b4ddecda-1677589768/kenney_impact-sounds.zip'
FILES={'footstep_carpet_000':'地毯脚步','footstep_concrete_000':'水泥地脚步','footstep_grass_000':'草地脚步','footstep_wood_000':'木地板脚步',
 'impactBell_heavy_000':'金属铃响','impactGlass_light_000':'玻璃轻碰','impactMetal_heavy_000':'重金属撞击','impactWood_heavy_000':'木板重击',
 'impactWood_light_000':'木门轻敲','impactPlank_medium_000':'木板碰撞','impactSoft_medium_000':'软物落地','impactPlate_light_000':'碟子轻碰'}
def setup():
    store.init();archive=store.DATA/'kenney_impact-sounds.zip'
    if not archive.exists():
        archive.write_bytes(urllib.request.urlopen(URL,timeout=60).read())
    catalog=[]
    with zipfile.ZipFile(archive) as z:
        (store.DATA/'assets'/'KENNEY-LICENSE.txt').write_bytes(z.read('License.txt'))
        for stem,name in FILES.items():
            a,sr=sf.read(io.BytesIO(z.read(f'Audio/{stem}.ogg')),dtype='float32')
            aid='kenney_'+stem;path=store.path_for('assets',aid,'wav')
            sf.write(path,a,sr,subtype='PCM_16');a=load_audio(path);sf.write(path,a,SR,subtype='PCM_16')
            catalog.append(dict(id=aid,name=name,kind='sfx',duration=len(a)/SR,filename=path.name,
                source='Kenney — Impact Sounds, https://kenney.nl/assets/impact-sounds',license='CC0-1.0',synthetic=False))
    store.write(store.DATA/'assets'/'recorded.json',catalog)
    print('Imported',len(catalog),'Kenney CC0 effects')
if __name__=='__main__':setup()
