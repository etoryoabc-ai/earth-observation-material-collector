"""Evidence-preserving entities, dated statements and visual intent. No LLM calls."""
import re

BIO = {
 'ラッコ': ('sea otter', 'Enhydra lutris', ('ラッコ','sea otter','Enhydra lutris'), ('sea otter swimming','sea otter feeding')),
 'ウニ': ('sea urchin', '', ('ウニ','sea urchin'), ('sea urchin underwater',)),
 'ケルプ': ('kelp', '', ('ケルプ','kelp','コンブ林'), ('kelp forest','underwater kelp forest')),
 'シャチ': ('killer whale','Orcinus orca',('シャチ','オルカ','killer whale','orca','Orcinus orca'),('orca swimming','killer whale hunting')),
 'アザラシ': ('seal','',('アザラシ',),('seal underwater',)),
 'アシカ': ('sea lion','',('アシカ','sea lion'),('sea lion swimming',)),
 'クジラ': ('whale','',('クジラ',),('whale ocean',)),
 'サケ': ('salmon','',('サケ','サーモン','salmon'),('salmon swimming',)),
}
GEO = {
 'アリューシャン列島': ('Aleutian Islands', ('アリューシャン列島','アリューシャン諸島','Aleutian Islands')),
 'アダック島': ('Adak Island', ('アダック島','アダク島','Adak Island')),
 'バンクーバー島': ('Vancouver Island', ('バンクーバー島','ヴァンクーヴァー島','Vancouver Island')),
 'サンニコラス島': ('San Nicolas Island', ('サンニコラス島','サン・ニコラス島','San Nicolas Island','San Nicholas Island')),
 'アラスカ': ('Alaska', ('アラスカ','Alaska')),
 '北太平洋': ('North Pacific', ('北太平洋','North Pacific')),
 'カリフォルニア': ('California', ('カリフォルニア','California')),
}
VISUALS = (
 ('捕食|食べ|餌|狩り', '捕食・採餌', 'feeding'),
 ('潜水|潜る|泳', '遊泳・潜水', 'swimming underwater'),
 ('個体数|減少|減った|回復|再定着|再導入', '個体数・回復の記録', 'population'),
 ('海底|海中|海の森|藻場', '海中の風景', 'underwater'),
 ('栄養カスケード|食物連鎖|捕食関係|生態系', '生態系の関係図', 'ecosystem'),
 ('調査|研究|観測', '調査記録・研究資料', 'research'),
)

def mentions(text, vocabulary, bio=False):
    result=[]
    for ja, values in vocabulary.items():
        aliases=values[2] if bio else values[1]
        hits=[]
        for alias in aliases:
            pattern=re.escape(alias)
            if alias.isascii(): pattern=r'(?<![A-Za-z])'+pattern+r'(?![A-Za-z])'
            hits.extend((m.start(),m.end(),m.group()) for m in re.finditer(pattern,text,re.I))
        if hits:
            first=min(hits)
            item=dict(ja=ja,en=values[0],evidence=first[2],local_start=first[0],local_end=first[1])
            if bio:item['scientific']=values[1] or '要確認'
            else:item['coordinates']='要確認'
            result.append(item)
    if any(x['ja']=='シャチ' for x in result):
        result=[x for x in result if x['ja']!='クジラ' or 'クジラ' in text]
    return sorted(result,key=lambda x:x['local_start'])

def details(text):
    animals=mentions(text,BIO,True); places=mentions(text,GEO)
    year_matches=list(re.finditer(r'(?<!\d)(?:1[5-9]|20)\d{2}(?:年代|年)?(?!\d)',text))
    years=list(dict.fromkeys(m.group() for m in year_matches))
    hypothesis=bool(re.search('仮説|可能性|かもしれ|推測|と考え|とされ|証明されていない|断定でき',text))
    observation=bool(re.search('調査|観測|記録|確認された|報告|研究',text))
    intents=[dict(ja=ja,en=en) for pattern,ja,en in VISUALS if re.search(pattern,text)]
    diagram=bool(re.search('比較|個体数|食物連鎖|栄養カスケード|位置|仕組み|関係',text))
    bare=re.sub(r'(?m)^(?:#{1,6}\s+[^\r\n]*|第[0-9０-９一二三四五六七八九十]+章[^\r\n]*)','',text).strip()
    # Each statement retains its own places, years and hypothesis status. Never
    # pair one scene's year with a different scene's place.
    statements=[]
    for m in re.finditer(r'[^。！？\n]+[。！？]?|\n',text):
        st=m.group()
        if not st.strip() or st.lstrip().startswith('#'):continue
        statements.append(dict(text=st,local_start=m.start(),local_end=m.end(),
            places=[x['ja'] for x in mentions(st,GEO)], animals=[x['ja'] for x in mentions(st,BIO,True)],
            years=re.findall(r'(?<!\d)(?:1[5-9]|20)\d{2}(?:年代|年)?(?!\d)',st),
            status='仮説（原稿の記述・未検証）' if re.search('仮説|可能性|かもしれ|推測|と考え|とされ',st) else '原稿の記述（未検証）',
            association='複数地点：各地点への年代の割当は要確認' if len(mentions(st,GEO))>1 else '同一文に明示された情報のみ。実際の対応は要確認'))
    needs=[]
    if animals:needs.append(' / '.join(x['ja'] for x in animals)+'の実写')
    if intents:needs.append(' / '.join(x['ja'] for x in intents))
    if diagram:needs.append('図解・比較資料（検証済みデータが必要）')
    if not needs:needs=['原稿に対応する風景・記録（検索語を確認）']
    return dict(searchable=bool(bare),animals=animals,places=places,years=years,statements=statements,
        visual_intents=intents,claim_type='仮説（要確認）' if hypothesis else '観測・研究の記述（出典未検証）' if observation else '原稿の記述（未検証）',
        summary=text.strip()[:160], required_material='タイトル（検索不要）' if not bare else '。'.join(needs),
        material_type='diagram' if diagram else 'video',keywords=list(dict.fromkeys(x['ja'] for x in animals+places)),
        english_queries=[],priority='必須',alternatives='同じ生物の一般映像 → 写真 → 位置図・関係図。場所・年代の一致は断定しない',
        fact_check='要確認：原稿の研究結果・年代対応、撮影地・種・行動・実記録と一般映像の区別',
        slide_request='原稿の説明を図解。数値・座標・因果関係は確認済み情報源を入力してから作成。' if diagram else '')

def annotate_offsets(scenes):
    for scene in scenes:
        for key in ('animals','places','statements'):
            for item in scene.get(key,[]):
                item['source_start']=scene['start']+item['local_start']
                item['source_end']=scene['start']+item['local_end']
    return scenes
