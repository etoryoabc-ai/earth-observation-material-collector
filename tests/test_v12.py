import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from collector.core import new_project,Store
from collector.scenes import group,validate,edit_structure
from collector.settings import public_settings,save_settings,provider_catalog
from collector.connectors import base,Mock,APIError
from collector.search import run_search
from collector.status import overview

class SceneGroupingTests(unittest.TestCase):
    def test_no_heading_only_scenes_and_lossless(self):
        source='# 動画タイトル\r\n\r\n導入\r\nアリューシャン列島の位置を紹介します。海は冷たい。\r\n\r\n第1章 海の森\r\nアダック島にケルプがあります。森に魚が暮らします。\r\n結び\r\n生命のつながりです。🌍'
        units,scenes=group(source)
        self.assertTrue(validate(source,scenes)['lossless'])
        self.assertTrue(all(s['searchable'] for s in scenes))
        self.assertEqual(''.join(u['text'] for u in units),source)
        self.assertTrue(all(any(u['kind']=='body' and u['start']>=s['start'] and u['end']<=s['end'] for u in units) for s in scenes))
        self.assertEqual(scenes[0]['start'],0)
    def test_150_repeated_sentences_are_not_150_scenes(self):
        source='# タイトル\n導入\n'+('ラッコが海に暮らします。体を温めます。\n'*75)+'第1章\nケルプは海の森です。森の中には魚がいます。'
        units,scenes=group(source)
        self.assertGreater(len([u for u in units if u['kind']=='body']),150)
        self.assertLess(len(scenes),10)
        self.assertTrue(validate(source,scenes)['lossless'])
    def test_comparison_observation_and_hypothesis_separate_records(self):
        source='アダック島で1987年に調査した。1997年に再調査した。\nシャチによる捕食が観察された。その影響は仮説とされる。\nバンクーバー島で再導入した。サンニコラス島は別の事例である。'
        _,scenes=group(source)
        records=[x for s in scenes for x in s['statements']]
        a=next(x for x in records if '観察' in x['text']);b=next(x for x in records if '仮説' in x['text'])
        self.assertNotIn('仮説',a['status']);self.assertIn('仮説',b['status'])
        v=next(s for s in scenes if 'バンクーバー島' in s['text']);n=next(s for s in scenes if 'サンニコラス島' in s['text'])
        self.assertNotEqual(v['id'],n['id'])
        for s in scenes:
            for st in s['statements']:self.assertEqual(source[st['source_start']:st['source_end']],st['text'])
    def test_merge_split_preserves_adopted_and_original_files(self):
        p=new_project('第1章\nラッコは海で暮らす。毛皮は厚い。\n第2章\nバンクーバー島で再導入した。','a.md')
        a=base('test','1','asset','https://example.org','video');a.update(scene_id=2,id='asset',decision='adopt',downloaded='original-path.mp4',material_number=1)
        p['assets']=[a]
        edit_structure(p,'merge',1)
        self.assertEqual(len(p['scenes']),1);self.assertEqual(a['scene_id'],1);self.assertEqual(a['downloaded'],'original-path.mp4');self.assertEqual(a['decision'],'adopt')
        edit_structure(p,'split',1,5)
        self.assertEqual(len(p['scenes']),2);self.assertEqual(len(p['assets']),1);self.assertIn('分割',a['assignment_note'])
        validate(p['source'],p['scenes'])
    def test_store_resume_grouped_structure(self):
        p=new_project('導入\nラッコの生態です。ウニを食べます。','a.md')
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);store.save(p);loaded=store.load(p['id'])
            self.assertEqual(loaded['text_units'],p['text_units']);self.assertEqual(loaded['source'],p['source'])

class KeyFreeTests(unittest.TestCase):
    def test_keyfree_defaults_and_old_default_migration(self):
        with tempfile.TemporaryDirectory() as tmp,patch('collector.settings.SETTINGS',Path(tmp)/'settings.local.json'),patch.dict('os.environ',{},clear=True):
            conf=public_settings();self.assertEqual(conf['providers'],['Wikimedia Commons','NASA'])
            Path(tmp,'settings.local.json').write_text(json.dumps({'SEARCH_PROVIDERS':['Pexels','Pixabay']}))
            self.assertEqual(public_settings()['providers'],['Wikimedia Commons','NASA'])
    def test_new_keys_automatically_enable_stock_without_leaking(self):
        with tempfile.TemporaryDirectory() as tmp,patch('collector.settings.SETTINGS',Path(tmp)/'settings.local.json'),patch.dict('os.environ',{},clear=True):
            result=save_settings({'PEXELS_API_KEY':'private-key','providers':['Wikimedia Commons','NASA']})
            self.assertIn('Pexels',result['providers']);self.assertNotIn('private-key',json.dumps(result))
    def test_disabled_all_is_distinct_and_unsupported_visible(self):
        with tempfile.TemporaryDirectory() as tmp,patch('collector.settings.SETTINGS',Path(tmp)/'settings.local.json'),patch.dict('os.environ',{},clear=True):
            save_settings({'providers':[]})
            catalog=provider_catalog();self.assertFalse(any(c['enabled'] for c in catalog))
            self.assertTrue(any(c['name']=='NOAA' and c['state']=='検索先未対応' for c in catalog))

