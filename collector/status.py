"""User-visible preflight and outcomes: zero candidates never imply collection success."""
from .core import now

ERROR_LABELS={'missing_key':'APIキー未設定','auth':'API認証失敗','access':'接続先でアクセス拒否（認証・ネットワーク・提供元制限を確認）','network':'接続失敗','rate_limited':'API利用上限','budget':'今回の検索予算上限','unsupported':'検索先未対応','query':'検索条件エラー','unexpected':'検索処理エラー','http':'API応答エラー','api':'API処理エラー'}

def overview(project,catalog=None):
    from .search import scene_metrics,usable
    from .downloads import permitted
    mock=project.get('mock',False)
    items=[a for a in project['assets'] if bool(a.get('mock'))==mock and usable(a)]
    latest=list(project.get('attempts',{}).values())
    done=[a for a in latest if a.get('status')=='done']
    errors=[a for a in latest if a.get('status') in ('error','rate_limited')]
    known_errors=project.get('provider_issues',{})
    provider_names=list(dict.fromkeys([x.get('provider') for x in latest]+list(known_errors)))
    if catalog:provider_names=list(dict.fromkeys([x['name'] for x in catalog if x.get('selected')]+provider_names))
    providers=[]
    for name in provider_names:
        attempts=[x for x in latest if x.get('provider')==name]
        successes=[x for x in attempts if x.get('status')=='done']
        failures=[x for x in attempts if x.get('status') in ('error','rate_limited')]
        issue=known_errors.get(name)
        code=issue.get('code') if issue else failures[-1].get('error_code') if failures else ''
        state=('一部のみ検索成功' if successes and (failures or issue) else ('検索成功・候補あり' if sum(x.get('returned',0) for x in successes) else '検索成功・候補0件') if successes else ERROR_LABELS.get(code,'未検索'))
        cat=next((x for x in (catalog or []) if x['name']==name),{})
        if not attempts and not issue:state=cat.get('state','未検索')
        found=[a for a in items if a['provider']==name]
        providers.append(dict(name=name,state=state,requests=len(attempts),returned=sum(x.get('returned',0) for x in successes),candidates=len(found),adoptable=sum(permitted(a) and bool(a.get('download_url')) for a in found),reason=issue.get('message','') if issue else '',queries=list(dict.fromkeys(x.get('query','') for x in attempts))))
    metrics=scene_metrics(project,mock)
    return dict(mode='mock' if mock else 'real',candidates=len(items),videos=sum(x['type']=='video' for x in items),photos=sum(x['type']=='photo' for x in items),adoptable=sum(permitted(x) and bool(x.get('download_url')) for x in items),short_scenes=sum(x['missing'] for x in metrics),providers=providers,successful_requests=len(done),failed_requests=len(errors),all_processed=project.get('search_phase')=='finished',
        next_action='提供元のエラーを確認し「接続確認」→再検索してください。無料キーは必須ではありません。' if not items and (errors or known_errors) else '候補0件です。シーンの英語検索語を見直し、一般映像・写真・図解を検討してください。' if not items and done else '有効な検索先を確認して検索を開始してください。' if not items else '提供元で内容・権利を確認して採用してください。不足シーンは再検索できます。')

def finish(project):
    result=overview(project)
    partial=result['failed_requests']>0 or bool(project.get('provider_issues'))
    if not result['successful_requests']:
        labels=list(dict.fromkeys(x['state'] for x in result['providers']))
        project['search_outcome']='failed'
        project['search_status']='検索失敗・実候補0件：'+(' / '.join(labels) or '検索先が有効ではありません')
    elif not result['candidates']:
        project['search_outcome']='partial_zero' if partial else 'zero'
        project['search_status']='一部のみ検索成功・候補0件（収集成功ではありません）' if partial else '検索成功・候補0件（素材は見つかりませんでした）'
    else:
        project['search_outcome']='partial' if partial else 'success'
        project['search_status']=('一部のみ検索成功' if partial else '検索成功・候補あり')+f'：{result["candidates"]}件'
    if project.get('mock'):project['search_status']='【模擬】'+project['search_status'].replace('実候補','模擬候補')
    project['search_phase']='finished';project['finished_at']=now()
    project['search_summary']=overview(project)
