import csv
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from collector.core import analyze, new_project, Store, decode_script
from collector.connectors import base, Pexels, Pixabay, Commons, NASA, Mock, RateLimited
from collector.search import run_search, queries, shortages
from collector.downloads import permitted, download, check_url
from collector.export import export_project, csv_write
from collector.diagrams import relation_svg
from collector import server

SAMPLE = '# 第1章\r\n\r\nアダック島のラッコ。1987年の調査。1997年の調査。シャチ捕食の仮説。\r\n\r\n## 第2章\r\nバンクーバー島。\n\nサンニコラス島。\n🌍\n'

class AnalysisTests(unittest.TestCase):
    def test_lossless_offsets(self):
        for text in (SAMPLE, '前文\n\n# 第一章\n本文\n', '\n\n# 見出し\n\n', '最後の改行なし', '# a\n# b\n'):
            scenes = analyze(text)
            self.assertEqual(''.join(s['text'] for s in scenes), text)
            for s in scenes:
                self.assertEqual(text[s['start']:s['end']], s['text'])
    def test_location_year_hypothesis_separation(self):
        scenes = analyze(SAMPLE)
        for s in scenes:
            if 'サンニコラス島' in s['text']:
                self.assertEqual([p['ja'] for p in s['places']], ['サンニコラス島'])
            if '仮説' in s['text']:
                self.assertIn('仮説', s['claim_type'])
        self.assertGreater(len(scenes), 2)
    def test_unknown_no_invention(self):
        s = analyze('未知の島の生き物。')[0]
        self.assertFalse(s['animals']); self.assertFalse(s['places'])
        self.assertIn('要確認', s['fact_check'])
    def test_encoding(self):
        self.assertEqual(decode_script('ラッコ'.encode('cp932')), 'ラッコ')
        self.assertEqual(decode_script(b'\xef\xbb\xbfabc'), 'abc')
        with self.assertRaises(ValueError):
            analyze('   ')
    def test_queries_do_not_substitute_places(self):
        s = analyze('アダック島のラッコ。')[0]
        q = str(queries(s))
        self.assertIn('Adak Island', q); self.assertIn('Enhydra lutris', q)
        self.assertNotIn('Vancouver', q)

class SearchTests(unittest.TestCase):
    def test_mock_resume_dedupe_and_ratio(self):
        p = new_project('ラッコの海。', 'test.md'); p['mock'] = True
        calls = []
        class Tracking(Mock):
            def search(self, q, k, page=1):
                calls.append(k)
                return super().search(q, k, page)
        run_search(p, [Tracking()], lambda _: None)
        count = len(p['assets'])
        self.assertEqual(count, 9)
        self.assertEqual(calls[0], 'video')
        self.assertEqual(sum(a['type']=='video' for a in p['assets']), 6)
        run_search(p, [Tracking()], lambda _: None)
        self.assertEqual(len(p['assets']), count)
        self.assertEqual(shortages(p)[0]['candidates'], 0)
    def test_rate_limit_persists_retries_and_peers(self):
        p = new_project('ラッコ。', 'test.md'); p['mock'] = True
        class Limited:
            name = 'limited'
            def search(self, *args):
                raise RateLimited()
        run_search(p, [Limited(), Mock()], lambda _: None)
        self.assertTrue(any(v['status']=='rate_limited' for v in p['attempts'].values()))
        self.assertTrue(p['assets'])
    def test_stop(self):
        p = new_project('ラッコ。', 'a.md')
        run_search(p, [Mock()], lambda _: None, lambda: True)
        self.assertEqual(p['search_status'], '一時停止')
    def test_identical_results_not_inflated(self):
        class Same:
            name = 'same'
            def search(self, q, kind, page):
                return [base('same','1','same','https://example.com','video')]*5
        p = new_project('ラッコ。', 'a.md')
        run_search(p, [Same()], lambda _: None)
        self.assertEqual(len(p['assets']), 1)

class ConnectorTests(unittest.TestCase):
    class HTTP:
        def __init__(self, data): self.data=data; self.calls=[]
        def get(self, *args): self.calls.append(args); return self.data
    def test_pexels_one_video_multiple_resolutions(self):
        http=self.HTTP({'videos':[{'id':1,'url':'https://www.pexels.com/video/1','video_files':[{'file_type':'video/mp4','width':1920,'height':1080,'link':'https://videos.pexels.com/1.mp4'},{'file_type':'video/mp4','width':3840,'height':2160,'link':'https://videos.pexels.com/4k.mp4'}]}]})
        items=Pexels(http,'fake').search('kelp','video')
        self.assertEqual(len(items),1); self.assertEqual(items[0]['height'],2160)
        self.assertIn('/v1/videos/search',http.calls[0][0]); self.assertEqual(items[0]['risk'],'D')
    def test_pixabay_shape(self):
        http=self.HTTP({'hits':[{'id':3,'pageURL':'https://pixabay.com/videos/3','videos':{'large':{'url':'https://cdn.pixabay.com/3.mp4','width':1920,'height':1080,'size':123}}}]})
        a=Pixabay(http,'fake').search('kelp','video')[0]
        self.assertEqual(a['size'],123); self.assertEqual(a['risk'],'D')
    def test_commons_license(self):
        http=self.HTTP({'query':{'pages':{'1':{'pageid':1,'title':'File:otter.jpg','imageinfo':[{'mime':'image/jpeg','url':'https://upload.wikimedia.org/otter.jpg','extmetadata':{'LicenseShortName':{'value':'CC BY-SA 4.0'},'LicenseUrl':{'value':'https://creativecommons.org/licenses/by-sa/4.0/'}}}]}}}})
        a=Commons(http).search('otter','photo')[0]
        self.assertEqual(a['risk'],'B'); self.assertFalse(a['human_checked'])
    def test_nasa_never_assumes_public_domain(self):
        http=self.HTTP({'collection':{'items':[{'data':[{'nasa_id':'123','title':'Earth'}]}]}})
        a=NASA(http).search('Earth','photo')[0]
        self.assertEqual(a['risk'],'D'); self.assertFalse(a['download_url'])

