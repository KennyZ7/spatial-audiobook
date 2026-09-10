"""Offline reports derived exclusively from a render's saved timeline and snapshot."""
import csv
import html
import io
import json

KINDS = {'speech':'人声', 'sfx':'音效', 'ambience':'环境声', 'music':'音乐'}
HEADERS = ['排序号','事件 ID','开始时间（秒）','结束时间（秒）','时长（秒）','关联台词 ID',
           '事件类型','原文','实际朗读文本','角色','音色 ID','情绪','素材 ID','素材名称',
           '增益 dB','空间处理方式','起点方位','起点坐标','终点坐标','完整轨迹 JSON']


def direction(p):
    return '、'.join(label for key,positive,negative in [('x','右','左'),('y','上','下'),('z','前','后')]
                    if (label := positive if p[key]>0 else negative if p[key]<0 else '')) or '听众原点'


def rows(manifest, assets=()):
    project = manifest['project']
    events = {e['id']:e for e in project['events']}
    order = {eid:i for i,eid in enumerate(events)}
    characters = {c['id']:c for c in project['characters']}
    names = {a['id']:a.get('name',a['id']) for a in assets}
    names.update(manifest.get('asset_names', {}))
    result = []
    for i,item in enumerate(sorted(manifest['timeline'], key=lambda a:(a['start'],order.get(a['id'],len(order))))):
        e = events[item['id']]
        speech = item['kind']=='speech'
        anchor = events.get(e.get('anchor_id'), {})
        original = e.get('original','') if speech else anchor.get('original','') if anchor.get('kind')=='speech' else ''
        char = characters.get(e.get('character_id'), {}) if speech else {}
        points = [{**{k:p[k] for k in ('t','x','y','z')},'absolute_time':item['start']+p['t']} for p in item['points']]
        narrator = item.get('narrator',False)
        mode = '居中双声道，不参与空间定位；下列坐标为未参与渲染的配置值' if narrator else '双耳空间定位'
        aid = e.get('asset_id','')
        coord = lambda p: json.dumps([p[k] for k in ('x','y','z')],ensure_ascii=False)
        values = [i+1,item['id'],item['start'],item['start']+item['duration'],item['duration'],e.get('anchor_id',''),
                  KINDS[item['kind']],original,e.get('text','') if speech else '',char.get('name',''),char.get('voice',''),
                  e.get('emotion','') if speech else '',aid,names.get(aid,aid),item['gain_db'],mode,
                  '居中（坐标未应用）' if narrator else direction(points[0]),coord(points[0]),coord(points[-1]),
                  json.dumps(points,ensure_ascii=False,separators=(',',':'))]
        result.append(dict(values=values,kind=item['kind'],points=points))
    return result


def csv_bytes(manifest, assets=()):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(HEADERS)
    def safe(v):
        # Only text is escaped: signed numeric gains remain numeric.
        if isinstance(v,str) and (v.lstrip().startswith(('=','+','-','@')) or v.startswith(('\t','\r','\n'))):
            return "'"+v
        return v
    writer.writerows([safe(v) for v in r['values']] for r in rows(manifest,assets))
    return stream.getvalue().encode('utf-8-sig')


