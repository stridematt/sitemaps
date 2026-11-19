"""Read the facts a Christmas events page actually contains (its event cards), not the numbers its text claims."""
import re, json, html as H

CARD = re.compile(r'<section class="rtt-pe-ride"([^>]*)>', re.S)


def attr(tag, name):
    m = re.search(r'\b' + re.escape(name) + r'="([^"]*)"', tag)
    return H.unescape(m.group(1)) if m else None


def last_day(cal):
    try:
        c = json.loads(cal)
    except Exception:
        return ''
    m = ''
    for r in c.get('d') or []:
        x = (r[3] if len(r) > 3 and r[3] else r[0]) or ''
        if x > m:
            m = x
    return m


def cards(html):
    out = []
    ms = list(CARD.finditer(html))
    for i, m in enumerate(ms):
        tag = m.group(1)
        end = ms[i + 1].start() if i + 1 < len(ms) else m.end() + 20000
        k = re.search(r'data-rtt-evp="([^"]+)"', html[m.end():end])
        cid = attr(tag, 'id') or ''
        out.append({'id': cid, 'key': k.group(1) if k else cid, 'last': last_day(attr(tag, 'data-cal') or '{}'),
                    'free': 'free' in (attr(tag, 'data-xf-fl') or '').split(),
                    'town': attr(tag, 'data-xf-town') or '', 'types': (attr(tag, 'data-xf-ty') or '').split()})
    return out


def analyze(html, today):
    cs = cards(html)
    live = [c for c in cs if not c['last'] or c['last'] >= today]
    head = html[:html.find('</head>')]
    title = re.search(r'<title>(.*?)</title>', head, re.S)
    desc = re.search(r'<meta name="description" content="([^"]*)"', head)
    lang = re.search(r'<html[^>]*\blang="([^"]+)"', html)
    checked = sorted(set(re.findall(r'<time datetime="(\d{4}-\d\d-\d\d)">', html)))
    future = sorted({c['last'] for c in live if c['last']})
    towns = {}
    for c in live:
        t = towns.setdefault(c['town'], [0, 0])
        t[0] += 1
        t[1] += c['free']
    faq = len(re.findall(r'"@type"\s*:\s*"Question"', html))
    return {
        'keys': [c['key'] for c in live], 'free_keys': [c['key'] for c in live if c['free']],
        'cards': len(cs), 'events': len(live), 'free': sum(c['free'] for c in live),
        'past': len(cs) - len(live), 'next_expiry': future[0] if future else None,
        'towns': towns, 'faq': faq,
        'title': H.unescape(title.group(1).strip()) if title else '', 'description': H.unescape(desc.group(1)) if desc else '',
        'lang': lang.group(1) if lang else '', 'checked': checked[-1] if checked else None,
    }


if __name__ == '__main__':
    import sys
    for f in sys.argv[2:]:
        r = analyze(open(f).read(), sys.argv[1])
        r.pop('towns') if len(r['towns']) > 6 else None
        print(f, json.dumps(r, ensure_ascii=False)[:900])
