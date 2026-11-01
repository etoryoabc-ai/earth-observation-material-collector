import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from collector.downloads import download
from collector.core import atomic_json
from collector.connectors import base

class DownloadTests(unittest.TestCase):
    def asset(self):
        a=base('Pexels','1','title','https://www.pexels.com/video/1','video')
        a.update(id='x',scene_id=1,material_number=1,risk='A',human_checked=True,commercial='可',license_name='Pexels',license_url='https://www.pexels.com/license/',checked_at='today',evidence='verified',decision='adopt',format='mp4',download_url='https://videos.pexels.com/1.mp4')
        return a
    def test_range_resume_and_no_overwrite(self):
        payload=b'abcdef'; calls=[]
        class Response:
            status=206
            headers={'Content-Type':'video/mp4','Content-Length':'3','Content-Range':'bytes 3-5/6','ETag':'"v1"'}
            def __init__(self): self.sent=False
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,size):
                if self.sent:return b''
                self.sent=True;return payload[3:]
        class Opener:
            def open(self,request,timeout):calls.append(request);return Response()
        with tempfile.TemporaryDirectory() as tmp:
            a=self.asset();folder=Path(tmp)/'scene_001';folder.mkdir()
            part=folder/'scene_001_video_001.mp4.part';part.write_bytes(payload[:3])
            atomic_json(part.with_suffix('.part.json'),dict(url=a['download_url'],validator='"v1"'))
            with patch('collector.downloads.check_url'),patch('collector.downloads.build_opener',return_value=Opener()):
                dest=Path(download(a,tmp))
                self.assertEqual(dest.read_bytes(),payload)
                self.assertEqual(calls[0].get_header('Range'),'bytes=3-')
                self.assertEqual(download(a,tmp),str(dest))
                dest.write_bytes(b'other')
                with self.assertRaises(ValueError): download(a,tmp)
    def test_ignored_range_restarts_full_file(self):
        class Response:
            status=200
            headers={'Content-Type':'video/mp4','Content-Length':'3','ETag':'"new"'}
            def __init__(self):self.sent=False
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,size):
                if self.sent:return b''
                self.sent=True;return b'new'
        class Opener:
            def open(self,*args,**kwargs):return Response()
        with tempfile.TemporaryDirectory() as tmp:
            a=self.asset();a['download_etag']='"old"'
            folder=Path(tmp)/'scene_001';folder.mkdir();(folder/'scene_001_video_001.mp4.part').write_bytes(b'old')
            with patch('collector.downloads.check_url'),patch('collector.downloads.build_opener',return_value=Opener()):
                self.assertEqual(Path(download(a,tmp)).read_bytes(),b'new')
