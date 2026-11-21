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


def slug(s):
    s = unicodedata.normalize('NFKD', H.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def source_key(cal, last):
    try:
        c = json.loads(H.unescape(cal))
    except Exception:
        return None
    u = re.sub(r'^https?://(www\.)?', '', (c.get('u') or '').split('#')[0].strip().lower()).rstrip('/')
    d = sorted(x[0] for x in (c.get('d') or []) if x and x[0])
    if not u or not d:
        return None
    return 'u:' + u + '|' + d[0] + '|' + (last or d[-1])


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
        # Language twins (christmas-in-paris-with-kids / noel-avec-les-enfants-paris) list the same event with two
        # different event pages, so the event-page key counts it twice. When the card says where the event is
        # published (data-cal "u") and when (its dates), key it by that instead: the same source page with the
        # same dates in two languages is one event.
        uk = source_key(attr(tag, 'data-cal') or '{}', last)
        out.append({'id': cid, 'key': key, 'uk': uk, 'last': last,
                    'free': 'free' in (attr(tag, 'data-xf-fl') or '').split(),
                    'town': attr(tag, 'data-xf-town') or '', 'types': (attr(tag, 'data-xf-ty') or '').split()})
    # A listing page (a city agenda, a festival programme) can be the source of several events with the same dates;
    # the source key is used only where it is unique on the page, so those events stay apart.
    n = {}
    for c in out:
        if c['uk']:
            n[c['uk']] = n.get(c['uk'], 0) + 1
    for c in out:
        if c['uk'] and n[c['uk']] == 1:
            c['key'] = c['uk']
        del c['uk']
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
