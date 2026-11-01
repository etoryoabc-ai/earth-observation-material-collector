"""Lossless, conservative offline analysis and persistent project state."""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

ANIMALS = {'ラッコ': ('sea otter', 'Enhydra lutris'), 'ウニ': ('sea urchin', ''),
           'ケルプ': ('kelp', ''), 'シャチ': ('killer whale', 'Orcinus orca')}
PLACES = {'アリューシャン列島': 'Aleutian Islands', 'アダック島': 'Adak Island',
          'バンクーバー島': 'Vancouver Island', 'サンニコラス島': 'San Nicolas Island'}

def now():
    return datetime.now(timezone.utc).isoformat()

def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def decode_script(raw):
    for encoding in ('utf-8-sig', 'cp932'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError('UTF-8 または Shift-JIS の TXT / Markdown を選んでください。')

def describe(text):
    from .analysis import details
    return details(text)


def analyze(source):
    from .scenes import group
    return group(source)[1]


def new_project(source, name):
    from .scenes import group, validate
    text_units, scenes = group(source)
    return dict(version=3, id=uuid.uuid4().hex, name=name, created=now(), source=source,
                analysis_mode='v1.2 文解析→映像シーンの二段階解析・AI不使用・費用なし', scenes=scenes, text_units=text_units, source_validation=validate(source,scenes),
                assets=[], attempts={}, logs=[], search_status='未開始', mock=False)

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, project_id):
        if not re.fullmatch('[a-f0-9]{32}', project_id):
            raise ValueError('不正なプロジェクト ID')
        return self.root / project_id / 'project.json'

    def save(self, project):
        atomic_json(self.path(project['id']), project)

    def load(self, project_id):
        return json.loads(self.path(project_id).read_text(encoding='utf-8'))

    def list(self):
        result = []
        for path in self.root.glob('*/project.json'):
            try:
                p = json.loads(path.read_text(encoding='utf-8'))
                result.append(dict(id=p['id'], name=p['name'], created=p['created']))
            except (ValueError, KeyError):
                continue
        return sorted(result, key=lambda x: x['created'], reverse=True)
