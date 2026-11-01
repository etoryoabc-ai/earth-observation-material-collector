"""Two-stage lossless text units -> visual scene groups. No fixed scene count."""
import re
import hashlib
from .analysis import details, annotate_offsets

HEADING=re.compile(r'(?m)^[ \t]*(?:#{1,6}[ \t]+[^\r\n]+|[【\[]?(?:第[0-9０-９一二三四五六七八九十]+章|導入|プロローグ|結び|終章|エピローグ)(?:[^\r\n]*)|[0-9０-９]+[.．、][ \t]+[^\r\n]+)\r?\n?')
TOPICS=(
 ('history','毛皮|乱獲|狩猟|禁猟|保護条約|交易'),
 ('reintroduction','再導入|再定着|移入|移送|再移入'),
 ('survey_comparison','1987|1997|海底調査|調査比較'),
 ('orca_hypothesis','シャチ|オルカ|killer whale|orca'),
 ('population_decline','急減|激減|1990年代|個体数.*減|ラッコ.*減少'),
 ('urchin_barren','荒地|磯焼け|ウニ.*海藻|海藻.*ウニ'),
 ('otter_feeding','ラッコ.*(?:食べ|捕食|ウニ)|(?:捕食|食べ).*ラッコ'),
 ('cascade','栄養カスケード|食物連鎖|連鎖|生態系.*仕組み'),
 ('kelp_recovery','ケルプ.*回復|森.*回復|海藻.*回復'),
 ('kelp_habitat','ケルプ|海の森|海藻の森|藻場'),
 ('marine_life','魚|甲殻類|カニ|エビ|貝'),
 ('otter_ecology','ラッコ|Enhydra lutris|sea otter'),
 ('location','位置|列島|島|海岸|風景'),
)
LABELS=dict(history='乱獲・保護の歴史',reintroduction='再導入・再定着',survey_comparison='調査・比較',orca_hypothesis='シャチの観測・仮説',population_decline='ラッコの減少',urchin_barren='ウニと荒地',otter_feeding='ラッコの採餌',cascade='栄養カスケード',kelp_recovery='森の回復',kelp_habitat='海藻の森',marine_life='森の生き物',otter_ecology='ラッコの生態',location='場所・風景',general='説明・風景')

def topic(text):
    for name,pattern in TOPICS:
        if re.search(pattern,text,re.I):return name
    return 'general'

def units(source):
    if not source.strip():raise ValueError('原稿が空です。')
    result=[];cursor=0;chapter='本文'
    def append(a,b,kind):
        text=source[a:b]
        result.append(dict(id=len(result)+1,start=a,end=b,text=text,kind=kind,chapter=chapter,
                           topic=topic(text) if kind=='body' else '',analysis=details(text) if kind=='body' else {}))
    def body(lo,hi):
        for m in re.finditer(r'[^。！？\n]+[。！？]*(?:\n)?|[。！？]+\n?|\n',source[lo:hi]):
            append(lo+m.start(),lo+m.end(),'body' if m.group().strip() else 'spacing')
    for m in HEADING.finditer(source):
        body(cursor,m.start())
        label=m.group().strip().lstrip('#').strip()
        # A video title / H1 remains structural metadata, not a new search scene.
        if re.search(r'第.+章|導入|結び|終章|プロローグ|エピローグ',label) or m.group().lstrip().startswith('##'):
            chapter=label
        append(m.start(),m.end(),'heading');cursor=m.end()
    body(cursor,len(source))
    previous=None
    for unit in result:
        unit['context_inferences']=[]
        if unit['kind']=='body':
            if previous and previous['chapter']==unit['chapter'] and not unit['analysis']['places'] and re.search('この島|この海域|その場所',unit['text']):
                if previous['analysis']['places']:
                    unit['context_inferences']=[dict(kind='場所の指示語',suggested=[x['ja'] for x in previous['analysis']['places']],certainty='推定・要確認',evidence_unit_id=previous['id'])]
            previous=unit
    if ''.join(x['text'] for x in result)!=source:raise ValueError('文単位の原稿保持検査に失敗しました。')
    return result

def scene_details(text):
    masked=list(text)
    for match in HEADING.finditer(text):
        for index in range(match.start(),match.end()):
            if masked[index] not in ('\r','\n'):masked[index]=' '
    return details(''.join(masked))


def rebuild(source,groups):
    scenes=[]
    for i,(lo,hi,unit_ids,chapter,visual_topic) in enumerate(groups,1):
        text=source[lo:hi];d=scene_details(text)
        # Heading mentions must never inject entities into a body-only claim.
        body=''.join(u['text'] for u in units(text) if u['kind']=='body')
        d['searchable']=bool(body.strip())
        scene=dict(id=i,chapter=chapter,start=lo,end=hi,text=text,unit_ids=unit_ids,
                   visual_topic=visual_topic,**d)
        scene['summary']=LABELS.get(visual_topic,visual_topic)+'：'+body.strip()[:100]
        scene['context_inferences']=[x for u in units(text) for x in u.get('context_inferences',[])]
        scenes.append(scene)
    annotate_offsets(scenes)
    validate(source,scenes)
    return scenes