def html_text(manifest, assets=()):
    esc = lambda v: html.escape(str(v),quote=True)
    project = manifest['project']
    data = rows(manifest,assets)
    duration = max(manifest.get('metrics',{}).get('duration',0),max((r['values'][3] for r in data),default=0),.001)
    stamp = lambda seconds: f'{int(seconds//60):02d}:{seconds%60:06.3f}'
    bars = []
    for kind,label in KINDS.items():
        lanes = []
        blocks = []
        for r in data:
            if r['kind']!=kind: continue
            v=r['values']; lane=next((i for i,end in enumerate(lanes) if end<=v[2]),len(lanes))
            if lane==len(lanes): lanes.append(v[3])
            else: lanes[lane]=v[3]
            blocks.append(f'<a class="bar {kind}" data-kind="{kind}" href="#event-{v[0]}" style="left:{v[2]/duration*100}%;width:{max(.15,v[4]/duration*100)}%;top:{lane*28}px" title="{esc(str(v[0])+" · "+(v[9] or v[13] or v[1]))}">{v[0]}</a>')
        bars.append(f'<div class="track"><b>{label}</b><div class="lane" style="height:{max(1,len(lanes))*28}px">'+''.join(blocks)+'</div></div>')
    body=[]
    for r in data:
        v=r['values']
        trajectory=''.join('<tr>'+''.join(f'<td>{esc(p[k])}</td>' for k in ('t','absolute_time','x','y','z'))+'</tr>' for p in r['points'])
        cells=''.join(f'<td>{esc(value)}</td>' for value in [v[0],v[1],f'{stamp(v[2])} → {stamp(v[3])}\n{v[2]} → {v[3]} 秒',v[4],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13],v[5],v[14],v[15],v[16],v[17],v[18]])
        body.append(f'<tr id="event-{v[0]}" data-kind="{r["kind"]}">{cells}<td><details><summary>查看轨迹（{len(r["points"])}点）</summary><table><tr><th>相对秒</th><th>绝对秒</th><th>x</th><th>y</th><th>z</th></tr>{trajectory}</table></details></td></tr>')
    columns=['序号','事件 ID','开始 → 编排结束','时长（秒）','类型','原文','实际朗读','角色','音色 ID','情绪','素材 ID','素材名称','关联台词 ID','增益 dB','空间处理','起点方位','起点坐标','终点坐标','完整轨迹']
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>声音脚本与空间轨迹</title><style>
body{font:15px/1.6 system-ui,sans-serif;margin:32px;color:#24332f;background:#f7f8f4}h1{margin-bottom:8px}p{max-width:1100px}.controls{display:flex;gap:16px;margin:24px 0}input,select{padding:10px;font:inherit}input{width:380px;max-width:60vw}.track{display:flex;gap:16px;margin:12px 0}.track>b{width:55px;flex-shrink:0}.lane{position:relative;flex:1;background:#e4e9e4}.bar{position:absolute;box-sizing:border-box;min-width:2px;height:24px;color:white;overflow:hidden;font-size:12px;text-decoration:none;border-radius:3px}.speech{background:#377a69}.sfx{background:#a15f30}.ambience{background:#496fa0}.music{background:#80598b}.scroll{overflow:auto;max-height:75vh;background:white}table{border-collapse:collapse}td,th{border:1px solid #d9dfd8;padding:8px;text-align:left;vertical-align:top;min-width:80px;white-space:pre-wrap;overflow-wrap:anywhere}th{background:#e8ede7;position:sticky;top:0;z-index:1}td:nth-child(6),td:nth-child(7){min-width:220px}tr:target{background:#fff0c9}details table{font-size:13px}summary{cursor:pointer;white-space:nowrap}[hidden]{display:none!important}
</style><h1>'''+esc(project['title'])+''' · 声音脚本</h1><p>工程版本 '''+esc(project['revision'])+' · 成品 '+esc(manifest['id'])+' · 总时长 '+stamp(duration)+' · HRTF '+esc(project['render']['profile'])+'''</p>
<p>坐标单位：米；右侧 +x，上方 +y，前方 +z，听众位于原点。结束时间为编排结束时间，混响尾音可能延续。旁白居中播放，其配置坐标不参与渲染。表中时间以成品快照为准，轨迹末点为最后一个配置控制点。</p>
<h2>声音时间线</h2><p>从 00:00 到 '''+stamp(duration)+'''；同类重叠事件分行显示。点击色块跳到对应事件；编号与表格一致。</p>'''+''.join(bars)+'''
<div class="controls"><select id="kind"><option value="">全部类型</option>'''+''.join(f'<option value="{k}">{v}</option>' for k,v in KINDS.items())+'''</select><input id="search" placeholder="搜索原文、台词、角色或素材" aria-label="搜索"><span id="count"></span></div>
<div class="scroll"><table id="events"><thead><tr>'''+''.join(f'<th>{c}</th>' for c in columns)+'''</tr></thead><tbody>'''+''.join(body)+'''</tbody></table></div>
<script>
const rows=[...document.querySelectorAll('#events > tbody > tr')],kind=document.querySelector('#kind'),search=document.querySelector('#search');
function filter(){let n=0;const q=search.value.toLowerCase();for(const row of rows){row.hidden=!!((kind.value&&row.dataset.kind!==kind.value)||!row.textContent.toLowerCase().includes(q));if(!row.hidden)n++;const bar=document.querySelector('.bar[href="#'+row.id+'"]');if(bar)bar.hidden=row.hidden}document.querySelector('#count').textContent=n+' / '+rows.length+' 个事件'}
kind.addEventListener('change',filter);search.addEventListener('input',filter);filter();
document.querySelectorAll('.bar').forEach(bar=>bar.addEventListener('click',()=>{const row=document.getElementById(bar.hash.slice(1));row.querySelector('details').open=true;row.scrollIntoView({block:'center'})}));
</script></html>'''