class SafetyExportTests(unittest.TestCase):
    def test_gate(self):
        a=base('MOCK','1','title','https://example.com','video'); a['decision']='adopt'
        for risk in ('A','B','C','D','E'):
            a['risk']=risk
            self.assertFalse(permitted(a))
        a.update(risk='B',human_checked=True,commercial='可',license_name='CC BY',license_url='https://creativecommons.org',checked_at='today',evidence='checked')
        self.assertTrue(permitted(a))
        for risk in ('C','D','E'):
            a['risk']=risk; self.assertFalse(permitted(a))
        a.update(risk='A',mock=True); self.assertFalse(permitted(a))
        with self.assertRaises(ValueError): download(a, '/tmp/unreachable')
    def test_url_ssrf(self):
        for u in ('http://upload.wikimedia.org/a', 'https://127.0.0.1/a', 'https://evil.com/a', 'https://upload.wikimedia.org:123/a'):
            with self.assertRaises(ValueError): check_url(u,'Wikimedia Commons')
        with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): check_url('https://upload.wikimedia.org/a','Wikimedia Commons')
    def test_persistence_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp); p=new_project(SAMPLE,'a.md'); store.save(p)
            self.assertEqual(store.load(p['id']),p)
            target=export_project(p,Path(tmp)/'out')
            for name in ('scene_list.csv','asset_candidates.csv','review.html','download_manifest.csv','license_report.csv','sources.md','missing_assets.csv','slide_requests.csv','summary_report.md'):
                self.assertTrue((target/name).exists(),name)
            self.assertTrue((target/'scene_list.csv').read_bytes().startswith(b'\xef\xbb\xbf'))
            self.assertNotEqual(export_project(p,Path(tmp)/'out'),target)
    def test_csv_formula(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'a.csv'; csv_write(path,[{'title':'=HYPERLINK("x")'}])
            self.assertIn("'=HYPERLINK", path.read_text(encoding='utf-8-sig'))
    def test_diagram_requires_verified_evidence_and_escapes(self):
        with self.assertRaises(ValueError): relation_svg(['a','b'],[],'',True)
        with self.assertRaises(ValueError): relation_svg(['a','b'],[],'source',False)
        svg=relation_svg(['<script>','b'],[[0,1,'関係']],'source',True)
        self.assertIn('&lt;script&gt;',svg); self.assertNotIn('<script>',svg)

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); server.STORE=Store(cls.temp.name)
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.http.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.temp.cleanup()
    def post(self,route,data,token=server.TOKEN):
        with urlopen(Request(self.url+'/api/'+route,data=json.dumps(data).encode(),headers={'X-App-Token':token,'Content-Type':'application/json'})) as r:
            return json.load(r)
    def test_auth_and_split_roundtrip(self):
        with self.assertRaises(HTTPError) as ctx:self.post('list',{},'wrong')
        self.assertEqual(ctx.exception.code,403)
        p=self.post('create',{'name':'test.txt','source':'ラッコとウニ。'})
        self.post('split',{'project_id':p['id'],'scene_id':1,'offset':3})
        state=self.post('state',{'project_id':p['id']})['project']
        self.assertEqual(''.join(s['text'] for s in state['scenes']),p['source'])
        self.assertEqual(len(state['scenes']),2)
    def test_cannot_adopt_unverified(self):
        p=new_project('原稿','a.md');a=base('test','1','x','https://example.com','photo');a.update(id='one',scene_id=1);p['assets']=[a];server.STORE.save(p)
        with self.assertRaises(HTTPError):self.post('asset',{'project_id':p['id'],'asset_id':'one','decision':'adopt'})
        self.assertEqual(server.STORE.load(p['id'])['assets'][0]['decision'],'hold')
    def test_home_and_unknown_route(self):
        with urlopen(self.url) as r:
            text=r.read().decode();self.assertIn('地球の観察録',text);self.assertNotIn('__TOKEN__',text)
        with self.assertRaises(HTTPError):urlopen(self.url+'/../../settings.local.json')

if __name__=='__main__':unittest.main()
