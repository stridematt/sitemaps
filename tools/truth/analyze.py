"""Read the facts a Christmas events page actually contains (its event cards), not the numbers its text claims."""
import re, json, unicodedata, html as H

# Plain cards are class="rtt-pe-ride"; verified cards are class="rtt-pe-ride rtt-pe-ride--verified rvc".
CARD = re.compile(r'<section class="rtt-pe-ride(?: [^"]*)?"([^>]*)>', re.S)


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


def signature(cal):
    # The same event in two language versions of a city page has the same place and the same dates, whatever
    # its name and event page. Used to count an event once when both language versions are counted.
    try:
        c = json.loads(cal)
    except Exception:
        return None
    # The host's link first: the place is written in each page's language ("Munich" / "München"), the link is not.
    link = re.sub(r'^https?://(www\.)?', '', (c.get('u') or '').split('#')[0].rstrip('/').lower())
    place = link or slug(c.get('l') or '')
    days = sorted({(r[0] or '', (r[1] if len(r) > 1 else '') or '', (r[3] if len(r) > 3 else '') or '') for r in (c.get('d') or []) if r})
    return place + '|' + ';'.join('~'.join(x) for x in days) if place and days else None


def slug(s):
    s = unicodedata.normalize('NFKD', H.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def cards(html):
    out = []
    ms = list(CARD.finditer(html))
    for i, m in enumerate(ms):
        tag = m.group(1)
        end = ms[i + 1].start() if i + 1 < len(ms) else m.end() + 20000
        seg = html[m.end():end]
        k = re.search(r'data-rtt-evp="([^"]+)"', seg) or re.search(r'class="rtt-pe-ride__book" href="/christmas-events/([a-z0-9-]+)"', seg)
        cid = attr(tag, 'id') or ''
        last = last_day(attr(tag, 'data-cal') or '{}')
        # A card that doesn't link an event page is keyed by what it is (name, town, last day), not by its id,
        # so the same event on a city page and on its district page (or two city pages) counts once.
        nm = re.search(r'<h3[^>]*>(.*?)</h3>', seg, re.S)
        key = k.group(1) if k else ('n:' + slug(nm.group(1)) + '|' + slug(attr(tag, 'data-xf-town') or '') + '|' + last if nm else cid)
        out.append({'id': cid, 'key': key, 'last': last, 'sig': signature(attr(tag, 'data-cal') or '{}'),
                    'free': 'free' in (attr(tag, 'data-xf-fl') or '').split(),
                    'town': attr(tag, 'data-xf-town') or '', 'types': (attr(tag, 'data-xf-ty') or '').split()})
    return out


def item_id(html):
    # Squarespace post id (the post body wrapper is id="item-<24 hex>"), used by the Squarespace sync
    m = re.search(r'data-type="item" id="item-([0-9a-f]{24})"', html) or re.search(r'\bid="item-([0-9a-f]{24})"', html)
    return m.group(1) if m else None


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
        'sigs': [c['sig'] or '' for c in live],
        'cards': len(cs), 'events': len(live), 'free': sum(c['free'] for c in live),
        'past': len(cs) - len(live), 'next_expiry': future[0] if future else None,
        'towns': towns, 'faq': faq,
        'title': H.unescape(title.group(1).strip()) if title else '', 'description': H.unescape(desc.group(1)) if desc else '',
        'lang': lang.group(1) if lang else '', 'checked': checked[-1] if checked else None,
        'sq': item_id(html),
    }


if __name__ == '__main__':
    import sys
    for f in sys.argv[2:]:
        r = analyze(open(f).read(), sys.argv[1])
        r.pop('towns') if len(r['towns']) > 6 else None
        print(f, json.dumps(r, ensure_ascii=False)[:900])
