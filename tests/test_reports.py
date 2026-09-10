import csv
import io
import json
import pytest
from fastapi.testclient import TestClient
from studio import reports, store, engine, providers
from studio.app import app
from studio.models import Project, Character, Event, Point


@pytest.fixture
def manifest():
    p=Project(title='<script>alert(1)</script>',characters=[Character(id='narrator',name='旁白')],
        events=[Event(id='s',character_id='narrator',original='原文，\n"雨"',text='=1+1'),
                Event(id='fx',kind='sfx',asset_id='a',anchor_id='s',placement='within',offset=.5),
                Event(id='off',kind='sfx',enabled=False)])
    items=[dict(id='fx',kind='sfx',start=2.5,duration=1,gain_db=-6,points=[dict(t=0,x=-2,y=1,z=0),dict(t=1,x=2,y=1,z=0)]),
           dict(id='s',kind='speech',start=2,duration=3,gain_db=0,narrator=True,points=[dict(t=0,x=0,y=0,z=2)])]
    return dict(id='test_render',project=p.model_dump(),timeline=items,metrics={'duration':6},asset_names={'a':'旧素材'})


def test_report_rows_and_csv(manifest):
    rows=reports.rows(manifest,[dict(id='a',name='新素材')])
    assert [r['values'][1] for r in rows]==['s','fx']
    assert rows[1]['values'][7]=='原文，\n"雨"'
    assert rows[1]['values'][13]=='旧素材'
    assert rows[1]['points'][1]['absolute_time']==3.5
    assert '不参与空间定位' in rows[0]['values'][15]
    raw=reports.csv_bytes(manifest)
    assert raw.startswith(b'\xef\xbb\xbf')
    parsed=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
    assert parsed[1][8]=="'=1+1" and parsed[2][14]=='-6'
    assert json.loads(parsed[2][-1])[1]['x']==2
    text=reports.html_text(manifest)
    assert '<script>alert(1)</script>' not in text
    assert '&lt;script&gt;' in text and 'file://' not in text
    assert '旧素材' in text


def test_ties_unanchored_and_legacy_names(manifest):
    manifest.pop('asset_names')
    manifest['timeline'][0]['start']=2
    manifest['project']['events'][1]['anchor_id']=''
    rows=reports.rows(manifest)
    assert rows[0]['values'][1]=='s'
    assert rows[1]['values'][7]=='' and rows[1]['values'][13]=='a'


def test_download_is_snapshot_only(tmp_path,monkeypatch,manifest):
    monkeypatch.setattr(store,'DATA',tmp_path);store.init()
    store.write(store.path_for('renders','test_render'),manifest)
    def forbidden(*args,**kwargs): raise AssertionError('must not regenerate or call provider')
    monkeypatch.setattr(engine,'generate',forbidden)
    monkeypatch.setattr(providers,'post_json',forbidden)
    store.write(store.path_for('projects',manifest['project']['id']),{'title':'current project changed'})
    with TestClient(app) as client:
        for kind in ('report','csv'):
            response=client.get('/api/renders/test_render/'+kind)
            assert response.status_code==200
            assert 'attachment;' in response.headers['content-disposition']
            assert 'current project changed' not in response.text
        assert client.get('/api/renders/missing/report').status_code==404
        assert client.get('/api/renders/bad.id/csv').status_code==400