class SearchStateTests(unittest.TestCase):
    def test_all_auth_errors_never_report_success(self):
        class Failed:
            name='Pexels'
            def search(self,*args):raise APIError('キー未設定','missing_key')
        p=new_project('ラッコ。','a.md');run_search(p,[Failed()],lambda _:None)
        self.assertEqual(p['search_outcome'],'failed');self.assertIn('検索失敗',p['search_status']);self.assertNotIn('検索完了',p['search_status'])
        self.assertIn('APIキー未設定',p['search_status'])
    def test_success_zero_not_failed_or_collection_success(self):
        class Empty:
            name='NASA'
            def search(self,*args):return []
        p=new_project('ラッコ。','a.md');run_search(p,[Empty()],lambda _:None)
        self.assertEqual(p['search_outcome'],'zero');self.assertIn('候補0件',p['search_status']);self.assertEqual(overview(p)['candidates'],0)
    def test_partial_success_reports_error_and_counts(self):
        class Failed:
            name='NASA'
            def search(self,*args):raise APIError('接続失敗','network')
        p=new_project('ラッコ。','a.md');p['mock']=True;run_search(p,[Failed(),Mock()],lambda _:None)
        self.assertEqual(p['search_outcome'],'partial');self.assertIn('一部のみ',p['search_status']);self.assertEqual(overview(p)['candidates'],9)
    def test_no_provider_cannot_report_completion_success(self):
        p=new_project('ラッコ。','a.md');run_search(p,[],lambda _:None)
        self.assertEqual(p['search_outcome'],'failed')

class MetadataAndRightsTests(unittest.TestCase):
    def test_heading_entities_do_not_leak_into_body(self):
        _,scenes=group('# シャチとサンニコラス島という動画タイトル\n導入\nアダック島のラッコを観察する。')
        self.assertEqual(len(scenes),1)
        self.assertEqual([x['ja'] for x in scenes[0]['animals']],['ラッコ'])
        self.assertEqual([x['ja'] for x in scenes[0]['places']],['アダック島'])
    def test_context_inference_never_becomes_confirmed_place(self):
        units,scenes=group('アダック島を訪れた。この島では海を見た。')
        second=[u for u in units if u['kind']=='body'][1]
        self.assertFalse(second['analysis']['places'])
        self.assertEqual(second['context_inferences'][0]['certainty'],'推定・要確認')
    def test_metadata_image_video_type_and_link_only(self):
        from collector.connectors import Commons,NASA
        class HTTP:
            def get(self,*args):
                return {'query':{'pages':{'1':{'pageid':1,'title':'File:Sea otter.webm','imageinfo':[{'mime':'video/webm','url':'https://upload.wikimedia.org/otter.webm','descriptionurl':'https://commons.wikimedia.org/wiki/File:Sea_otter.webm','metadata':[{'name':'duration','value':10}]}]}}}}
        a=Commons(HTTP()).search('sea otter','video')[0]
        self.assertEqual(a['duration'],10);self.assertEqual(a['access_mode'],'download');self.assertEqual(a['risk'],'D')
        class NASAHTTP:
            def get(self,*args):return {'collection':{'items':[{'data':[{'nasa_id':'abc','title':'Ocean'}]}]}}
        n=NASA(NASAHTTP()).search('ocean','video')[0]
        self.assertEqual(n['access_mode'],'link_only');self.assertFalse(n['human_checked'])
    def test_http200_error_is_not_zero_result_success(self):
        from collector.connectors import JsonHTTP
        import io
        class Response:
            status=200;headers={}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'{"error":{"code":"badquery"}}'
        with tempfile.TemporaryDirectory() as tmp,patch('collector.connectors.urlopen',return_value=Response()):
            with self.assertRaises(APIError) as ctx:JsonHTTP(tmp).get('https://commons.wikimedia.org/w/api.php')
            self.assertEqual(ctx.exception.code,'api')
    def test_identical_signed_download_url_deduplicates(self):
        from collector.search import fingerprint
        a=base('a','1','one','https://example.org','video');b=base('b','2','two','https://example.org','video')
        a['download_url']='https://cdn.example.org/movie.mp4?token=one';b['download_url']='https://cdn.example.org/movie.mp4?token=two'
        self.assertEqual(fingerprint(a),fingerprint(b))
    def test_number_collisions_after_merge_are_resolved(self):
        p=new_project('第1章\nラッコ。\n第2章\nウニ。','a.md')
        for sid in (1,2):
            a=base('test',str(sid),'asset','https://example.org','video');a.update(scene_id=sid,id=str(sid),material_number=1,decision='adopt');p['assets'].append(a)
        edit_structure(p,'merge',1)
        self.assertEqual(len({a['material_number'] for a in p['assets']}),2)

    def test_narrative_prefix_is_not_heading_and_subheadings_not_chapters(self):
        source='# 世界を結びつける森\n導入\n結びつきが重要です。導入された動物を説明します。\n第1章\nラッコの生態です。\n### 小見出し\nウニを食べます。'
        units,scenes=group(source)
        body=[u for u in units if u['kind']=='body']
        self.assertTrue(any('結びつき' in u['text'] for u in body))
        self.assertTrue(any('導入された' in u['text'] for u in body))
        self.assertEqual(set(u['chapter'] for u in body),{'導入','第1章'})
        validate(source,scenes)
