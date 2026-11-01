"""Private local settings. Keys are never sent back to the browser."""
import json
import os
from pathlib import Path
from .core import atomic_json
ROOT=Path(__file__).resolve().parent.parent
SETTINGS=ROOT/'settings.local.json'
SERVICES=('Pexels','Pixabay','Wikimedia Commons','NASA')

def read_settings():
    result={}
    if SETTINGS.exists():
        result=json.loads(SETTINGS.read_text(encoding='utf-8-sig'))
        if not isinstance(result,dict):raise ValueError('settings.local.json はJSONオブジェクトで指定してください。')
    for key in ('PEXELS_API_KEY','PIXABAY_API_KEY'):
        if os.getenv(key):result[key]=os.environ[key]
    result.setdefault('SEARCH_PROVIDERS',['Wikimedia Commons','NASA'])
    # Auto-migrate the old key-only default; explicit disabled sources are kept.
    if result['SEARCH_PROVIDERS']==['Pexels','Pixabay'] and not result.get('PROVIDERS_EXPLICIT_V12'):
        result['SEARCH_PROVIDERS']=['Wikimedia Commons','NASA']
    for service,key in [('Pexels','PEXELS_API_KEY'),('Pixabay','PIXABAY_API_KEY')]:
        if result.get(key) and service not in result['SEARCH_PROVIDERS']:
            result['SEARCH_PROVIDERS'].append(service)
    result.setdefault('MAX_REQUESTS_PER_PROVIDER',80)
    return result

def public_settings():
    settings=read_settings()
    return dict(pexels=bool(settings.get('PEXELS_API_KEY')),pixabay=bool(settings.get('PIXABAY_API_KEY')),
                providers=settings['SEARCH_PROVIDERS'],budget=settings['MAX_REQUESTS_PER_PROVIDER'],catalog=provider_catalog(settings))

def save_settings(data):
    current={}
    if SETTINGS.exists():current=json.loads(SETTINGS.read_text(encoding='utf-8-sig'))
    for key in ('PEXELS_API_KEY','PIXABAY_API_KEY'):
        value=data.get(key,'')
        if not isinstance(value,str) or len(value)>1000:raise ValueError('APIキーの形式が不正です。')
        if value.strip():current[key]=value.strip()
    selected=data.get('providers',current.get('SEARCH_PROVIDERS',['Pexels','Pixabay']))
    if not isinstance(selected,list) or any(p not in SERVICES for p in selected):
        raise ValueError('検索先を1つ以上選択してください。')
    current['SEARCH_PROVIDERS']=list(dict.fromkeys(selected))
    current['PROVIDERS_EXPLICIT_V12']=True
    budget=int(data.get('budget',80))
    if not 4<=budget<=150:raise ValueError('検索予算は4〜150にしてください。')
    current['MAX_REQUESTS_PER_PROVIDER']=budget
    atomic_json(SETTINGS,current)
    try: SETTINGS.chmod(0o600)
    except OSError: pass
    return public_settings()


def provider_catalog(settings=None):
    settings=settings or read_settings()
    result=[]
    keys={'Pexels':'PEXELS_API_KEY','Pixabay':'PIXABAY_API_KEY'}
    for name in SERVICES:
        required=name in keys
        ready=not required or bool(settings.get(keys.get(name,'')))
        selected=name in settings['SEARCH_PROVIDERS']
        result.append(dict(name=name,implemented=True,key_required=required,selected=selected,enabled=selected and ready,state='APIキー未設定' if selected and not ready else '利用可能（接続は検索時に確認）' if selected else '選択なし',note='公式API。素材固有の権利は要確認。'))
    for name,note in [('NOAA','統一した素材検索APIの対応は未実装。公式素材入口へのリンクのみ。'),('USGS','ScienceBase等の公開APIを調査中。本版の自動素材検索は未対応。'),('National Park Service','公式APIはキーが必要。本版の自動素材検索は未対応。')]:
        result.append(dict(name=name,implemented=False,key_required=name=='National Park Service',selected=False,enabled=False,state='検索先未対応',note=note))
    return result
