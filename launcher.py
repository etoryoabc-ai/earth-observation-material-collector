"""UTF-8 Japanese diagnostics live here, never in cmd.exe batch source."""
import os
from pathlib import Path
import runpy
import subprocess
import sys
import traceback
from datetime import datetime

class Tee:
    def __init__(self, console, log):
        self.console,self.log=console,log
    def write(self,text):
        self.log.write(text);self.log.flush()
        return self.console.write(text)
    def flush(self):
        self.log.flush();self.console.flush()
    def __getattr__(self,key):
        return getattr(self.console,key)

def launch(root, test=False):
    if sys.version_info[:2] != (3,12):
        print('Python 3.12 が必要です。https://www.python.org/downloads/')
        return 1
    root=Path(root).resolve()
    log_dir=root/'logs'
    try:
        log_dir.mkdir(exist_ok=True)
        log_path=log_dir/f'startup-{datetime.now():%Y%m%d-%H%M%S-%f}-{os.getpid()}.log'
        log=log_path.open('x',encoding='utf-8')
    except OSError:
        print('ログを保存できません。ZIPを「ドキュメント」など書き込み可能なフォルダへ展開してください。')
        return 1
    old_out,old_err=sys.stdout,sys.stderr
    old_cwd=Path.cwd()
    try:
        sys.stdout=Tee(old_out,log);sys.stderr=Tee(old_err,log)
        print('地球の観察録 起動診断（v1.1.1）')
        print('Python:',sys.version.split()[0])
        print('実行ファイル:',sys.executable)
        print('アプリフォルダ:',root)
        print('診断ログ:',log_path)
        os.chdir(root)
        if test:
            return subprocess.call([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=root)
        if not (root/'app.py').is_file():
            raise FileNotFoundError('app.py がありません。ZIPをすべて展開してください。')
        runpy.run_path(str(root/'app.py'),run_name='__main__')
        return 0
    except KeyboardInterrupt:
        print('\nアプリを終了しました。')
        return 0
    except SystemExit as exc:
        code=exc.code if isinstance(exc.code,int) else (0 if exc.code is None else 1)
        if code: print('アプリがエラーで終了しました。終了コード:',code)
        return code
    except Exception:
        traceback.print_exc()
        print('\n起動に失敗しました。上のメッセージと診断ログを確認してください。')
        print('既に起動中の場合は前のアプリを閉じてください。APIキーは共有しないでください。')
        return 1
    finally:
        sys.stdout,sys.stderr=old_out,old_err
        os.chdir(old_cwd)
        log.close()

if __name__=='__main__':
    sys.exit(launch(Path(__file__).resolve().parent,test='--test' in sys.argv[1:]))
