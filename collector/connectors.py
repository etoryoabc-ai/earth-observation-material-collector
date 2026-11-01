"""Independent official-API connectors. No scraping, no paid APIs."""
import html
import hashlib
from pathlib import Path
from .core import atomic_json
import json
import os
import re
import time
from urllib.parse import urlencode, urlsplit, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from .core import now

class APIError(RuntimeError):
    def __init__(self, message, code='error', retry_at=0):
        super().__init__(message)
        self.code, self.retry_at = code, retry_at

class RateLimited(APIError):
    def __init__(self, message='API上限。時間を空けて再開してください。', retry_at=0):
        super().__init__(message, 'rate_limited', retry_at)

class JsonHTTP:
    def __init__(self, cache_dir=None, max_requests=80):
        self.cache_dir = Path(cache_dir) if cache_dir else Path(__file__).resolve().parent.parent / 'data' / 'api_cache'
        self.last_request = 0
        self.last_info = {}
        self.max_requests = max_requests
        self.requests = {}

    def get(self, url, params=None, headers=None):
        host = urlsplit(url).hostname
        if host not in ('api.pexels.com','pixabay.com','commons.wikimedia.org','images-api.nasa.gov'):
            raise APIError('公式の無料検索API以外は呼び出せません。','blocked')
        if params:
            url += '?' + urlencode(params)
        cache_key = hashlib.sha256((url + json.dumps(headers or {}, sort_keys=True)).encode()).hexdigest()
        cache = self.cache_dir / (cache_key + '.json')
        self.last_info = {}
        if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
            try:
                cached=json.loads(cache.read_text(encoding='utf-8'))
                if isinstance(cached,dict) and cached.get('_cache_version')==2:
                    self.last_info=dict(origin='api_cache',fetched_at=cached['fetched_at'],endpoint=host,http_status=200)
                    return cached['data']
            except (OSError, ValueError, KeyError):
                pass
        # Hashed keys isolate quota accounting per credential without storing secrets.
        quota_key=hashlib.sha256((host+str(headers or {})+str((params or {}).get('key',''))).encode()).hexdigest()
        quota_path=self.cache_dir / ('quota_'+quota_key+'.json')
        quota={}
        if quota_path.exists():
            try: quota=json.loads(quota_path.read_text(encoding='utf-8'))
            except (OSError,ValueError): pass
        if quota.get('retry_at',0)>time.time():
            raise RateLimited('前回のAPI上限による待機中です。時間を空けて再開してください。',quota['retry_at'])
        req = Request(url, headers={'User-Agent': 'EarthObservationCollector/1.2 (https://github.com/etoryoabc-ai/earth-observation-material-collector; local documentary research)', **(headers or {})})
        for attempt in range(3):
            if self.requests.get(host,0)>=self.max_requests:
                raise APIError('今回の提供元別検索予算に達しました。進行を保存し、再開できます。','budget')
            recent=[stamp for stamp in quota.get('requests',[]) if time.time()-stamp<3600]
            if host=='api.pexels.com' and len(recent)>=190:
                until=recent[0]+3601
                quota.update(retry_at=until,requests=recent)
                atomic_json(quota_path,quota)
                raise RateLimited('Pexelsのローカル時間枠予算に達しました。時間を空けて再開してください。',until)
            elapsed=time.monotonic()-self.last_request
            if elapsed<0.7: time.sleep(0.7-elapsed)
            self.last_request=time.monotonic()
            self.requests[host]=self.requests.get(host,0)+1
            recent.append(time.time());quota['requests']=recent
            atomic_json(quota_path,quota)
            try:
                with urlopen(req, timeout=15) as response:
                    data=json.load(response)
                    if not isinstance(data,dict): raise ValueError('invalid API response')
                    if data.get('error'):
                        error=data['error']
                        if isinstance(error,dict) and error.get('code') in ('maxlag','ratelimited'):
                            raise RateLimited('提供元が混雑・利用上限を通知しました。時間を空けて再開してください。',time.time()+60)
                        raise APIError('公式APIがエラー応答を返しました（HTTP 200）。検索成功として扱いません。','api')
                    fetched=now()
                    self.last_info=dict(origin='api_network',fetched_at=fetched,endpoint=host,http_status=response.status)
                    remaining=response.headers.get('X-Ratelimit-Remaining')
                    if remaining=='0':
                        reset=response.headers.get('X-Ratelimit-Reset','')
                        try:
                            reset_value=float(reset)
                            quota['retry_at']=reset_value if host=='api.pexels.com' and reset_value>time.time() else time.time()+reset_value
                        except ValueError: quota['retry_at']=time.time()+3600
                        atomic_json(quota_path,quota)
                    atomic_json(cache,dict(_cache_version=2,fetched_at=fetched,data=data))
                    return data
            except HTTPError as exc:
                if exc.code==429:
                    try: delay=float(exc.headers.get('Retry-After','3600'))
                    except (ValueError,TypeError): delay=3600
                    quota['retry_at']=time.time()+max(60,delay)
                    atomic_json(quota_path,quota)
                    raise RateLimited(retry_at=quota['retry_at']) from None
                if exc.code in (401,403):
                    code='auth' if exc.code==401 or host in ('api.pexels.com','pixabay.com') else 'access'
                    raise APIError(f'HTTP {exc.code}：認証・提供元のアクセス制限・ネットワーク設定を確認してください。',code) from None
                if exc.code in (400,404,422):
                    raise APIError(f'HTTP {exc.code}：検索条件またはページ範囲を変更します。','query') from None
                if exc.code<500 or attempt==2:
                    raise APIError(f'HTTP {exc.code}：提供元APIの応答エラー。','http') from None
            except (OSError,ValueError):
                if attempt==2:
                    raise APIError('接続またはJSON応答エラー。ネットワーク設定を確認してください。','network') from None
            time.sleep(0.5*(attempt+1))


