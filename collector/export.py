import csv
import html
import json
import shutil
from datetime import datetime
from pathlib import Path
from .core import atomic_json
from .search import shortages, scene_metrics, usable


def csv_write(path, rows, fields=None):
    fields = fields or list(dict.fromkeys(k for row in rows for k in row)) or ['status']
    def cell(value):
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + value  # prevent spreadsheet formula execution
        return value
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: cell(row.get(k, '')) for k in fields})


def export_project(project, root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / (datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    target.mkdir(exist_ok=False)
    scenes, assets = project['scenes'], project['assets']
    csv_write(target / 'scene_list.csv', scenes)
    csv_write(target / 'asset_candidates.csv', assets, ['id', 'scene_id', 'title', 'type', 'provider', 'page_url', 'query', 'search_stage', 'relevance', 'relevance_reason', 'place_certainty', 'species_certainty', 'year_certainty', 'record_type', 'width', 'height', 'duration', 'format', 'size', 'mock', 'api_origin', 'api_fetched_at', 'match_status', 'record_type'])
    csv_write(target / 'download_manifest.csv', assets, ['id', 'scene_id', 'title', 'decision', 'downloaded', 'download_error', 'sha256', 'mock'])
    csv_write(target / 'license_report.csv', assets, ['id', 'scene_id', 'title', 'page_url', 'creator', 'institution', 'license_name', 'license_url', 'commercial', 'modification', 'attribution', 'terms', 'checked_at', 'evidence', 'risk', 'human_checked', 'citation_reason', 'citation_script', 'citation_range', 'citation_distinct', 'citation_source', 'citation_main', 'commercial_policy', 'license_scope', 'policy_evidence_url', 'policy_checked_at', 'free_only'])
    csv_write(target / 'missing_assets.csv', shortages(project), ['scene_id', 'candidates', 'videos', 'photos', 'adopted', 'reason', 'alternative', 'suggestion'])
    csv_write(target / 'slide_requests.csv', [dict(scene_id=s['id'], text=s['text'], request=s['slide_request'], labels=s['keywords'], numbers='検証済み資料を手動入力', source='要確認') for s in scenes if s['slide_request']], ['scene_id', 'text', 'request', 'labels', 'numbers', 'source'])
    for mock,filename in ((False,'scene_metrics_real.csv'),(True,'scene_metrics_mock.csv')):
        csv_write(target / filename,scene_metrics(project,mock))
    csv_write(target / 'search_attempts.csv',project.get('attempt_history',list(project['attempts'].values())))
    atomic_json(target / 'validation_report.json',dict(
        project_name=project['name'],source_sha256=__import__('hashlib').sha256(project['source'].encode()).hexdigest(),
        mode='mock' if project['mock'] else 'real',
        real=scene_metrics(project),mock=scene_metrics(project,True),
        caution='検索APIの実応答と模擬応答は別集計。候補数は原稿との一致や利用条件の確認完了を意味しません。'))
    adopted = [a for a in assets if a['decision'] == 'adopt' and not a.get('mock')]
    sources = ['# 採用素材の出典', '利用前に素材固有の条件と改変表記を最終確認してください。', '']
    for a in adopted:
        sources.extend([f'- シーン{a["scene_id"]}：{a["title"]}', f'  作成者：{a["creator"]} / 提供：{a["institution"]}',
                        f'  出典：{a["page_url"]}', f'  ライセンス：{a["license_name"]} {a["license_url"]}',
                        f'  条件：{a["terms"]} / 表示義務：{a["attribution"]} / 改変：{a["modification"]}'])
    (target / 'sources.md').write_text('\n'.join(sources), encoding='utf-8')
    real = [a for a in assets if not a.get('mock') and usable(a)]
    summary = f'# 収集結果\n\n原稿：{project["name"]}\n\n解析：{project["analysis_mode"]}\n\nシーン：{len(scenes)} / 実候補：{len(real)} / 模擬：{sum(bool(a.get('mock')) for a in assets)} / 採用：{len(adopted)}\n\n状態：{project["search_status"]}\n\n不足シーン：{len(shortages(project))}\n\n実際の場所・種・年代・権利は人間の確認が必要です。模擬結果は収集実績ではありません。\n\n' + '\n'.join(project['logs'])
    summary += '\n\n## シーン別の実素材検索結果\n\n|シーン|候補|動画|写真|動画率|一般映像|確認済み高関連度|実API応答|キャッシュ|不足理由|\n|---|---|---|---|---|---|---|---|---|---|\n'
    for row in scene_metrics(project):
        summary += '|'+ '|'.join(str(row[k]).replace('|','/') for k in ('scene_id','candidates','videos','photos','video_ratio','general','confirmed_relevance','live_requests','cached_requests','reason'))+'|\n'
    summary += '\n模擬検索の結果は scene_metrics_mock.csv に分離しています。実API接続確認の結果はアプリ内の設定欄と data/connection_check.json で確認できます。\n'
    (target / 'summary_report.md').write_text(summary, encoding='utf-8')
    esc = html.escape
    cards = []
    for s in scenes:
        cards.append(f'<section><h2>シーン{s["id"]} {esc(s["chapter"])}</h2><p>{esc(s["text"])}</p>')
        for a in (x for x in assets if x['scene_id'] == s['id']):
            url = a['page_url'] if a['page_url'].startswith('https://') else '#'
            cards.append(f'<article><a rel="noreferrer" href="{esc(url, quote=True)}">{esc(a["title"])}</a> | {esc(a["type"])} | {esc(a["decision"])} | 権利{esc(a["risk"])}<p>{esc(a["relevance_reason"])}</p></article>')
        cards.append('</section>')
    (target / 'review.html').write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><title>素材確認</title><style>body{max-width:1100px;margin:40px auto;font:16px sans-serif;background:#eef2ed}section,article{background:white;padding:20px;margin:12px;border-radius:10px}p{white-space:pre-wrap}</style><h1>地球の観察録 — 素材確認スナップショット</h1><p>編集はアプリで行ってください。模擬データはタイトルに明示しています。</p>' + ''.join(cards) + '</html>', encoding='utf-8')
    for a in adopted:
        if a.get('downloaded') and Path(a['downloaded']).is_file():
            folder = target / f'scene_{a["scene_id"]:03d}'
            folder.mkdir(exist_ok=True)
            shutil.copy2(a['downloaded'], folder / Path(a['downloaded']).name)
    for diagram in project.get('diagrams', []):
        if Path(diagram['path']).is_file():
            folder = target / f'scene_{diagram["scene_id"]:03d}'
            folder.mkdir(exist_ok=True)
            shutil.copy2(diagram['path'], folder / Path(diagram['path']).name)
    atomic_json(target / 'project_snapshot.json', project)
    return target
