"""Bounded REAL key-free API checks. Not part of offline unit tests; no mocks."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from collector.connectors import JsonHTTP,Commons,NASA,APIError
from collector.core import now
from collector.search import screen
from collector.scenes import group


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=dict(started_at=now(),mode='real_network',actual_otter_manuscript='not_provided',input_scope='明示した接続・素材検索クエリのみ。本物の完成原稿の実証ではない。',checks=[],otter_kelp_candidates=[],mock_used=False)
    with tempfile.TemporaryDirectory() as tmp:
        http=JsonHTTP(cache_dir=tmp,max_requests=8)
        for provider,query in [(Commons(http),'sea otter'),(Commons(http),'kelp forest'),(NASA(http),'ocean')]:
            for kind in ('video','photo'):
                row=dict(provider=provider.name,query=query,kind=kind)
                try:
                    found=provider.search(query,kind,1)
                    row.update(state='success_candidates' if found else 'success_zero',returned=len(found),origin=http.last_info.get('origin'))
                    row['examples']=[dict(title=a['title'],page_url=a['page_url'],type=a['type'],license=a['license_name'],risk=a['risk'],access=a['access_mode']) for a in found[:3]]
                    if provider.name=='Wikimedia Commons':
                        scene=group('ラッコの生態。' if query=='sea otter' else 'ケルプの森。')[1][0]
                        for asset in found:
                            if screen(asset,scene,'一般映像・実検索検証'):
                                report['otter_kelp_candidates'].append(dict(title=asset['title'],page_url=asset['page_url'],type=kind,license=asset['license_name'],risk=asset['risk'],query=query))
                except APIError as exc:
                    row.update(state='blocked_or_error',code=exc.code,reason=str(exc))
                except Exception:
                    row.update(state='error',reason='予期しない応答。成功として扱わない。')
                report['checks'].append(row)
    report['finished_at']=now()
    report['real_candidates']=len(report['otter_kelp_candidates'])
    report['videos']=sum(x['type']=='video' for x in report['otter_kelp_candidates'])
    report['photos']=sum(x['type']=='photo' for x in report['otter_kelp_candidates'])
    report['result']='real_query_candidates_found' if report['real_candidates'] else 'real_otter_kelp_candidates_not_verified'
    report['actual_manuscript_validation']='not_run_missing_manuscript'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