def clean(value):
    return html.unescape(re.sub('<[^>]*>', '', str(value or ''))).strip()

def base(provider, identity, title, page, kind):
    return dict(provider=provider, provider_id=str(identity), title=clean(title), page_url=page,
                type=kind, creator='', institution=provider, license_name='', license_url='',
                commercial='要確認', modification='要確認', attribution='要確認', terms='',
                checked_at='', evidence='', risk='D', human_checked=False, decision='hold',
                download_url='', thumbnail='', duration='', width=0, height=0, format='', size='',
                relevance='要確認', relevance_reason='検索語への一致のみ。映像の内容は未確認。',
                place_certainty='要確認', species_certainty='要確認', year_certainty='要確認',
                access_mode='link_only',provider_date='',api_origin='unverified', metadata_text='', free_only=True, license_scope='素材固有の条件は未確認',
                commercial_policy='要確認', policy_evidence_url='', policy_checked_at='',
                match_status='tentative', record_type='要確認', downloaded='', download_error='', citation_reason='',
                citation_script='', citation_range='', citation_distinct=False,
                citation_source=False, citation_main=False, mock=False)

class Pexels:
    name = 'Pexels'
    def __init__(self, http, key=''):
        self.http, self.key = http, key
    def search(self, query, kind, page=1):
        if not self.key:
            raise APIError('PEXELS_API_KEY 未設定（無料キーが必要）','missing_key')
        video = kind == 'video'
        data = self.http.get('https://api.pexels.com/' + ('v1/videos/search' if video else 'v1/search'),
                             dict(query=query[:200], per_page=20, page=page, orientation='landscape'), {'Authorization': self.key})
        out = []
        for item in data.get('videos' if video else 'photos', []):
            a = base(self.name, item['id'], item.get('alt') or clean(re.sub(r'-?\d+/?$', '', urlsplit(item['url']).path.strip('/').split('/')[-1]).replace('-', ' ')) or f'Pexels {item["id"]}', item['url'], kind)
            a.update(creator=item.get('user', {}).get('name', '') if video else item.get('photographer', ''),
                     thumbnail=item.get('image', '') if video else item.get('src', {}).get('medium', ''),
                     duration=item.get('duration', ''), width=item.get('width', 0), height=item.get('height', 0),
                     license_name='Pexels License', license_url='https://www.pexels.com/license/',
                     terms='商用利用・改変等の条件と禁止事項を素材ページおよび最新規約で人間が確認してください。',
                     evidence='公式APIの素材ページ。ライセンス条件の個別確認は未実施。')
            a['metadata_text'] = clean(item.get('alt','')) + ' ' + a['title']
            self.apply_policy(a)
            if video:
                files = [f for f in item.get('video_files', []) if f.get('file_type') == 'video/mp4']
                if files:
                    # One source video, one candidate; prefer full HD/4K.
                    f = max(files, key=lambda x: (bool((x.get('width') or 0)>=(x.get('height') or 0)), 1080 <= (x.get('height') or 0) <= 2160, min(x.get('height') or 0,2160)))
                    a.update(download_url=f['link'], width=f.get('width', 0), height=f.get('height', 0), format='mp4')
            else:
                a.update(download_url=item.get('src', {}).get('original', ''), format='jpg')
            if a.get('download_url'):a['access_mode']='download'
            a['api_origin']='mock' if a.get('mock') else getattr(getattr(self,'http',None),'last_info',{}).get('origin','fixture')
            a['api_fetched_at']=getattr(getattr(self,'http',None),'last_info',{}).get('fetched_at','')
            out.append(a)
        return out

    @staticmethod
    def apply_policy(a):
        a.update(commercial_policy='一般ライセンス上は商用利用可。第三者権利・禁止用途の個別確認が必要',
            modification='可（禁止用途・第三者権利に注意）',attribution='素材ライセンスでは任意。API画面では提供元リンクを表示',
            license_scope='一般規約の記録。素材固有の権利は未確認', policy_evidence_url='https://www.pexels.com/license/',policy_checked_at='2026-11-01',
            terms='無料利用・改変可。未加工素材の販売、他ストックサイトへの再配布、商標利用、推薦の示唆、人物への不適切な扱いは禁止。商標・肖像等は別途確認。',
            evidence='公式APIの素材URLとPexels一般ライセンス（2026-11-01確認）。素材固有の確認は未実施。')

