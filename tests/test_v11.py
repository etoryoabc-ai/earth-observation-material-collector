"""No live requests or credentials. Fixed API responses are not live-search evidence."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from collector.core import analyze,new_project,Store
from collector.connectors import JsonHTTP,Pexels,Pixabay,APIError,RateLimited,base,Mock
from collector.search import run_search,queries,scene_metrics,screen
from collector.settings import public_settings,save_settings
from collector.export import export_project

class Response:
    status=200
    headers={}
    def __init__(self,data):self.stream=io.BytesIO(json.dumps(data).encode())
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,*args):return self.stream.read(*args)

class HTTPTests(unittest.TestCase):
    def test_authenticated_real_transport_and_separate_cache_provenance(self):
        # The HTTP transport is mocked: validates requests, not actual API access.
        payload={'videos':[{'id':123,'url':'https://www.pexels.com/video/sea-otter-123/','video_files':[{'file_type':'video/mp4','width':1920,'height':1080,'link':'https://videos.pexels.com/123.mp4'}]}]}
        with tempfile.TemporaryDirectory() as tmp,patch('collector.connectors.urlopen',side_effect=lambda *a,**k:Response(payload)) as send:
            http=JsonHTTP(tmp);p=Pexels(http,'test-secret')
            found=p.search('sea otter','video')
            req=send.call_args.args[0]
            self.assertEqual(req.get_header('Authorization'),'test-secret')
            self.assertIn('/v1/videos/search?',req.full_url)
            self.assertEqual(http.last_info['origin'],'api_network')
            self.assertIn('sea otter',found[0]['title'])
            p.search('sea otter','video')
            self.assertEqual(send.call_count,1)
            self.assertEqual(http.last_info['origin'],'api_cache')
            for path in Path(tmp).glob('*.json'):
                self.assertNotIn('test-secret',path.read_text())
    def test_pixabay_language_photo_filter_and_free_license(self):
        with tempfile.TemporaryDirectory() as tmp,patch('collector.connectors.urlopen',side_effect=lambda *a,**k:Response({'hits':[{'id':7,'pageURL':'https://pixabay.com/photos/otter-7','tags':'sea otter'}]})) as send:
            a=Pixabay(JsonHTTP(tmp),'test-secret').search('ラッコ','photo')[0]
            url=send.call_args.args[0].full_url
            self.assertIn('lang=ja',url);self.assertIn('image_type=photo',url)
            self.assertEqual(a['commercial'],'要確認')
            self.assertIn('商用利用可',a['commercial_policy'])
            self.assertTrue(a['free_only']);self.assertEqual(a['risk'],'D')
    def test_429_persisted_cooldown_and_secret_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            err=HTTPError('https://pixabay.com/api/?key=secret',429,'error',{'Retry-After':'120'},None)
            with patch('collector.connectors.urlopen',side_effect=err) as send:
                with self.assertRaises(RateLimited) as ctx:JsonHTTP(tmp).get('https://pixabay.com/api/',{'key':'secret'})
                self.assertNotIn('secret',str(ctx.exception))
                with self.assertRaises(RateLimited):JsonHTTP(tmp).get('https://pixabay.com/api/',{'key':'secret'})
                self.assertEqual(send.call_count,1)
    def test_auth_error_no_url_or_key_disclosure(self):
        with tempfile.TemporaryDirectory() as tmp,patch('collector.connectors.urlopen',side_effect=HTTPError('https://pixabay.com/api/?key=secret',403,'secret',{},None)):
            with self.assertRaises(APIError) as ctx:JsonHTTP(tmp).get('https://pixabay.com/api/',{'key':'secret'})
            self.assertEqual(ctx.exception.code,'auth');self.assertNotIn('secret',str(ctx.exception))
    def test_no_paid_or_arbitrary_host(self):
        with tempfile.TemporaryDirectory() as tmp,patch('collector.connectors.urlopen') as send:
            with self.assertRaises(APIError):JsonHTTP(tmp).get('https://paid.example/api/')
            send.assert_not_called()

class SearchAndAnalysisTests(unittest.TestCase):
    def test_english_fallback_multi_subject_and_later_page(self):
        class Sparse:
            name='Pexels'
            def __init__(self):self.calls=[]
            def search(self,q,kind,page):
                self.calls.append((q,kind,page))
                if not q.isascii():return []
                return [base('Pexels',f'{q}-{kind}-{page}-{n}',q,'https://www.pexels.com/a',kind) for n in range(3)]
        p=new_project('アダック島のラッコとウニ。','a.md');sparse=Sparse()
        run_search(p,[sparse],lambda _:None)
        self.assertTrue(any(q.isascii() for q,_,_ in sparse.calls))
        self.assertTrue(any(page==2 for _,_,page in sparse.calls))
        self.assertEqual(sparse.calls[0][1],'video')
        self.assertEqual(scene_metrics(p)[0]['videos'],6)
        self.assertEqual(scene_metrics(p)[0]['photos'],3)
        self.assertAlmostEqual(scene_metrics(p)[0]['video_ratio'],66.7)
    def test_query_400_does_not_disable_provider_for_english(self):
        class QueryError:
            name='Pexels'
            def search(self,q,kind,page):
                if not q.isascii():raise APIError('bad query','query')
                return [base('Pexels',f'{q}-{kind}-{page}-{n}',q,'https://www.pexels.com/a',kind) for n in range(3)]
        p=new_project('ラッコ。','a.md');run_search(p,[QueryError()],lambda _:None)
        self.assertTrue(p['assets']);self.assertTrue(any(x.get('error_code')=='query' for x in p['attempts'].values()))
    def test_rejected_candidates_can_be_replaced(self):
        class Stock:
            name='Pexels'
            def search(self,q,kind,page):
                return [base('Pexels',f'{q}-{kind}-{page}-{n}',q,'https://www.pexels.com/a',kind) for n in range(12)]
        p=new_project('ラッコ。','a.md');run_search(p,[Stock()],lambda _:None)
        rejected=next(a for a in p['assets'] if a['type']=='video');rejected['decision']='reject'
        p['search_revision']=1;run_search(p,[Stock()],lambda _:None)
        self.assertEqual(scene_metrics(p)[0]['videos'],6)
        self.assertEqual(rejected['decision'],'reject')
    def test_metadata_wrong_species_not_used_to_fill_count(self):
        a=base('Pexels','1','river otter','https://www.pexels.com/a','video')
        self.assertFalse(screen(a,analyze('ラッコ。')[0],'英語'))
        self.assertEqual(a['match_status'],'excluded')
    def test_general_does_not_inherit_place_year(self):
        a=base('Pexels','1','sea otter','https://www.pexels.com/a','video')
        screen(a,analyze('アダック島の1987年のラッコ。')[0],'一般映像')
        self.assertIn('未確認',a['place_certainty']);self.assertIn('要確認',a['year_certainty'])
        self.assertNotEqual(a['relevance'],'高')
    def test_separate_years_hypothesis_and_regions_with_evidence(self):
        text='# 第1章\nアダック島で1987年に海底を調査しました。1997年の調査ではケルプが減少しました。シャチによるラッコの捕食は仮説です。\n\n# 第2章\nバンクーバー島ではラッコの再定着を記録しました。サン・ニコラス島は別地域です。'
        scenes=analyze(text)
        self.assertEqual(''.join(s['text'] for s in scenes),text)
        first=next(s for s in scenes if '1987' in s['text']);second=next(s for s in scenes if '1997' in s['text'])
        self.assertNotEqual(first['id'],second['id'])
        for s in scenes:
            for x in s['statements']:
                self.assertEqual(text[x['source_start']:x['source_end']],x['text'])
            if 'サン・ニコラス島' in s['text']:
                self.assertEqual([x['ja'] for x in s['places']],['サンニコラス島'])
    def test_english_scientific_and_no_invented_whale(self):
        s=analyze('Adak Island: Enhydra lutris and killer whale.')[0]
        self.assertEqual({x['ja'] for x in s['animals']},{'ラッコ','シャチ'})
        self.assertEqual(s['places'][0]['ja'],'アダック島')
    def test_real_and_mock_reports_separated(self):
        p=new_project('ラッコ。','sample.md');p['mock']=True
        run_search(p,[Mock()],lambda _:None)
        with tempfile.TemporaryDirectory() as tmp:
            target=export_project(p,tmp)
            self.assertEqual(scene_metrics(p)[0]['candidates'],0)
            self.assertEqual(scene_metrics(p,True)[0]['candidates'],9)
            report=json.loads((target/'validation_report.json').read_text())
            self.assertEqual(report['real'][0]['live_requests'],0)
            self.assertTrue((target/'scene_metrics_mock.csv').exists())

class SettingsTests(unittest.TestCase):
    def test_keys_private_and_blank_preserves_existing(self):
        with tempfile.TemporaryDirectory() as tmp,patch('collector.settings.SETTINGS',Path(tmp)/'settings.local.json'),patch.dict('os.environ',{},clear=True):
            result=save_settings({'PEXELS_API_KEY':'test-secret','providers':['Pexels'],'budget':30})
            self.assertTrue(result['pexels']);self.assertNotIn('test-secret',json.dumps(result))
            save_settings({'providers':['Pexels'],'budget':30})
            self.assertTrue(public_settings()['pexels'])
