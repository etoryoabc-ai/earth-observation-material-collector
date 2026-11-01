"""Only approved, verified official-provider downloads; resumable bounded transfers."""
import hashlib
import json
from .core import atomic_json
import ipaddress
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

ALLOWED = {
    'Pexels': ('pexels.com', 'pexels.io'),
    'Pixabay': ('pixabay.com',),
    'Wikimedia Commons': ('upload.wikimedia.org',),
}
MAX_BYTES = 2 * 1024**3


def permitted(a):
    return (not a.get('mock') and a.get('risk') in ('A', 'B') and a.get('human_checked') is True
            and a.get('commercial') == '可' and bool(a.get('license_name')) and bool(a.get('license_url'))
            and bool(a.get('checked_at')) and bool(a.get('evidence')))


def check_url(url, provider):
    u = urlsplit(url)
    host = u.hostname or ''
    if u.scheme != 'https' or u.username or u.password or u.port not in (None, 443):
        raise ValueError('HTTPSの公式提供元URLが必要です。')
    if not any(host == domain or host.endswith('.' + domain) for domain in ALLOWED.get(provider, ())):
        raise ValueError('ダウンロードは対応提供元の公式配信先に限定されています。')
    for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError('内部アドレスへの接続は禁止されています。')

class Redirects(HTTPRedirectHandler):
    def __init__(self, provider):
        self.provider = provider
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.provider)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(asset, root):
    if asset.get('decision') != 'adopt' or not permitted(asset):
        raise ValueError('採用済み・A/B区分・人間の権利確認済み素材だけ保存できます。')
    check_url(asset['download_url'], asset['provider'])
    scene_dir = Path(root) / f'scene_{asset["scene_id"]:03d}'
    scene_dir.mkdir(parents=True, exist_ok=True)
    extension = {'mp4': 'mp4', 'webm': 'webm', 'ogg': 'ogv', 'jpeg': 'jpg', 'jpg': 'jpg', 'png': 'png'}.get(asset.get('format'), 'bin')
    # Stable per-scene material number assigned at adoption, plus no overwrites.
    filename = f'scene_{asset["scene_id"]:03d}_{asset["type"]}_{asset["material_number"]:03d}.{extension}'
    dest = scene_dir / filename
    if dest.exists():
        if asset.get('sha256') == hashlib.sha256(dest.read_bytes()).hexdigest():
            return str(dest)
        raise ValueError('同名ファイルが存在します。上書きしません。')
    part = dest.with_suffix(dest.suffix + '.part')
    metadata = part.with_suffix(part.suffix + '.json')
    if metadata.exists():
        try:
            saved = json.loads(metadata.read_text(encoding='utf-8'))
            if saved.get('url') == asset['download_url']:
                asset['download_etag'] = saved.get('validator', '')
        except (OSError, ValueError):
            pass
    if part.exists() and not asset.get('download_etag'):
        part.unlink()  # Cannot safely resume without an entity validator.
    opener = build_opener(Redirects(asset['provider']))
    for retry in range(3):
        try:
            offset = part.stat().st_size if part.exists() else 0
            headers = {'User-Agent': 'EarthObservationCollector/1.0', 'Accept-Encoding': 'identity'}
            if offset:
                headers['Range'] = f'bytes={offset}-'
                if asset.get('download_etag'):
                    headers['If-Range'] = asset['download_etag']
            with opener.open(Request(asset['download_url'], headers=headers), timeout=30) as response:
                append = offset > 0 and response.status == 206
                if append and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                    raise ValueError('再開位置が一致しません。')
                mime = response.headers.get('Content-Type', '').lower()
                if not mime.startswith(('image/', 'video/', 'application/octet-stream', 'binary/octet-stream')):
                    raise ValueError('画像・動画以外の応答を拒否しました。')
                asset['download_etag'] = response.headers.get('ETag') or response.headers.get('Last-Modified', '')
                atomic_json(metadata, dict(url=asset['download_url'], validator=asset['download_etag']))
                received = offset if append else 0
                expected = response.headers.get('Content-Length')
                transferred = 0
                with part.open('ab' if append else 'wb') as target:
                    while chunk := response.read(1024*256):
                        received += len(chunk)
                        transferred += len(chunk)
                        if received > MAX_BYTES:
                            raise ValueError('2 GiB上限を超える素材です。提供元で手動取得してください。')
                        target.write(chunk)
                if expected and transferred != int(expected):
                    raise OSError('ダウンロードが途中で切断されました。')
            part.rename(dest)
            metadata.unlink(missing_ok=True)
            digest = hashlib.sha256()
            with dest.open('rb') as f:
                while chunk := f.read(1024*1024):
                    digest.update(chunk)
            asset['sha256'] = digest.hexdigest()
            asset['downloaded'] = str(dest)
            asset['download_error'] = ''
            return str(dest)
        except ValueError:
            raise
        except Exception:
            if retry == 2:
                raise RuntimeError('ダウンロード失敗。途中ファイルを保持しました。再試行できます。') from None
            time.sleep(retry + 1)