class Pixabay:
    name = 'Pixabay'
    def __init__(self, http, key=''):
        self.http, self.key = http, key
    def search(self, query, kind, page=1):
        if not self.key:
            raise APIError('PIXABAY_API_KEY 未設定（無料キーが必要）','missing_key')
        video = kind == 'video'
        data = self.http.get('https://pixabay.com/api/' + ('videos/' if video else ''),
                             dict(key=self.key, q=query[:100], lang='ja' if re.search('[ぁ-んァ-ン一-龥]', query) else 'en', per_page=20, page=page, safesearch='true', **({} if video else {'image_type':'photo','orientation':'horizontal'})))
        out = []
        for item in data.get('hits', []):
            a = base(self.name, item['id'], item.get('tags', query), item['pageURL'], kind)
            a.update(creator=item.get('user', ''), thumbnail=item.get('webformatURL', ''),
                     license_name='Pixabay Content License', license_url='https://pixabay.com/service/license-summary/',
                     terms='素材固有の第三者権利・禁止用途を含め最新規約の確認が必要。',
                     evidence='公式APIの素材ページ。条件は人間による確認待ち。', duration=item.get('duration', ''))
            a.update(metadata_text=clean(item.get('tags','')), commercial_policy='一般ライセンス上は商用利用可。商標・人物等の第三者権利と禁止用途の確認が必要',
                modification='可（Content Licenseの条件あり）',attribution='任意（クレジット推奨）',
                license_scope='一般規約の記録。素材固有の権利は未確認',policy_evidence_url='https://pixabay.com/service/license-summary/',policy_checked_at='2026-11-01',
                terms='無料利用・改変可。素材単体の販売・配布、誤解を招く用途、商標としての使用は禁止。識別可能な商標・ロゴ等の商用用途や第三者権利は別途確認。',
                evidence='公式APIの素材URLとPixabay一般規約（2026-11-01確認）。素材固有の確認は未実施。')
            if video:
                variants = [v for v in item.get('videos', {}).values() if v.get('url')]
                if variants:
                    f = max(variants, key=lambda v: v.get('width', 0))
                    a.update(download_url=f['url'], width=f.get('width', 0), height=f.get('height', 0),
                             size=f.get('size', ''), thumbnail=f.get('thumbnail', ''), format='mp4')
            else:
                a.update(download_url=item.get('largeImageURL', ''), width=item.get('imageWidth', 0),
                         height=item.get('imageHeight', 0), size=item.get('imageSize', ''), format='jpg')
            if a.get('download_url'):a['access_mode']='download'
            a['api_origin']='mock' if a.get('mock') else getattr(getattr(self,'http',None),'last_info',{}).get('origin','fixture')
            a['api_fetched_at']=getattr(getattr(self,'http',None),'last_info',{}).get('fetched_at','')
            out.append(a)
        return out

