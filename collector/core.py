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
    """Paragraph/sentence semantic cues, never drop or normalize a source character.

    This is intentionally not an LLM. Boundaries prefer changes in explicit
    location, dated records, hypothesis and explanation. Ambiguous text is kept.
    """
    if not source.strip():
        raise ValueError('原稿が空です。')
    headings = list(re.finditer(r'(?m)^(?:#{1,6}\s+.+|第[0-9０-９一二三四五六七八九十]+章[^\r\n]*|[0-9０-９]+[.．、]\s*[^\r\n]+)\r?$', source))
    bounds = sorted(set([0, len(source)] + [m.start() for m in headings]))
    scenes = []
    chapter = '本文'
    for lo, hi in zip(bounds, bounds[1:]):
        matching = next((m for m in headings if m.start() == lo), None)
        if matching:
            chapter = matching.group().strip().lstrip('#').strip()
        text = source[lo:hi]
        cuts = [lo]
        # Split at explicit editorial/semantic transitions, retaining every byte
        # decoded as text. No inherited place/year assertions across boundaries.
        from .analysis import mentions, GEO, BIO
        last_signature = None
        for m in re.finditer(r'[^。！？]+[。！？]?|[。！？]', text):
            segment = m.group()
            d = describe(segment)
            signature = (tuple(x['ja'] for x in d['places']), tuple(x['ja'] for x in d['animals']), tuple(d['years']), d['claim_type'])
            if last_signature is not None:
                changed = (signature[0] and signature[0] != last_signature[0]) or (signature[1] and last_signature[1] and signature[1] != last_signature[1]) or (signature[2] and signature[2] != last_signature[2]) or signature[3] != last_signature[3]
                if changed and lo + m.start() > lo:
                    cuts.append(lo + m.start())
            if segment.strip():
                last_signature = signature
        cuts.extend(lo+m.end() for m in re.finditer(r'\n[ \t]*\r?\n',text) if lo+m.end()<hi)
        cuts = sorted(set(cuts))
        cuts.append(hi)
        for start, end in zip(cuts, cuts[1:]):
            fragment = source[start:end]
            if not fragment.strip() and scenes:
                scenes[-1]['end'] = end
                scenes[-1]['text'] += fragment
                continue
            scenes.append(dict(id=len(scenes)+1, chapter=chapter, start=start, end=end,
                               text=fragment, **describe(fragment)))
    assert ''.join(s['text'] for s in scenes) == source
    from .analysis import annotate_offsets
    return annotate_offsets(scenes)

def new_project(source, name):
    return dict(version=2, id=uuid.uuid4().hex, name=name, created=now(), source=source,
                analysis_mode='v1.1 文単位の根拠付き規則解析・AI不使用・費用なし', scenes=analyze(source),
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
