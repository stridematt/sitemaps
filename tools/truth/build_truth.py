#!/usr/bin/env python3
"""Build tools/truth/live.json: what the Christmas events pages actually contain.

Every city guide and country or state guide is read every run (6 threads, with backoff on
429/503) for its event cards (dates and free flags). Past events are dropped, each city is
counted once using its fuller language version (twins are not double counted), and the
result is rolled up by state, country, region and for the whole hub. New country and region
guides are found from the newest-posts feed (/christmas-events?format=json) and crawled
down to their city pages. Also writes tools/sqsp/ids.json (path to Squarespace post id).

The Cloudflare Worker reads live.json to keep every number on the hub, country and state
pages and city pages right; the Squarespace sync writes the same numbers into the posts.

Usage: python3 tools/truth/build_truth.py [--state .state/truth.json] [--max 8000]
"""
import argparse, collections, concurrent.futures as cf, datetime, gzip, json, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import analyze, item_id

SITE = 'https://www.rallytakesthetrain.com'
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
# Our own pipeline proves itself to Cloudflare with this header (GitHub secret RTT_BOT_KEY), so bot protection never challenges it.
HDR = {'User-Agent': UA, **({'x-rtt-key': os.environ['RTT_BOT_KEY']} if os.environ.get('RTT_BOT_KEY') else {})}
sys.path.insert(0, os.path.join(ROOT, 'tools', 'llms'))
import build_llms as L  # hub parser, ISO codes, English city guide pattern


def own_country(h):
    """The country a city page says it is in: its data-ke-country, else the most common addressCountry of
    its events (ISO-2, upper case). None when the page doesn't say."""
    m = re.search(r'data-ke-country="([A-Za-z]{2})"', h)
    if m:
        return m.group(1).upper()
    cs = collections.Counter(c.upper() for c in re.findall(r'"addressCountry"\s*:\s*"([A-Za-z]{2})"', h))
    return cs.most_common(1)[0][0] if cs else None


DISTRICT = re.compile(r'^\d{1,2}(?:-kerulet|er|e|eme|-arr|-bezirk)?$')
LANG_PREFIX = re.compile(r'^/?(?:christmas-events/)?(navidad-con-ninos|noel-avec-les-enfants|activites-de-noel-pour-enfants|weihnachten-mit-kindern|natale-con-i-bambini|kerst-met-kinderen|natal-com-criancas|kodomo-christmas|rozhdestvo-s-detmi)-')
# The language prefix of a translated city page ("rozhdestvo-s-detmi-", "navidad-con-ninos-"...). Only such a
# prefix makes a page a twin: "north-charleston" is not a twin of "charleston".
XMAS_PREFIX = re.compile(r'(^|-)(christmas|xmas|navidad|natal|noel|weihnacht\w*|natale|kerst|kodomo|rozhdestvo|jul\w*|joulu\w*|bozic|vanoce|karacsony|craciun|boze|kalikimaka|kurisumasu|krismas|kerismas)(-|$)')


# English country names by code, for guides whose title is in another language (the UAE guide is Arabic).
ISO_NAME = {**{v: k for k, v in L.ISO.items()}, 'AE': 'United Arab Emirates', 'SV': 'El Salvador', 'CZ': 'Czechia'}


def city_base(path):
    """City part of a city page slug: no section, no trailing 2-letter code."""
    return re.sub(r'-[a-z]{2}$', '', path.rsplit('/', 1)[-1])


def twin_of(q, country, place):
    """An already counted city in the same country whose slug this language-prefixed page ends with
    (rozhdestvo-s-detmi-tallinn-ru -> tallinn-ee, navidad-con-ninos-paris -> paris-fr), or None."""
    b = city_base(q)
    for p, o in place.items():
        if o.get('country') != country or p == q:
            continue
        pb = city_base(p)
        if pb and pb != b and b.endswith('-' + pb) and XMAS_PREFIX.search(b[:-len(pb) - 1]):
            return p
    return None


def log(*a):
    print(*a, file=sys.stderr, flush=True)