class Commons:
    name = 'Wikimedia Commons'
    def __init__(self, http):
        self.http = http
    def search(self, query, kind, page=1):
        params = dict(action='query', format='json', generator='search', gsrsearch=query + (' filetype:video' if kind == 'video' else ' filetype:bitmap'),
                      gsrnamespace=6, gsrlimit=15, gsroffset=(page-1)*15, prop='imageinfo', iiprop='url|size|mime|extmetadata|metadata|commonmetadata', iiurlwidth=480)
        data = self.http.get('https://commons.wikimedia.org/w/api.php', params)
        out = []
        for item in data.get('query', {}).get('pages', {}).values():
            info = (item.get('imageinfo') or [{}])[0]
            mime = info.get('mime', '')
            actual_kind = 'video' if mime.startswith('video/') else 'photo' if mime.startswith('image/') else ''
            if actual_kind != kind:
                continue
            meta = info.get('extmetadata', {})
            get = lambda key: clean(meta.get(key, {}).get('value', ''))
            a = base(self.name, item['pageid'], item['title'], info.get('descriptionurl', ''), kind)
            license_name, license_url = get('LicenseShortName'), get('LicenseUrl')
            a.update(metadata_text=clean(item['title'])+' '+get('ImageDescription')+' '+get('Categories'),provider_date=get('DateTimeOriginal'),creator=get('Artist'), license_name=license_name, license_url=license_url,
                     terms=get('UsageTerms') + ' / ' + get('Restrictions'),
                     evidence='Commons imageinfo.extmetadata（個別ページで確認が必要）',
                     thumbnail=info.get('thumburl', ''), download_url=info.get('url', ''),
                     width=info.get('width', 0), height=info.get('height', 0), size=info.get('size', ''),
                     format=mime.split('/')[-1])
            a['duration']=next((x.get('value','') for x in info.get('commonmetadata',[])+info.get('metadata',[]) if x.get('name','').lower() in ('length','duration','playtime_seconds')), '')
            a['access_mode']='download' if a.get('download_url') else 'link_only'
            # Conservative: only recognized commercial licenses without known restrictions.
            if license_url.startswith('https://creativecommons.org/') and not get('Restrictions'):
                if re.fullmatch(r'CC BY(?:-SA)? [1-4]\.0', license_name):
                    a.update(risk='B', commercial='可', modification='可（ライセンス条件あり）',
                             attribution='必須', checked_at=now())
                elif license_name in ('CC0', 'CC0 1.0'):
                    a.update(risk='A', commercial='可', modification='可', attribution='不要', checked_at=now())
            if a.get('download_url'):a['access_mode']='download'
            a['api_origin']='mock' if a.get('mock') else getattr(getattr(self,'http',None),'last_info',{}).get('origin','fixture')
            a['api_fetched_at']=getattr(getattr(self,'http',None),'last_info',{}).get('fetched_at','')
            out.append(a)
        return out

class NASA:
    name = 'NASA'
    def __init__(self, http):
        self.http = http
    def search(self, query, kind, page=1):
        data = self.http.get('https://images-api.nasa.gov/search', dict(q=query, media_type='video' if kind == 'video' else 'image', page=page, page_size=15))
        out = []
        for item in data.get('collection', {}).get('items', []):
            d = (item.get('data') or [{}])[0]
            ident = d.get('nasa_id', '')
            a = base(self.name, ident, d.get('title', query), 'https://images.nasa.gov/details/' + quote(ident,safe=''), kind)
            a.update(metadata_text=clean(d.get('title',''))+' '+clean(d.get('description',''))+' '+clean(d.get('keywords','')), provider_date=d.get('date_created',''), access_mode='link_only',creator=d.get('photographer',d.get('secondary_creator','')), institution=d.get('center', 'NASA'),
                     evidence='NASA公式検索API。第三者権利・利用条件は未確認。',
                     license_url='https://www.nasa.gov/nasa-brand-center/images-and-media/',
                     thumbnail=next((x.get('href', '') for x in item.get('links', []) if x.get('rel') == 'preview'), ''))
            # No assumption that every NASA-hosted file is public domain; link only.
            if a.get('download_url'):a['access_mode']='download'
            a['api_origin']='mock' if a.get('mock') else getattr(getattr(self,'http',None),'last_info',{}).get('origin','fixture')
            a['api_fetched_at']=getattr(getattr(self,'http',None),'last_info',{}).get('fetched_at','')
            out.append(a)
        return out

class Mock:
    name = 'MOCK'
    def search(self, query, kind, page=1):
        out = []
        for i in range(3):
            a = base('MOCK', f'{query}-{kind}-{page}-{i}', f'【模擬データ】{query} {i+1}', 'https://example.invalid/mock', kind)
            a.update(mock=True, api_origin='mock', evidence='テスト専用。実在素材ではありません。')
            if a.get('download_url'):a['access_mode']='download'
            a['api_origin']='mock' if a.get('mock') else getattr(getattr(self,'http',None),'last_info',{}).get('origin','fixture')
            a['api_fetched_at']=getattr(getattr(self,'http',None),'last_info',{}).get('fetched_at','')
            out.append(a)
        return out

def providers(mock=False, selected=None, cache_dir=None):
    if mock:
        return [Mock()]
    from .settings import read_settings
    settings=read_settings()
    http=JsonHTTP(cache_dir=cache_dir,max_requests=settings['MAX_REQUESTS_PER_PROVIDER'])
    available=[Commons(http),NASA(http),Pexels(http,settings.get('PEXELS_API_KEY','')),Pixabay(http,settings.get('PIXABAY_API_KEY',''))]
    chosen=selected if selected is not None else settings['SEARCH_PROVIDERS']
    return [p for p in available if p.name in chosen and (not hasattr(p,'key') or bool(p.key))]


MANUAL_SOURCES = {
    'NOAA': 'https://www.noaa.gov/multimedia',
    'USGS': 'https://www.usgs.gov/products/multimedia-gallery',
    'National Park Service': 'https://www.nps.gov/subjects/digital/nps-data-api.htm',
}
