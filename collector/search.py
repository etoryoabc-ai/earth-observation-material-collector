"""Video-first query expansion, per-provider progress and auditable evidence."""
import hashlib
import re
from .core import now
from .analysis import BIO, GEO
from .connectors import APIError, RateLimited
from .status import finish
from urllib.parse import urlsplit


def queries(scene):
    animals=scene.get('animals',[]); places=scene.get('places',[])
    ja=' '.join(scene.get('keywords',[])) or scene['summary'].strip('# \r\n')[:70]
    terms=[x['en'] for x in animals+places]
    results=[(ja,'日本語・原稿由来')]
    for q in scene.get('english_queries',[]):
        results.append((q,'英語・手動指定'))
    if terms: results.append((' '.join(terms),'英語・明示された固有名'))
    # Split multi-animal subjects: combining every species into a single phrase
    # often finds nothing. Keep precise place in this first expansion.
    for a in animals:
        located=' '.join([a['en']]+[p['en'] for p in places])
        results.append((located,'英語・生物と明示地名'))
        if a.get('scientific') and a['scientific']!='要確認':
            results.append((' '.join([a['scientific']]+[p['en'] for p in places]),'学名・明示地名'))
    for a in animals:
        for alias in (BIO.get(a['ja'],('','','',()))[3]):
            # Related visual actions must be present in the scene, not invented.
            if ('feeding' in alias or 'hunting' in alias) and not re.search('捕食|食べ|餌|狩り',scene['text']):continue
            results.append((alias,'一般映像・撮影地と年代は一致未確認'))
        results.append((a['en'],'一般映像・生物単独'))
    if 'killer whale' in ' '.join(terms):
        results.append(('orca','一般映像・別表記'))
    for p in places:
        results.append((p['en'],'場所の一般風景・年代未確認'))
    if re.search('ケルプ|kelp|海の森|藻場',scene['text'],re.I):
        results.extend([('kelp forest','一般映像・海中の森'),('underwater kelp forest','一般映像・海中の森・別表記')])
    if any(p['ja']=='アダック島' for p in places):
        for animal in animals:
            results.append((animal['en']+' Aleutian Islands','一般映像・広域地名（アダック島撮影は未確認）'))
    unique={}
    for query,stage in results:
        query=re.sub(r'\s+',' ',query).strip()
        if query:unique.setdefault(query,stage)
    return list(unique.items())[:24]


def usable(a):
    return a.get('decision')!='reject' and a.get('risk')!='E' and a.get('match_status')!='excluded'


def enough(assets,target=9):
    items=[a for a in assets if usable(a)]
    return len(items)>=target and sum(a['type']=='video' for a in items)>=6 and sum(a['type']=='photo' for a in items)>=3


def screen(asset,scene,stage):
    """Only reject explicit metadata conflicts. Never assert species/place by title."""
    text=(asset.get('metadata_text') or asset.get('title','')).lower()
    wanted={x['ja'] for x in scene.get('animals',[])}
    conflict=[]
    if 'ラッコ' in wanted and re.search(r'river otter|giant otter|asian small.clawed otter|カワウソ',text) and not re.search('sea otter|enhydra lutris|ラッコ',text):
        conflict.append('ラッコに対して別種のカワウソ表記')
    if re.search(r'\b(?:cartoon|animation|illustration|ai generated)\b',text) and asset['type']=='video':
        conflict.append('実写に対してアニメーション等の表記')
    if wanted and not conflict and '場所の一般風景' not in stage:
        aliases=[term for animal in scene.get('animals',[]) for term in BIO.get(animal['ja'],('','','',()))[2]]
        if aliases and not any(term.lower() in text for term in aliases):
            conflict.append('対象生物を示すメタデータが不足。関連未確認のため件数に算入しない')
    general='一般' in stage
    asset.update(match_status='excluded' if conflict else 'general' if general else 'tentative',
        relevance='低' if conflict else '要確認',
        relevance_reason='メタデータ上の相違：'+' / '.join(conflict) if conflict else f'{stage}で取得。本文・映像は未照合。タイトルだけでは一致を断定しない。',
        place_certainty='一般映像：指定地点と一致未確認' if general else '要確認',
        species_certainty='要確認',year_certainty='調査年代・撮影年とも要確認',
        record_type='一般的な代替映像候補' if general else '実記録か一般映像か要確認')
    return not conflict


