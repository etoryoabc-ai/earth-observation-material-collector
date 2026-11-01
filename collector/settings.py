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
    result.setdefault('SEARCH_PROVIDERS',['Pexels','Pixabay'])
    result.setdefault('MAX_REQUESTS_PER_PROVIDER',80)
    return result

def public_settings():
    settings=read_settings()
    return dict(pexels=bool(settings.get('PEXELS_API_KEY')),pixabay=bool(settings.get('PIXABAY_API_KEY')),
                providers=settings['SEARCH_PROVIDERS'],budget=settings['MAX_REQUESTS_PER_PROVIDER'])

def save_settings(data):
    current={}
    if SETTINGS.exists():current=json.loads(SETTINGS.read_text(encoding='utf-8-sig'))
    for key in ('PEXELS_API_KEY','PIXABAY_API_KEY'):
        value=data.get(key,'')
        if not isinstance(value,str) or len(value)>1000:raise ValueError('APIキーの形式が不正です。')
        if value.strip():current[key]=value.strip()
    selected=data.get('providers',current.get('SEARCH_PROVIDERS',['Pexels','Pixabay']))
    if not isinstance(selected,list) or not selected or any(p not in SERVICES for p in selected):
        raise ValueError('検索先を1つ以上選択してください。')
    current['SEARCH_PROVIDERS']=list(dict.fromkeys(selected))
    budget=int(data.get('budget',80))
    if not 4<=budget<=150:raise ValueError('検索予算は4〜150にしてください。')
    current['MAX_REQUESTS_PER_PROVIDER']=budget
    atomic_json(SETTINGS,current)
    try: SETTINGS.chmod(0o600)
    except OSError: pass
    return public_settings()
