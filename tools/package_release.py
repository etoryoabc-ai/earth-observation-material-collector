"""Package only source files; verify extracted bytes, batch encoding and ZIP names."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parent.parent
NAME='earth-observation-material-collector-v1.1.1.zip'
FOLDER='earth-observation-material-collector'

def verify(path):
    with ZipFile(path) as z,tempfile.TemporaryDirectory() as tmp:
        if z.testzip() is not None:raise ValueError('ZIP integrity failed')
        for item in z.infolist():
            p=Path(item.filename)
            if '..' in p.parts or p.is_absolute():raise ValueError('Unsafe ZIP path')
            if p.name in ('settings.local.json','.env','credentials.json') or any(x in ('logs','data','.git','downloads','__pycache__') for x in p.parts):raise ValueError('Private/runtime path in ZIP')
        z.extractall(tmp)
        extracted=Path(tmp)/FOLDER
        manifest=json.loads((extracted/'package_manifest.json').read_text(encoding='utf-8'))
        for name,digest in manifest['sha256'].items():
            if hashlib.sha256((extracted/name).read_bytes()).hexdigest()!=digest:raise ValueError('Extracted file mismatch: '+name)
        for name in ('起動.bat','テスト.bat'):
            b=(extracted/name).read_bytes();b.decode('ascii')
            if b.startswith(b'\xef\xbb\xbf') or b'\n' in b.replace(b'\r\n',b'') or b'\r' in b.replace(b'\r\n',b''):raise ValueError('Invalid batch encoding/newlines')
            if b!=(ROOT/name).read_bytes():raise ValueError('Source and ZIP batch differ')
        return dict(file_count=len(manifest['sha256']),extracted_hashes='pass',batch_ascii_crlf_no_bom='pass',zip_integrity='pass',sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def build(path):
    tracked=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    files={}
    for rel in sorted(set(filter(None,tracked))):
        p=ROOT/rel
        if any(x in ('downloads','logs','data','.git','__pycache__') for x in Path(rel).parts) or p.name in ('settings.local.json','.env','credentials.json'):continue
        if p.is_file():files[rel]=p.read_bytes()
    # Do not accidentally package credentials introduced into a source file.
    import re
    secret=re.compile(rb'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
    if any(secret.search(b) for b in files.values()):raise ValueError('Credential pattern detected; packaging stopped')
    manifest=dict(version='1.1.1',sha256={rel:hashlib.sha256(b).hexdigest() for rel,b in files.items()},batch_format='ASCII / no BOM / CRLF')
    path.parent.mkdir(exist_ok=True)
    with ZipFile(path,'w',ZIP_DEFLATED) as z:
        for rel,b in files.items():z.writestr(FOLDER+'/'+rel,b)
        z.writestr(FOLDER+'/package_manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode())
    return verify(path)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
    target=ROOT/'downloads'/NAME
    print(json.dumps(verify(target) if args.verify_only else build(target),ensure_ascii=False,indent=2))