def fingerprint(asset):
    url=asset.get('download_url') or asset.get('thumbnail') or ''
    parts=urlsplit(url)
    return (parts.netloc.lower(),parts.path) if url else None


def run_search(project,connectors,save,stop=lambda:False):
    project['search_status']='検索中'
    project['search_phase']='running'
    project['active_providers']=[x.name for x in connectors]
    project['progress']={'scene_index':0,'scene_total':sum(s.get('searchable',True) for s in project['scenes']),'requests':0}
    run_id=hashlib.sha256(now().encode()).hexdigest()[:12]
    mock=project['mock']
    save(project)
    failed=set()
    project['provider_issues']={}
    try:
        for scene_index, scene in enumerate(project['scenes'],1):
            if not scene.get('searchable',True):continue
            sid=scene['id']
            project['progress'].update(scene_index=scene_index,scene_id=sid)
            save(project)
            all_items=lambda:[a for a in project['assets'] if a['scene_id']==sid and bool(a.get('mock'))==mock]
            active=lambda:[a for a in all_items() if usable(a)]
            seen={(a['provider'],a['provider_id'],a['type']) for a in all_items()}
            plan=queries(scene)
            # Search video across languages before images. Always try one English
            # video query when available, even if Japanese results filled a quota.
            for kind,goal in (('video',6),('photo',3)):
                english_done=False
                for query,stage in plan:
                    is_english=bool(re.search('[A-Za-z]',query))
                    count=sum(a['type']==kind for a in active())
                    if count>=goal and (english_done or not any(re.search('[A-Za-z]',q) for q,_ in plan)):
                        break
                    for page in (1,2):
                        page_found=False
                        for connector in connectors:
                            if connector.name in failed:continue
                            if stop():
                                project['search_status']='一時停止';project['search_phase']='paused';return
                            key=hashlib.sha256(f'{mock}|{sid}|{connector.name}|{query}|{kind}|{page}'.encode()).hexdigest()
                            previous=project['attempts'].get(key,{})
                            # A successful prior response can be consumed again from
                            # cache after rejections; no duplicate IDs are re-added.
                            if previous.get('status')=='done' and previous.get('revision')==project.get('search_revision',0):
                                page_found=page_found or previous.get('returned',previous.get('added',0))>0
                                continue
                            entry=dict(scene=sid,provider=connector.name,query=query,stage=stage,kind=kind,page=page,
                                       run_id=run_id,mode='mock' if mock else 'real',revision=project.get('search_revision',0),at=now())
                            project['progress'].update(provider=connector.name,query=query,kind=kind,requests=project['progress']['requests']+1)
                            save(project)
                            try:
                                results=connector.search(query,kind,page)
                                info=getattr(getattr(connector,'http',None),'last_info',{})
                            except APIError as exc:
                                entry.update(status='rate_limited' if isinstance(exc,RateLimited) else 'error',error_code=exc.code,error=str(exc),retry_at=exc.retry_at)
                                if exc.code!='query':
                                    failed.add(connector.name)
                                    project['provider_issues'][connector.name]=dict(code=exc.code,message=str(exc),retry_at=exc.retry_at)
                                project['attempts'][key]=entry
                                project.setdefault('attempt_history',[]).append(dict(entry))
                                project['logs'].append(f'シーン{sid} / {connector.name}：{exc}')
                                save(project);continue
                            except Exception:
                                entry.update(status='error',error_code='unexpected',error='応答形式またはコネクターのエラー（キー非表示）')
                                failed.add(connector.name);project['attempts'][key]=entry
                                project.setdefault('attempt_history',[]).append(dict(entry))
                                project['provider_issues'][connector.name]={'code':'unexpected','message':entry['error']}
                                save(project);continue
                            page_found=page_found or bool(results)
                            added=0;excluded=0
                            # Small per-response batches allow another provider to
                            # contribute before one provider occupies every slot.
                            batch=3 if kind=='video' else 2
                            for a in results:
                                if sum(x['type']==kind for x in active())>=goal or added>=batch:break
                                identity=(a['provider'],a['provider_id'],a['type'])
                                if identity in seen:continue
                                if fingerprint(a) and any(fingerprint(x)==fingerprint(a) for x in all_items()):continue
                                seen.add(identity)
                                if not screen(a,scene,stage):
                                    excluded+=1
                                    # Retain conflict evidence without filling candidate quotas.
                                    if sum(x.get('match_status')=='excluded' for x in all_items())>=10:continue
                                a.update(id=hashlib.sha256(f'{sid}|{a["provider"]}|{a["provider_id"]}|{a["type"]}'.encode()).hexdigest()[:24],
                                         scene_id=sid,query=query,search_stage=stage,collected_at=now(),
                                         api_origin=a.get('api_origin',info.get('origin','mock' if mock else 'unverified')))
                                project['assets'].append(a)
                                if a['match_status']!='excluded':added+=1
                            entry.update(status='done',returned=len(results),added=added,excluded=excluded,
                                         origin='mock' if mock else info.get('origin','unverified'),fetched_at=info.get('fetched_at',''))
                            project['attempts'][key]=entry
                            project.setdefault('attempt_history',[]).append(dict(entry))
                            save(project)
                        if sum(a['type']==kind for a in active())>=goal or not page_found:break
                    english_done=english_done or is_english
                    if len(failed)==len(connectors):break
            # Core targets are intentionally not relaxed into unrelated material.
        finish(project)
    finally:
        save(project)


