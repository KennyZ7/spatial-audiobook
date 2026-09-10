"""Import the self-contained, credential-free example into a fresh installation."""
import shutil
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import store
from studio.models import Project

def main():
    source=store.ROOT/'examples'/'suspense'
    p=Project.model_validate(store.read(source/'project.json'))
    store.init()
    if store.path_for('projects',p.id).exists():
        raise SystemExit('Example already imported; existing project preserved.')
    records=store.read(source/'assets.json')
    for item in records:
        name=item['filename']
        if Path(name).name!=name: raise ValueError('Invalid example asset filename')
        target=store.DATA/'assets'/name
        if target.exists() and target.read_bytes()!=(source/'assets'/name).read_bytes():
            raise ValueError('Existing asset differs; import stopped: '+name)
    for item in records:
        shutil.copyfile(source/'assets'/item['filename'],store.DATA/'assets'/item['filename'])
    old=store.read(store.DATA/'assets'/'uploads.json',[])
    ids={a['id'] for a in records}
    store.write(store.DATA/'assets'/'uploads.json',[a for a in old if a['id'] not in ids]+records)
    store.save_project(p)
    print('Imported example:',p.id,'(no model calls)')
if __name__=='__main__': main()