RC = re.compile(r'<li class="rtt-rc">(?:(?!</li>).){0,3000}?href="(/christmas-events/[a-z0-9-]+)"[^>]*>(?:<[^>]+>)*([^<]{1,80})', re.S)
SEC = re.compile(r'<h2 id="city-[^"]*"[^>]*>([^<]{1,80})(?:(?!<h2\b).){0,4000}?href="(/christmas-events/[a-z0-9-]+)', re.S)


RCS = re.compile(r'<ul class="rtt-rcs"[^>]*>(.*?)</ul>', re.S)
RCS_LI = re.compile(r'<li\b[^>]*>(?:(?!</li>).){0,600}?href="(/christmas-events/[a-z0-9-]+)"[^>]*>(?:<[^>]+>)*([^<]{1,120})', re.S)


def linked_cities(h, self_path=None):
    """City pages a guide lists: its city cards, its city sections and its city lists
    (ul.rtt-rcs, the format of the Sweden, Cyprus and Estonia guides) (path -> shown name)."""
    out = {}
    for m in RC.finditer(h):
        out.setdefault(m.group(1), m.group(2).strip())
    for ul in RCS.finditer(h):
        for li in re.finditer(r'<li\b[^>]*>(.*?)</li>', ul.group(1), re.S):
            # every city page an item links (its own page and its other-language page)
            hrefs = re.findall(r'href="(/christmas-events/[a-z0-9-]+)"[^>]*>(?:<[^>]+>)*([^<]{0,120})', li.group(1))
            for i, (q, name) in enumerate(hrefs):
                out.setdefault(q, (hrefs[0][1] if i else name).strip())
    # Some guides list their cities in ul.rtt-other-countries (El Salvador). Only links that end in the
    # country code most of the guide's other city links use count; other countries' guides never do.
    codes = collections.Counter(q.rsplit('-', 1)[-1] for q in out if re.search(r'-[a-z]{2}$', q))
    extra = {}
    for ul in re.finditer(r'<ul class="rtt-other-countries"[^>]*>(.*?)</ul>', h, re.S):
        for m in re.finditer(r'href="(/christmas-events/[a-z0-9-]+-([a-z]{2}))"[^>]*>(?:<[^>]+>)*([^<]{1,120})', ul.group(1)):
            extra.setdefault(m.group(1), (m.group(2), m.group(3).strip()))
    if extra:
        cc = codes.most_common(1)[0][0] if codes else collections.Counter(c for c, _ in extra.values()).most_common(1)[0][0]
        for q, (c, name) in extra.items():
            if c == cc:
                out.setdefault(q, name)
    for m in SEC.finditer(h):
        out.setdefault(m.group(2), m.group(1).strip())
    out.pop(self_path, None)
    return out


def item_json(path):
    """A post's Squarespace JSON (body, title, id), or None."""
    for i in range(5):
        try:
            r = urllib.request.urlopen(urllib.request.Request(SITE + path + ('&' if '?' in path else '?') + 'format=json', headers={**HDR}), timeout=60)
            return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            time.sleep(8 * (i + 1) if e.code in (429, 503) else 3)
        except Exception:
            continue
    return None


def clean_name(name, path=''):
    """A city's name from a card or title that may be a whole headline
    ("¿Qué hacer en Navidad con niños en Buin?" -> "Buin")."""
    n = re.sub(r'\s*\(?\b20\d\d\)?\s*$', '', (name or '').strip())
    if '?' in n or re.search(r'(?i)navidad|natal|no[eë]l|christmas|weihnacht|kerst|natale|jul |advent|kar[aá]csony|j[oó]la', n):
        m = re.search(r'(?i).*(?:^|\s)(?:en|in|à|em|na|a|im|nel|ni|di|i|på|í)\s+([^?¿()]+?)\s*[?!.]*\s*$', n)
        if m and len(m.group(1)) <= 40:
            return m.group(1).strip()
        slug = path.rsplit('/', 1)[-1]
        slug = re.sub(r'^(navidad-con-ninos|natal-com-criancas|noel-avec-les-enfants|weihnachten-mit-kindern|natale-con-i-bambini|kerst-met-kinderen)-', '', slug)
        slug = re.sub(r'-[a-z]{2}$', '', slug)
        return ' '.join(w.capitalize() for w in slug.split('-')) or n
    return n