def group(source):
    text_units=units(source);groups=[];pending=[];active=[];current_topic=None;current_places=set();body_count=0
    def flush():
        nonlocal active,body_count,current_topic,current_places
        if active:
            groups.append((active[0]['start'],active[-1]['end'],[x['id'] for x in active],next((x['chapter'] for x in active if x['kind']=='body'),active[0]['chapter']),current_topic or 'general'))
        active=[];body_count=0;current_topic=None;current_places=set()
    for unit_index, unit in enumerate(text_units):
        if unit['kind']=='heading':
            if body_count:flush()
            pending.append(unit);continue
        if unit['kind']=='spacing':
            (active if active else pending).append(unit);continue
        new_places={x['ja'] for x in unit['analysis']['places']}
        # Narrowing Aleutians -> Adak may share geographic context, whereas
        # Vancouver and San Nicolas must always form separate visual scenes.
        distinct_place=bool(new_places and current_places and new_places.isdisjoint(current_places))
        topic_change=unit['topic']!='general' and current_topic not in (None,'general',unit['topic'])
        strong_transition=bool(re.match(r'\s*(一方|別の地域|しかし|ところが|次に|それでは|時代を)',unit['text']))
        # Changes are assessed over a visual group: generic linking sentences do
        # not force cuts, and isolated animal mentions do not force cuts.
        following=next((x for x in text_units[unit_index+1:] if x['kind'] in ('body','heading')),None)
        sustained=bool(following and following['kind']=='body' and following['topic']==unit['topic'])
        editorial=unit['topic'] in ('history','reintroduction','survey_comparison','orca_hypothesis','cascade')
        cut=body_count>0 and (distinct_place or (topic_change and (strong_transition or (body_count>=2 and (sustained or editorial)))))
        if cut:flush()
        active.extend(pending);pending=[];active.append(unit);body_count+=1
        if unit['topic']!='general':current_topic=unit['topic']
        if new_places:current_places=new_places
    if pending:
        if active:active.extend(pending)
        elif groups:
            lo,_,ids,ch,tp=groups[-1];groups[-1]=(lo,pending[-1]['end'],ids+[x['id'] for x in pending],ch,tp)
        else:active=pending
    flush()
    return text_units,rebuild(source,groups)

def validate(source,scenes):
    cursor=0
    for s in scenes:
        if s['start']!=cursor or s['end']<=s['start'] or source[s['start']:s['end']]!=s['text']:
            raise ValueError('シーンと原稿の位置・順序・重複検査に失敗しました。')
        cursor=s['end']
    if cursor!=len(source) or ''.join(x['text'] for x in scenes)!=source:
        raise ValueError('原稿の欠落検査に失敗しました。')
    return dict(characters=len(source),sha256=hashlib.sha256(source.encode()).hexdigest(),lossless=True)


def edit_structure(project,operation,scene_id,offset=None):
    source=project['source'];scenes=project['scenes'];index=next(i for i,s in enumerate(scenes) if s['id']==scene_id)
    if operation=='merge':
        if index+1>=len(scenes):raise ValueError('最後のシーンは次と結合できません。')
        cuts=[(s['start'],s['end']) for s in scenes]
        cuts[index:index+2]=[(scenes[index]['start'],scenes[index+1]['end'])]
    else:
        s=scenes[index];cut=s['start']+int(offset)
        if not s['start']<cut<s['end']:raise ValueError('分割位置が範囲外です。')
        cuts=[(x['start'],x['end']) for x in scenes];cuts[index:index+1]=[(s['start'],cut),(cut,s['end'])]
    updated=[];mapping={}
    for new_id,(lo,hi) in enumerate(cuts,1):
        exact=next((s for s in scenes if s['start']==lo and s['end']==hi),None)
        if exact:
            entry=dict(exact);entry['id']=new_id
        else:
            d=scene_details(source[lo:hi]);entry=dict(id=new_id,start=lo,end=hi,text=source[lo:hi],chapter=scenes[index]['chapter'],visual_topic=topic(source[lo:hi]),unit_ids=[],context_inferences=[],**d)
        updated.append(entry)
        for old in scenes:
            if max(lo,old['start'])<min(hi,old['end']):mapping.setdefault(old['id'],[]).append(new_id)
    # Existing decisions/files are preserved. A split must not duplicate adopted
    # footage: keep it on the first part and clearly request human reassignment.
    for asset in project['assets']:
        targets=mapping[asset['scene_id']]
        asset['scene_id']=targets[0]
        if len(targets)>1:asset['assignment_note']='手動分割後：先頭側へ保持。必要なら素材の割当を再確認。'
    occupied=set()
    next_number=max((a.get('material_number',0) for a in project['assets']),default=0)+1
    for asset in project['assets']:
        if asset.get('material_number'):
            key=(asset['scene_id'],asset['type'],asset['material_number'])
            if key in occupied and not asset.get('downloaded'):
                asset['material_number']=next_number;next_number+=1
                key=(asset['scene_id'],asset['type'],asset['material_number'])
            occupied.add(key)
    project['scenes']=annotate_offsets(updated)
    project.setdefault('structural_history',[]).append(dict(operation=operation,scene_id=scene_id,mapping=mapping))
    project.setdefault('archived_attempts',[]).extend(project['attempts'].values())
    project['attempts']={};project['attempt_history']=[];project['provider_issues']={}
    project['search_revision']=project.get('search_revision',0)+1
    project['search_status']='シーン構成を変更しました。素材の割当を確認して再検索できます。'
    project['search_phase']='edited'
    project['search_outcome']='not_started'
    project['source_validation']=validate(source,project['scenes'])