def scene_metrics(project,mock=False):
    rows=[]
    for s in project['scenes']:
        if not s.get('searchable',True):continue
        all_items=[a for a in project['assets'] if a['scene_id']==s['id'] and bool(a.get('mock'))==mock]
        items=[a for a in all_items if usable(a)]
        videos=sum(a['type']=='video' for a in items);photos=sum(a['type']=='photo' for a in items)
        attempts=[x for x in project['attempts'].values() if x.get('scene')==s['id'] and x.get('mode','real')==('mock' if mock else 'real')]
        reasons=list(dict.fromkeys(x.get('error',x.get('status','')) for x in attempts if x['status']!='done'))
        if not reasons:
            reasons=[x['message'] for x in project.get('provider_issues',{}).values()]
        deficit=[]
        if videos<6:deficit.append(f'動画{6-videos}件不足')
        if photos<3:deficit.append(f'写真{3-photos}件不足')
        if len(items)<9:deficit.append(f'合計{9-len(items)}件不足')
        rows.append(dict(scene_id=s['id'],candidates=len(items),videos=videos,photos=photos,
            video_ratio=round(videos/len(items)*100,1) if items else 0,
            adopted=sum(a['decision']=='adopt' for a in items),downloaded=sum(bool(a.get('downloaded')) for a in items),
            general=sum(a.get('match_status')=='general' for a in items),excluded=sum(a.get('match_status')=='excluded' for a in all_items),
            confirmed_relevance=sum(a.get('relevance')=='高' and a.get('human_checked') is True for a in items),
            live_requests=sum(x.get('origin')=='api_network' for x in project.get('attempt_history',attempts) if x.get('scene')==s['id']),cached_requests=sum(x.get('origin')=='api_cache' for x in project.get('attempt_history',attempts) if x.get('scene')==s['id']),
            missing=bool(deficit),reason=' / '.join(deficit+reasons) if deficit else '候補目標達成（内容・権利は未確定）',
            alternative=s['alternatives'],suggestion=s.get('slide_request') or '同じ生物の一般映像・写真・図解を検討。指定地の記録と誤認させない。',
            mode='mock' if mock else 'real'))
    return rows


def shortages(project):
    return [row for row in scene_metrics(project) if row['missing']]