def plain(s):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def discover_guides(known_guides, known_places, code2name, found, today, log):
    """New country and region guides the hub does not list yet.

    Walks the Christmas events collection newest first (back to the last run), takes every new post
    that lists city cards, and follows its cards down to the city pages (a country page can list
    region pages, which list city pages). Returns the updated `found` registry:
      found['hw']: newest publish time seen; found['guides'][path] = {kind, name, country, cities, subs}
    """
    hw = found.get('hw', 0)
    guides = found.setdefault('guides', {})
    url, newest, roots = '/christmas-events', hw, []
    for _ in range(250):
        j = item_json(url)
        if not j:
            break
        stop = False
        for it in j.get('items', []):
            if it.get('publishOn', 0) <= hw - 3600000:
                stop = True
                break
            newest = max(newest, it.get('publishOn', 0))
            p, b = it.get('fullUrl', ''), it.get('body') or ''
            if p in known_guides or p in guides or p in known_places or '<section class="rtt-pe-ride' in b:
                continue
            if '<li class="rtt-rc">' in b or 'class="rtt-rcs"' in b:
                roots.append((p, it.get('title', ''), b))
        nxt = (j.get('pagination') or {}).get('nextPageUrl')
        if stop or not nxt:
            break
        url = nxt
    found['hw'] = newest
    # Guides published before the walk reached them (or in a list format the walk didn't know yet): tools/truth/guide-seed.txt
    seed = os.path.join(HERE, 'guide-seed.txt')
    if os.path.exists(seed):
        for g in (l.strip() for l in open(seed, encoding='utf-8')):
            if g.startswith('/christmas-events/') and g not in known_guides and g not in [r[0] for r in roots]:   # re-read every run
                j = item_json(g)
                if j and j.get('item'):
                    roots.append((g, j['item'].get('title', ''), j['item'].get('body') or ''))
    # re-crawl guides found earlier once a day (they gain cities as they are built out)
    for g, v in guides.items():
        if v.get('at', '') < today and v.get('kind') == 'country':
            j = item_json(g)
            if j and j.get('item'):
                roots.append((g, j['item'].get('title', ''), j['item'].get('body') or ''))
    sub_of = {s: g for g, v in guides.items() for s in v.get('subs', {})}
    for root, title, body in roots:
        if root in sub_of:
            continue
        cities, subs, seen = {}, {}, {root}
        queue = [(root, body, None)]
        while queue:
            path, b, parent = queue.pop()
            for q, name in linked_cities(b, path).items():
                if q in seen or q in known_guides:
                    continue
                seen.add(q)
                if q in known_places:
                    cities[q] = name
                    continue
                j = item_json(q)
                qb = ((j or {}).get('item') or {}).get('body') or ''
                if not qb:  # could not read it now: keep what the last crawl knew
                    prev = guides.get(root) or {}
                    if q in prev.get('cities', {}):
                        cities[q] = prev['cities'][q]
                    elif q in prev.get('subs', {}):
                        subs[q] = prev['subs'][q]
                        for c2, n2 in (guides.get(q) or {}).get('cities', {}).items():
                            cities.setdefault(c2, n2)
                    continue
                if '<section class="rtt-pe-ride' in qb or ('<li class="rtt-rc">' not in qb and qb):
                    cities[q] = name
                elif '<li class="rtt-rc">' in qb:
                    subs[q] = {'name': name}
                    queue.append((q, qb, path))
        codes = collections.Counter(c.rsplit('-', 1)[-1].upper() for c in cities if re.search(r'-[a-z]{2}$', c))
        cc = codes.most_common(1)[0][0] if codes else ''
        ld = re.search(r'"@type":\s*"Country",\s*"name":\s*"([^"]+)"', body)
        country = code2name.get(cc) or (plain(ld.group(1)) if ld else '') or ISO_NAME.get(cc) or re.sub(r'\s*\(\d{4}\)\s*$', '', title)
        if not cities:
            continue
        kind = 'region' if cc in code2name else 'country'
        guides[root] = {'kind': kind, 'name': country if kind == 'country' else re.sub(r'\s*\(\d{4}\)\s*$', '', title),
                        'country': country, 'cc': cc, 'cities': cities, 'subs': subs, 'at': today}
        log(f'found a {kind} guide the hub does not list yet: {root} ({country}, {len(cities)} city pages, {len(subs)} region pages)')
    # a region page found on its own before its country page: keep it under the country only
    subs_all = {s for v in guides.values() for s in v.get('subs', {})}
    for g in [g for g in guides if g in subs_all]:
        guides.pop(g)
    return found


