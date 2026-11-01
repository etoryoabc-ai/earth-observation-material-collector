import argparse
import json
import os
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .core import Store, new_project, now
from .connectors import providers, MANUAL_SOURCES
from .downloads import permitted, download
from .search import run_search, shortages, scene_metrics
from .export import export_project
from .settings import public_settings

ROOT = Path(__file__).resolve().parent.parent
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
BUSY = set()
STOP = set()
STORE = None
DIAGNOSTICS = {"running": False, "results": []}


def safe_project(project_id):
    if project_id in BUSY:
        raise ValueError('検索・保存中です。一時停止してから編集してください。')
    return STORE.load(project_id)


def search_job(project_id, mock):
    try:
        with LOCK:
            p = STORE.load(project_id)
            if p['assets'] and p['mock'] != mock:
                raise ValueError('模擬と実検索は別プロジェクトで行ってください。')
            p['mock'] = mock
        def save(data):
            with LOCK:
                STORE.save(data)
        run_search(p, providers(mock, cache_dir=STORE.root / "api_cache"), save, lambda: project_id in STOP)
    except Exception:
        with LOCK:
            p = STORE.load(project_id)
            p['search_status'] = '処理エラー。設定を確認して再開してください。'
            STORE.save(p)
    finally:
        with LOCK:
            BUSY.discard(project_id)
            STOP.discard(project_id)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, data, status=200, mime='application/json; charset=utf-8'):
        body = json.dumps(data, ensure_ascii=False).encode() if not isinstance(data, bytes) else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def do_GET(self):
        if not self.host_ok():
            return self.respond({'error': 'Host rejected'}, 403)
        path = urlsplit(self.path).path
        if path == '/':
            page = (ROOT / 'collector' / 'index.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN)
            return self.respond(page.encode(), mime='text/html; charset=utf-8')
        if path == '/app.js':
            return self.respond((ROOT / 'collector' / 'app.js').read_bytes(), mime='text/javascript; charset=utf-8')
        return self.respond({'error': 'Not found'}, 404)

    def do_POST(self):
        if not self.host_ok() or self.headers.get('X-App-Token') != TOKEN:
            return self.respond({'error': '操作の認証に失敗しました。画面を再読み込みしてください。'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8*1024*1024:
                raise ValueError('入力サイズが不正です（上限8 MiB）。')
            data = json.loads(self.rfile.read(length))
            with LOCK:
                result = self.action(urlsplit(self.path).path, data)
            self.respond(result)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            self.respond({'error': str(exc)}, 400)
        except Exception:
            self.respond({'error': '処理に失敗しました。ファイルの権限・設定を確認してください。'}, 500)

    def action(self, route, d):
        if route == '/api/list':
            return dict(projects=STORE.list(), sources=MANUAL_SOURCES,
                        keys=public_settings(),diagnostics=DIAGNOSTICS)
        if route == '/api/settings':
            if BUSY or DIAGNOSTICS['running']:
                raise ValueError('検索・接続確認が完了してから設定を変更してください。')
            from .settings import save_settings
            return dict(message='ローカル設定を保存しました。キー入力欄は消去されます。', keys=save_settings(d))
        if route == '/api/check':
            if DIAGNOSTICS['running'] or BUSY:
                raise ValueError('現在の処理が完了してから接続確認してください。')
            DIAGNOSTICS.update(running=True, results=[])
            def check():
                from .connectors import APIError
                results=[]
                try:
                    for connector in providers(False, selected=['Pexels','Pixabay'],cache_dir=STORE.root/'api_cache'):
                        for kind in ('video','photo'):
                            try:
                                found=connector.search('sea otter',kind,1)
                                info=connector.http.last_info
                                row=dict(provider=connector.name,kind=kind,status='success',count=len(found),origin=info.get('origin','unverified'),at=now())
                            except APIError as exc:
                                row=dict(provider=connector.name,kind=kind,status='blocked',error_code=exc.code,message=str(exc),at=now())
                            except Exception:
                                row=dict(provider=connector.name,kind=kind,status='error',message='接続確認中の応答エラー',at=now())
                            results.append(row)
                            with LOCK: DIAGNOSTICS['results']=list(results)
                finally:
                    with LOCK:
                        DIAGNOSTICS['running']=False
                        from .core import atomic_json
                        atomic_json(STORE.root/'connection_check.json',DIAGNOSTICS)
            threading.Thread(target=check,daemon=True).start()
            return {'message':'Pexels・Pixabayの動画/写真API接続を確認中です。'}
        if route == '/api/create':
            if not str(d.get('name', '')).lower().endswith(('.txt', '.md', '.markdown')):
                raise ValueError('TXT / Markdown の原稿を指定してください。')
            p = new_project(d['source'], d['name'])
            STORE.save(p)
            return p
        pid = d['project_id']
        if route == '/api/state':
            p = STORE.load(pid)
            return dict(project=p, busy=pid in BUSY, shortages=shortages(p),metrics=scene_metrics(p),mock_metrics=scene_metrics(p,True))
        if route == '/api/stop':
            if pid not in BUSY:
                return {'message':'現在実行中の検索はありません。'}
            STOP.add(pid)
            return {'message': '現在のAPI要求後に停止します。'}
        p = safe_project(pid)
        if route == '/api/search':
            mock = d.get('mock') is True
            if p['assets'] and p['mock'] != mock:
                raise ValueError('実検索と模擬テストは別プロジェクトにしてください。')
            BUSY.add(pid)
            threading.Thread(target=search_job, args=(pid, mock), daemon=True).start()
            return {'message': '検索を開始しました。'}
        if route == '/api/expand':
            sid=int(d.get('scene_id',0))
            if sid and not any(s['id']==sid for s in p['scenes']):raise ValueError('不正なシーン番号です。')
            p['search_revision']=p.get('search_revision',0)+1
            STORE.save(p)
            BUSY.add(pid)
            threading.Thread(target=search_job,args=(pid,p['mock']),daemon=True).start()
            return {'message':'見送り・除外候補を除き、不足分を再検索します。'}
        if route == '/api/scene':
            scene = next(s for s in p['scenes'] if s['id'] == int(d['scene_id']))
            for key in ('summary', 'required_material', 'material_type', 'priority', 'alternatives', 'fact_check', 'slide_request'):
                if key in d:
                    scene[key] = str(d[key])[:12000]
            if 'keywords' in d:
                scene['keywords'] = [str(x)[:120] for x in d['keywords'][:20]]
            if 'english_queries' in d:
                scene['english_queries']=[str(x)[:200] for x in d['english_queries'][:12] if str(x).strip()]
            p['search_revision']=p.get('search_revision',0)+1
        elif route == '/api/split':
            scene = next(s for s in p['scenes'] if s['id'] == int(d['scene_id']))
            if p['assets'] or p['attempts']:
                raise ValueError('手動分割は検索開始前に行ってください。')
            cut = int(d['offset'])
            if not 0 < cut < len(scene['text']):
                raise ValueError('分割位置が原稿の範囲外です。')
            from .core import describe
            index = p['scenes'].index(scene)
            original_end, original_text = scene['end'], scene['text']
            scene.update(end=scene['start']+cut, text=original_text[:cut], **describe(original_text[:cut]))
            tail = dict(id=0, chapter=scene['chapter'], start=scene['end'], end=original_end, text=original_text[cut:], **describe(original_text[cut:]))
            p['scenes'].insert(index+1, tail)
            for i, s in enumerate(p['scenes'], 1):
                s['id'] = i
        elif route == '/api/asset':
            a = next(x for x in p['assets'] if x['id'] == d['asset_id'])
            strings = ('creator', 'institution', 'license_name', 'license_url', 'commercial', 'modification', 'attribution', 'terms', 'evidence', 'risk', 'relevance', 'relevance_reason', 'place_certainty', 'species_certainty', 'year_certainty', 'record_type', 'citation_reason', 'citation_script', 'citation_range')
            # Validate a copy: invalid adoption must not partially modify saved state.
            updated = dict(a)
            for key in strings:
                if key in d:
                    updated[key] = str(d[key])[:12000]
            for key in ('human_checked', 'citation_distinct', 'citation_source', 'citation_main'):
                if key in d:
                    updated[key] = d[key] is True
            if updated['risk'] not in ('A', 'B', 'C', 'D', 'E'):
                raise ValueError('不正な権利区分です。')
            if updated['human_checked']:
                updated['checked_at'] = now()
            decision = d.get('decision', updated['decision'])
            if decision not in ('adopt', 'hold', 'reject'):
                raise ValueError('不正な採用区分です。')
            if decision == 'adopt' and not permitted(updated):
                raise ValueError('A/B区分・商用利用「可」・ライセンス名とURL・確認根拠・人間による確認が必要です。C/D/Eと模擬素材は採用できません。')
            updated['decision'] = decision
            if decision == 'adopt' and not updated.get('material_number'):
                updated['material_number'] = max([x.get('material_number', 0) for x in p['assets'] if x['scene_id'] == a['scene_id']], default=0)+1
            a.update(updated)
        elif route == '/api/diagram':
            from .diagrams import save_diagram
            sid = int(d['scene_id'])
            if not any(s['id'] == sid for s in p['scenes']):
                raise ValueError('不正なシーン番号です。')
            path = save_diagram(STORE.path(pid).parent / 'media', sid, d['labels'], d['edges'], d['evidence'], d.get('verified'))
            p.setdefault('diagrams', []).append(dict(scene_id=sid, path=str(path), evidence=d['evidence'], verified_at=now()))
            STORE.save(p)
            return {'message': f'SVGを保存しました：{path}'}
        elif route == '/api/download':
            BUSY.add(pid)
            def job():
                try:
                    for a in p['assets']:
                        if a['decision'] != 'adopt':
                            continue
                        try:
                            download(a, STORE.path(pid).parent / 'media')
                        except Exception as exc:
                            a['download_error'] = str(exc)
                        with LOCK:
                            STORE.save(p)
                finally:
                    with LOCK:
                        BUSY.discard(pid)
            threading.Thread(target=job, daemon=True).start()
            return {'message': '採用素材を保存中です。'}
        elif route == '/api/export':
            target = export_project(p, STORE.path(pid).parent / 'exports')
            return {'message': f'出力しました：{target}'}
        else:
            raise ValueError('不明な操作です。')
        from .analysis import annotate_offsets
        annotate_offsets(p['scenes'])
        STORE.save(p)
        return {'message': '保存しました。'}


def main():
    global STORE
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    args = parser.parse_args()
    STORE = Store(args.data_dir)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'地球の観察録：http://127.0.0.1:{server.server_port} （終了は Ctrl+C）', flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(f'http://127.0.0.1:{server.server_port}')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
