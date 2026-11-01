"""Actual Windows cmd.exe tests; skipped on Linux, never reported as Windows passes."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent

@unittest.skipUnless(os.name=='nt','Windows cmd.exe is required')
class WindowsBatchTests(unittest.TestCase):
    def run_case(self,app='print("APP_STARTED")\n',missing_python=False,missing_app=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'日本語 空白 & path';root.mkdir()
            shutil.copy2(ROOT/'起動.bat',root/'起動.bat')
            shutil.copy2(ROOT/'launcher.py',root/'launcher.py')
            if not missing_app:(root/'app.py').write_text(app,encoding='utf-8')
            env=os.environ.copy()
            # Exclude Python Launcher: exercises fallback to the exact interpreter
            # supplied by setup-python, independent of preinstalled Python versions.
            env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
            if not missing_python:env['PATH']=str(Path(sys.executable).parent)+';'+env['PATH']
            env['EO_LAUNCHER']=str(root/'起動.bat')
            cmd=f'"{env["COMSPEC"]}" /d /c chcp 932 >nul & call "%EO_LAUNCHER%"'
            r=subprocess.run(cmd,input=b'\r\n',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,cwd=tmp,env=env,timeout=30)
            output=r.stdout.decode('cp932',errors='replace')
            self.assertIn('Press any key to close this window.',output)
            self.assertNotIn('rvorlevel',output)
            return r.returncode,output,list((root/'logs').glob('*.log'))
    def test_japanese_path_cp932_start_and_pause(self):
        code,out,_=self.run_case()
        self.assertEqual(code,0,out);self.assertIn('APP_STARTED',out)
    def test_app_failure_is_nonzero_and_pauses(self):
        code,out,_=self.run_case('raise RuntimeError("TEST_FAILURE")\n')
        self.assertNotEqual(code,0,out);self.assertIn('Application exited with code',out)
    def test_python_missing_pauses(self):
        code,out,_=self.run_case(missing_python=True)
        self.assertNotEqual(code,0,out);self.assertIn('Python 3.12 was not found',out)
    def test_incomplete_extraction_pauses(self):
        code,out,_=self.run_case(missing_app=True)
        self.assertNotEqual(code,0,out);self.assertIn('Application files are missing',out)

    def test_real_application_http_start_via_launcher(self):
        import queue
        import threading
        from urllib.request import urlopen
        with tempfile.TemporaryDirectory() as tmp:
            process=subprocess.Popen([sys.executable,'-X','utf8','-u',str(ROOT/'launcher.py'),'--no-browser','--port','0','--data-dir',tmp],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',cwd=ROOT)
            lines=queue.Queue()
            def read():
                for line in process.stdout:lines.put(line)
            reader=threading.Thread(target=read,daemon=True);reader.start()
            try:
                captured=[]
                while True:
                    line=lines.get(timeout=20);captured.append(line)
                    if 'http://127.0.0.1:' in line:
                        url='http://'+line.split('http://')[1].split(' ')[0].strip()
                        break
                with urlopen(url,timeout=5) as response:
                    self.assertEqual(response.status,200)
                    self.assertIn('地球の観察録',response.read().decode('utf-8'))
            finally:
                process.terminate();process.wait(timeout=10)
                reader.join(timeout=5);process.stdout.close()