def fetch(path, tries=5):
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(SITE + path, headers={**HDR, 'Accept-Encoding': 'gzip'}), timeout=60)
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                b = gzip.decompress(b)
            return 200, b.decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return e.code, ''
            if e.code in (429, 503):
                time.sleep(8 * (i + 1))  # Squarespace is rate limiting: back off
                continue
        except Exception:
            pass
        time.sleep(3)
    return 0, ''


def ref_today():
    # An event stays listed until its last day is over everywhere (UTC-12).
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=12)).date().isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=8000, help='most pages to read this run')
    ap.add_argument('--titles', default=os.path.join(ROOT, '.state', 'llms-titles.json'))
    ap.add_argument('--state', default=os.path.join(ROOT, '.state', 'truth.json'), help='full registry kept between runs')
    args = ap.parse_args()
    today = ref_today()
    out_path = args.state
    seed = os.path.join(HERE, 'truth-seed.json')
    src = out_path if os.path.exists(out_path) else seed if os.path.exists(seed) else None
    old = json.load(open(src, encoding='utf-8')) if src else {'pages': {}}
    pages = old.get('pages', {})

    _, hb = L.get(SITE + '/christmas-events-for-kids')
    hub = L.parse_hub(hb.decode('utf-8'))
    _, sm = L.get(SITE + '/sitemap.xml')
    lastmod = dict(re.findall(r'<loc>https://www\.rallytakesthetrain\.com([^<]+)</loc>\s*(?:<changefreq>[^<]*</changefreq>\s*)?(?:<priority>[^<]*</priority>\s*)?<lastmod>([^<]+)</lastmod>', sm.decode('utf-8')))

    # Every city guide and where it belongs. Primary list: the hub's own finder data (xn-data),
    # then the hub's A to Z, then English city guides in the sitemap that neither has yet.
    hub_html = hb.decode('utf-8')
    place = {}  # path -> {country, state(path), name, main}
    in_az = set()
    for c in hub:
        for g in c['groups']:
            for anchors in g['cities']:
                in_az.update(hr for hr, a, tx in anchors)
    abbr2state = {v: '/christmas-events/' + k for k, v in L.US_ABBR.items() if k != 'district-of-columbia'}
    xd = re.search(r'<script type="application/json" id="xn-data">(.*?)</script>', hub_html, re.S)
    if xd:
        D = json.loads(xd.group(1))
        for a in D.get('p', []):
            slugs = ['/christmas-events/' + x.split(':', 1)[1] for x in str(a[6]).split(',') if ':' in x]
            if not slugs:
                continue
            country = D['c'][a[3]][1]
            st = abbr2state.get(a[4]) if country == 'United States' and a[4] else None
            for q in slugs:
                place[q] = {'country': country, 'state': st, 'name': a[0], 'main': slugs[0]}
    for c in hub:
        for g in c['groups']:
            st = g['state'][0] if g['state'] else None
            for anchors in g['cities']:
                for hr, a, tx in anchors:
                    place.setdefault(hr, {'country': c['name'], 'state': st, 'name': anchors[0][2], 'main': anchors[0][0]})
    titles = {}
    seed = os.path.join(ROOT, 'tools', 'llms', 'titles-seed.json')
    for f in (seed, args.titles):
        if os.path.exists(f):
            titles.update(json.load(open(f, encoding='utf-8')))
    us_state = {v.lower(): k for k, v in L.US_ABBR.items() if k != 'district-of-columbia'}
    for p, t in titles.items():
        if p in place or not p.startswith('/christmas-events/') or not isinstance(t, str):
            continue
        m = L.ENGLISH_GUIDE.match(t)
        if not m or p not in lastmod:
            continue
        code = p.rsplit('-', 1)[-1]
        if code in L.CA_PROV:
            place[p] = {'country': 'Canada', 'state': None, 'name': m.group(1).strip(), 'main': p}
        elif code in us_state:
            place[p] = {'country': 'United States', 'state': '/christmas-events/' + us_state[code], 'name': m.group(1).strip(), 'main': p}
    missing = [p for p, v in place.items() if v['main'] == p and not any(q in in_az for q, o in place.items() if o['main'] == p)]
    odd = sorted(p for p in place if 'duplicate' in p or 'copy' in p.rsplit('/', 1)[-1].split('-'))
    for p in odd:  # leftover copies are not counted as cities
        place.pop(p, None)
    missing = [p for p in missing if p not in odd]

    # Country and state guides: they list cities and quote totals.
    guides = {}
    for c in hub:
        for hr, a, tx in c['guides']:
            guides[hr] = {'kind': 'country', 'name': c['name']}
        for g in c['groups']:
            if g['state']:
                guides[g['state'][0]] = {'kind': 'state', 'name': g['state'][1], 'country': c['name']}
    # Country and region guides the hub does not list yet (a new country is live before it is on the hub)
    code2name = {}
    if xd:
        code2name = {c[0]: c[1] for c in json.loads(xd.group(1)).get('c', [])}
    found = discover_guides(guides, place, code2name, old.get('found', {}), today, log)
    for g, fg in found.get('guides', {}).items():
        if g in guides:
            continue
        guides[g] = {'kind': fg['kind'], 'name': fg['name'], 'country': fg['country']}
        for sub, sd in fg.get('subs', {}).items():
            guides.setdefault(sub, {'kind': 'region', 'name': sd.get('name', ''), 'country': fg['country']})
        for q, name in sorted(fg.get('cities', {}).items(), key=lambda kv: (len(kv[0].split('-')), kv[0])):
            if q in place:
                continue
            twin = twin_of(q, fg['country'], place)
            place[q] = {**place[twin]} if twin else {'country': fg['country'], 'state': None, 'name': clean_name(name, q), 'main': q}
    gstate = old.get('guide_pages', {})
    # New city pages a country or state guide links to (its city cards and city sections) count too,
    # even before the hub lists them. They are picked up from the last read of each guide.
    added = []
    for g, gs in gstate.items():
        gi = guides.get(g)
        if not gi:
            continue
        for q in sorted(gs.get('cities', []), key=lambda x: (len(x.split('-')), x)):
            if q in place or q in guides or q in odd or 'duplicate' in q:
                continue
            country = gi['name'] if gi['kind'] == 'country' else gi.get('country', '')
            twin = twin_of(q, country, place)
            if twin:  # another-language page of a city already counted (rozhdestvo-s-detmi-tallinn-ru = tallinn-ee)
                place[q] = {**place[twin], 'main': place[twin]['main']}
                continue
            place[q] = {'country': country, 'state': g if gi['kind'] == 'state' and country == 'United States' else None,
                        'name': clean_name(gs.get('names', {}).get(q) or '', q), 'main': q}
            added.append(q)
    if added:
        log(f'{len(added)} city pages found through guides that the hub does not list yet: {added[:10]}')

    # District pages (praha-1-cz, budapest-12-kerulet-hu, navidad-con-ninos-madrid-retiro, noel-avec-les-enfants-paris-1er)
    # list events of their city. They are not cities: their cards count as part of the city they extend, once
    # (cards are keyed by event page or by name, town and date), and they never count as a city of their own.
    parent_of = {}
    by_base = {}
    for p, o in place.items():
        by_base.setdefault((city_base(p), p.rsplit('-', 1)[-1] if re.search(r'-[a-z]{2}$', p) else ''), p)
    for q in re.findall(r'<loc>https://www\.rallytakesthetrain\.com(/christmas-events/[a-z0-9-]+)</loc>', sm.decode('utf-8')):
        if q in place or q in guides or q in odd:
            continue
        code = q.rsplit('-', 1)[-1] if re.search(r'-[a-z]{2}$', q) else ''
        b = city_base(q) if code else q.rsplit('/', 1)[-1]
        parts = b.split('-')
        for i in range(len(parts) - 1, 0, -1):
            pb, rest = '-'.join(parts[:i]), '-'.join(parts[i:])
            par = by_base.get((pb, code)) or (by_base.get(('/christmas-events/' + pb, '')) if not code else None)
            if not par:
                continue
            prefixed = bool(LANG_PREFIX.match(pb))
            if DISTRICT.match(rest) or prefixed:
                parent_of[q] = place[par]['main']
            break
    if parent_of:
        log(f'{len(parent_of)} district pages counted as part of their city: {sorted(parent_of)[:12]}')

    # What to (re)read
    # Every page is read every run: Squarespace's sitemap dates lag behind edits, so a page that
    # changed would otherwise keep its old count for days. New and changed pages go first.
    due = []
    for p in list(place) + list(guides) + list(parent_of):
        prev = pages.get(p)
        if not prev:
            due.append((0, p))
        elif prev.get('lastmod') != lastmod.get(p):
            due.append((1, p))
        elif prev.get('x') and prev['x'] < today:
            due.append((2, p))
        else:
            due.append((3, p))
    due.sort()
    todo = [p for _, p in due[:args.max]]
    log(f'{len(place)} city guide pages ({len(missing)} cities not in the hub A to Z); reading {len(todo)} of {len(due)} due')
    if odd:
        log(f'pages that look like leftover copies: {odd}')
    ids_path = os.path.join(HERE, '..', 'sqsp', 'ids.json')
    sq_ids = json.load(open(ids_path, encoding='utf-8')) if os.path.exists(ids_path) else {}
    failed = 0
    with cf.ThreadPoolExecutor(6) as ex:
        for p, (st, h) in zip(todo, ex.map(fetch, todo)):
            if st == 200 and h and p in guides:
                hrefs = set(re.findall(r'href="(/christmas-events/[a-z0-9-]+)(?:#[^"]*)?"', h))
                links = sorted(hrefs & set(place))
                cities = linked_cities(h, p)
                gstate[p] = {'links': links, 'subs': sorted(q for q in (set(cities) & set(guides)) if q != p), 'cities': sorted(cities), 'names': cities, 'lang': (re.search(r'<html[^>]*\blang="([^"]+)"', h) or [None, ''])[1], 'lastmod': lastmod.get(p), 'at': today}
                sq_ids[p] = item_id(h) or sq_ids.get(p)
                pages.setdefault(p, {}).update({'guide': True, 'lastmod': lastmod.get(p), 'at': today, 'e': 0, 'f': 0, 'k': [], 'fk': [], 'x': None})
            elif st == 200 and h:
                r = analyze(h, today)
                sq_ids[p] = r['sq'] or sq_ids.get(p)
                pages[p] = {'e': r['events'], 'f': r['free'], 'x': r['next_expiry'], 'c': r['checked'], 'q': r['faq'],
                            'k': r['keys'], 'fk': r['free_keys'], 'lang': r['lang'], 'co': own_country(h), 'lastmod': lastmod.get(p), 'at': today}
                if p in parent_of:  # a district page links back to its city (any language version)
                    ups = {q for q, o in place.items() if o['main'] == parent_of[p]}
                    pages[p]['up'] = any(f'href="{u}"' in h or f'href="{u}#' in h for u in ups)
            elif st in (404, 410):
                pages.pop(p, None)
            else:
                failed += 1
    if failed:
        log(f'{failed} pages could not be read; their last known counts are kept')
    # A page counted as a U.S. city must not say it is somewhere else. State codes double as country codes in
    # slugs (-co Colombia/Colorado, -de Germany/Delaware, -ca Canada/California...), so an English page for a
    # non-U.S. city could be filed under a U.S. state. The page's own country (its data-ke-country or the
    # addressCountry of its events) decides; such a page is left out of the U.S. and reported.
    misfiled = sorted(q for q, o in place.items() if o['country'] == 'United States' and (pages.get(q) or {}).get('co') not in (None, 'US'))
    for q in misfiled:
        log(f'not a U.S. city (the page says {pages[q]["co"]}): {q}; left out of the U.S. counts until a guide places it')
        place.pop(q, None)
    # Squarespace post ids for the sync (path -> id), kept for pages that still exist
    sq_ids = {p: i for p, i in sq_ids.items() if i and (p in place or p in guides)}
    os.makedirs(os.path.dirname(ids_path), exist_ok=True)
    json.dump(dict(sorted(sq_ids.items())), open(ids_path, 'w', encoding='utf-8'), indent=0, separators=(',', ':'))
    # Events that have passed since a page was read still drop out of its count.
    for p, v in pages.items():
        if v.get('x') and v['x'] < today:
            v['stale'] = True
    for p in list(pages):
        if p not in place and p not in guides and p not in parent_of:
            pages.pop(p)
    def all_links(g, seen=None):
        seen = seen if seen is not None else {g}
        gs = gstate.get(g) or {}
        out = set(gs.get('links', []))
        for sub in gs.get('subs', []):
            if sub not in seen:
                seen.add(sub)
                out |= all_links(sub, seen)
        return out

    gout = {}
    for p, g in guides.items():
        # only this guide's own cities (guides also link "nearby" cities in other states or countries)
        country = g['name'] if g['kind'] == 'country' else g.get('country', '')
        own = lambda q: (place.get(q) or {}).get('country') == country and (g['kind'] != 'state' or (place.get(q) or {}).get('state') in (p, None))
        links = sorted(q for q in all_links(p) if own(q))
        k, fk = set(), set()
        for q in links:
            v = pages.get(q) or {}
            k.update(v.get('k', [])); fk.update(v.get('fk', []))
        gout[p] = {'kind': g['kind'], 'name': g['name'], 'e': len(k), 'f': len(fk), 'c': len(links),
                   'cw': sum(1 for q in links if (pages.get(q) or {}).get('e'))}

    # Roll up: unique events (an event listed on two city pages counts once).
    def scoped(keys, scope):
        # Cards without an event-page link are keyed n:<name>|<town>|<last>. A city page and its district pages
        # name the town differently ("Praha" / "Praha 1"), so within one city the town is replaced by the city.
        return {('n:' + x[2:].split('|')[0] + '|' + scope + '|' + x.rsplit('|', 1)[-1]) if scope and x.startswith('n:') else x for x in keys}

    def roll(paths, scope=None):
        k, fk, e_cities, q = set(), set(), 0, 0
        for p in paths:
            v = pages.get(p)
            if not v:
                continue
            k |= scoped(v['k'], scope); fk |= scoped(v['fk'], scope); q += v.get('q', 0)
            e_cities += 1 if v['e'] else 0
        return {'events': len(k), 'free': len(fk), 'cities_with_events': e_cities, 'faq': q, '_k': k, '_fk': fk}

    cities = {}
    for p, pl in place.items():
        if pl['main'] != p:
            continue  # local-language twin of the same city: count the city once
        twins = [q for q, o in place.items() if o['main'] == p]
        best = max(twins, key=lambda q: (pages.get(q) or {}).get('e', 0))  # same as the hub: the fuller language version
        parts = sorted(q for q, par in parent_of.items() if par == p and (pages.get(q) or {}).get('up'))
        cities[p] = {'country': pl['country'], 'state': pl['state'], 'name': pl['name'], 'paths': twins, 'best': best, 'parts': parts, 'key': p}
    by_country, by_state = collections.defaultdict(list), collections.defaultdict(list)
    for p, c in cities.items():
        by_country[c['country']].append(c)
        if c['state']:
            by_state[c['state']].append(c)

    def agg(cs):
        # One language version per city (the fuller one): the English and local-language pages list the
        # same events, sometimes under different card ids, so taking both would count events twice.
        k, fk, qn, ew = set(), set(), 0, 0
        for c in cs:
            x = roll([c['best']] + c['parts'], c['key'] if c['parts'] else None)
            k |= x['_k']; fk |= x['_fk']; qn += x['faq']; ew += 1 if x['cities_with_events'] else 0
        r = {'events': len(k), 'free': len(fk), 'cities_with_events': ew, 'faq': qn}
        r['cities'] = len(cs)
        r['cities_with_events'] = sum(1 for c in cs if any((pages.get(q) or {}).get('e') for q in [c['best']] + c['parts']))
        return r

    total = agg(list(cities.values()))
    total['countries'] = len(by_country)
    # Merry Christmas language guides (one /merry-christmas/<language> page each)
    total['languages'] = len({u for u in re.findall(r'<loc>https://www\.rallytakesthetrain\.com/merry-christmas/([a-z-]+)</loc>', sm.decode('utf-8'))
                              if not u.startswith('blog-post-title')})
    truth = {
        'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'today': today,
        'total': total,
        'countries': {n: agg(cs) for n, cs in by_country.items()},
        'states': {s: agg(cs) for s, cs in by_state.items()},
        'cities': {p: {'n': c['name'], 'co': c['country'], 'st': c['state'], 'e': roll([c['best']] + c['parts'], c['key'] if c['parts'] else None)['events'],
                       'f': roll([c['best']] + c['parts'], c['key'] if c['parts'] else None)['free'], 'alt': [q for q in c['paths'] if q != p],
                       'hub': p not in missing} for p, c in sorted(cities.items())},
        'pages': pages, 'odd': odd, 'guide_pages': gstate, 'found': found,
    }
    # the country's main guide: the found guide with the most city pages
    for g, fg in sorted(found.get('guides', {}).items(), key=lambda x: len(x[1].get('cities', {})) + len(x[1].get('subs', {}))):
        if fg.get('kind') == 'country' and fg.get('country') in truth['countries']:
            truth['countries'][fg['country']].update({'cc': fg.get('cc', ''), 'guide': g, 'hub': 0})
    # Small file for the Worker: only what pages display.
    regions = collections.defaultdict(lambda: {'events': set(), 'free': set(), 'cities': 0, 'cities_with_events': 0})
    for p, c in cities.items():
        if c['country'] == 'United States' and c['state']:
            key = 'US-' + L.US_ABBR.get(c['state'].split('/')[-1], '')
        elif c['country'] == 'Canada' and p.rsplit('-', 1)[-1] in L.CA_PROV:
            key = 'CA-' + p.rsplit('-', 1)[-1].upper()
        else:
            continue
        g = regions[key]
        x = roll([c['best']] + c['parts'], c['key'] if c['parts'] else None)
        g['events'] |= x['_k']; g['free'] |= x['_fk']
        g['cities'] += 1
        g['cities_with_events'] += 1 if (pages.get(p) or {}).get('e') else 0
    live = {
        'generated': truth['generated'], 'today': today, 'total': total,
        'countries': truth['countries'], 'states': truth['states'],
        'regions': {k: {'events': len(v['events']), 'free': len(v['free']), 'cities': v['cities'], 'cities_with_events': v['cities_with_events']} for k, v in regions.items()},
        # path: [events, free, name, country, state path, in hub A to Z (1/0), other-language paths]
        'cities': {p: [c['e'], c['f'], c['n'], c['co'], c['st'] or '', 1 if c['hub'] else 0, c['alt']] for p, c in truth['cities'].items()},
        'pages': {p: [v['e'], v['f']] for p, v in pages.items() if not v.get('guide')},
        'guides': gout,
    }
    if total['cities'] < 0.9 * len(old.get('cities', {}) or {'x': 0}) - 5:
        raise SystemExit('city count dropped by more than 10%; not writing')
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    json.dump(truth, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    # live.json only changes when a displayed number changes (or the day changes), so the
    # Worker's healed-page cache stays valid between runs that found nothing new.
    live_path = os.path.join(HERE, 'live.json')
    prev = json.load(open(live_path, encoding='utf-8')) if os.path.exists(live_path) else {}
    strip = lambda d: {k: v for k, v in d.items() if k != 'generated'}
    if prev and strip(prev) == strip(live):
        live['generated'] = prev.get('generated', live['generated'])
    json.dump(live, open(live_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log(f"truth: {total['events']:,} events ({total['free']:,} free) in {total['cities']:,} cities "
        f"({total['cities_with_events']:,} with events) across {total['countries']} countries")


if __name__ == '__main__':
    main()
