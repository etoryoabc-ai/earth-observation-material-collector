import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import launcher
from tools.write_launchers import expected

ROOT=Path(__file__).resolve().parent.parent

class LauncherTests(unittest.TestCase):
    def test_batch_exact_ascii_crlf_no_bom(self):
        for name,mode in [('起動.bat',''),('テスト.bat','--test')]:
            raw=(ROOT/name).read_bytes()
            self.assertEqual(raw,expected(mode))
            raw.decode('ascii')
            self.assertNotIn(b'\n',raw.replace(b'\r\n',b''))
            self.assertNotIn(b'\r',raw.replace(b'\r\n',b''))
            self.assertFalse(raw.startswith(b'\xef\xbb\xbf'))
    def run_stub(self,text):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'日本語 空白 & folder';root.mkdir()
            (root/'app.py').write_text(text,encoding='utf-8')
            output=io.StringIO()
            before=Path.cwd()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
                code=launcher.launch(root)
            self.assertEqual(Path.cwd(),before)
            logs=list((root/'logs').glob('*.log'))
            self.assertEqual(len(logs),1)
            return code,output.getvalue(),logs[0].read_text(encoding='utf-8')
    def test_success_logged(self):
        code,out,log=self.run_stub('print("起動確認")\n')
        self.assertEqual(code,0);self.assertIn('起動確認',out);self.assertIn('起動確認',log)
    def test_exception_logged_nonzero(self):
        code,out,log=self.run_stub('raise RuntimeError("起動テスト用エラー")\n')
        self.assertEqual(code,1);self.assertIn('起動に失敗',out);self.assertIn('RuntimeError',log)
    def test_exit_code_preserved(self):
        self.assertEqual(self.run_stub('raise SystemExit(7)\n')[0],7)
    def test_wrong_python_rejected(self):
        with patch.object(launcher.sys,'version_info',(3,11)),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.launch(ROOT),1)
    def test_log_failure_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'logs').write_text('existing file')
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(launcher.launch(root),1)
            self.assertIn('ログを保存できません',out.getvalue())
