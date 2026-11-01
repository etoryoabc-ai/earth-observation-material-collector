"""Offline SVG relation diagram from human-verified labels and edges only."""
from html import escape
from pathlib import Path
import uuid


def relation_svg(labels, edges, evidence, verified):
    if verified is not True or not evidence.strip():
        raise ValueError('検証済み情報源と人間による確認が必要です。')
    if not 2 <= len(labels) <= 6 or any(not isinstance(x, str) or not x.strip() or len(x) > 30 for x in labels):
        raise ValueError('ラベルは2〜6個、各30文字以内で入力してください。')
    if len(edges) > 12:
        raise ValueError('関係は12件以内にしてください。')
    body = []
    for i, label in enumerate(labels):
        x, y = 70 + (i % 3)*390, 130 + (i//3)*280
        body.append(f'<rect x="{x}" y="{y}" width="300" height="90" rx="12" fill="#d8e8d4"/><text x="{x+150}" y="{y+53}" text-anchor="middle" font-size="22">{escape(label)}</text>')
    for edge in edges:
        a, b, caption = edge
        if not isinstance(a, int) or not isinstance(b, int) or not 0 <= a < len(labels) or not 0 <= b < len(labels) or a == b or not isinstance(caption, str) or len(caption) > 35:
            raise ValueError('関係の始点・終点・説明が不正です。')
        x1, y1 = 220+(a%3)*390, 175+(a//3)*280
        x2, y2 = 220+(b%3)*390, 175+(b//3)*280
        # Arrows terminate outside node boxes; all labels are user verified.
        dx, dy = x2-x1, y2-y1
        fraction = min(0.35, 160/max(abs(dx), abs(dy)))
        sx, sy, ex, ey = x1+dx*fraction, y1+dy*fraction, x2-dx*fraction, y2-dy*fraction
        body.append(f'<path d="M{sx},{sy} L{ex},{ey}" stroke="#244c37" stroke-width="3" marker-end="url(#arrow)"/><text x="{(x1+x2)/2}" y="{(y1+y2)/2-14}" text-anchor="middle" font-size="18">{escape(caption)}</text>')
    return '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720"><defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#244c37"/></marker></defs><rect width="1280" height="720" fill="#f4f7ef"/><g fill="#19392d" font-family="sans-serif"><text x="70" y="70" font-size="28">関係図（入力された検証済み情報）</text>' + ''.join(body) + f'<text x="70" y="660" font-size="14">出典：{escape(evidence[:130])}</text></g></svg>'


def save_diagram(root, scene_id, labels, edges, evidence, verified):
    svg = relation_svg(labels, edges, evidence, verified)
    path = Path(root) / f'scene_{scene_id:03d}'
    path.mkdir(parents=True, exist_ok=True)
    target = path / f'diagram_{uuid.uuid4().hex[:10]}.svg'
    target.write_text(svg, encoding='utf-8')
    return target
