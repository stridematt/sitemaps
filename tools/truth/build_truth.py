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
sys.path.insert(0, os.path.join(ROOT, 'tools', 'llms'))
import build_llms as L  # hub parser, ISO codes, English city guide pattern


def log(*a):
    print(*a, file=sys.stderr, flush=True)


RC = re.compile(r'<li class="rtt-rc">(?:(?!</li>).){0,3000}?href="(/christmas-events/[a-z0-9-]+)"[^>]*>(?:<[^>]+>)*([^<]{1,80})', re.S)
SEC = re.compile(r'<h2 id="city-[^"]*"[^>]*>([^<]{1,80})(?:(?!<h2\b).){0,4000}?href="(/christmas-events/[a-z0-9-]+)', re.S)


def linked_cities(h, self_path=None):
    """City pages a guide lists: its city cards and its city sections (path -> shown name)."""
    out = {}
    for m in RC.finditer(h):
        out.setdefault(m.group(1), m.group(2).strip())
    for m in SEC.finditer(h):
        out.setdefault(m.group(2), m.group(1).strip())
    out.pop(self_path, None)
    return out


def item_json(path):
    """A post's Squarespace JSON (body, title, id), or None."""
    for i in range(5):
        try:
            r = urllib.request.urlopen(urllib.request.Request(SITE + path + ('&' if '?' in path else '?') + 'format=json', headers={'User-Agent': UA}), timeout=60)
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
            if p in known_guides or p in guides or p in known_places or '<section class="rtt-pe-ride"' in b:
                continue
            if '<li class="rtt-rc">' in b:
                roots.append((p, it.get('title', ''), b))
        nxt = (j.get('pagination') or {}).get('nextPageUrl')
        if stop or not nxt:
            break
        url = nxt
    found['hw'] = newest
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
                if '<section class="rtt-pe-ride"' in qb or ('<li class="rtt-rc">' not in qb and qb):
                    cities[q] = name
                elif '<li class="rtt-rc">' in qb:
                    subs[q] = {'name': name}
                    queue.append((q, qb, path))
        codes = collections.Counter(c.rsplit('-', 1)[-1].upper() for c in cities if re.search(r'-[a-z]{2}$', c))
        cc = codes.most_common(1)[0][0] if codes else ''
        ld = re.search(r'"@type":\s*"Country",\s*"name":\s*"([^"]+)"', body)
        country = code2name.get(cc) or (plain(ld.group(1)) if ld else '') or re.sub(r'\s*\(\d{4}\)\s*$', '', title)
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
            r = urllib.request.urlopen(urllib.request.Request(SITE + path, headers={'User-Agent': UA, 'Accept-Encoding': 'gzip'}), timeout=60)
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
        for q, name in fg.get('cities', {}).items():
            place.setdefault(q, {'country': fg['country'], 'state': None, 'name': clean_name(name, q), 'main': q})
    gstate = old.get('guide_pages', {})
    # New city pages a country or state guide links to (its city cards and city sections) count too,
    # even before the hub lists them. They are picked up from the last read of each guide.
    added = []
    for g, gs in gstate.items():
        gi = guides.get(g)
        if not gi:
            continue
        for q in gs.get('cities', []):
            if q in place or q in guides or q in odd or 'duplicate' in q:
                continue
            country = gi['name'] if gi['kind'] == 'country' else gi.get('country', '')
            place[q] = {'country': country, 'state': g if gi['kind'] == 'state' and country == 'United States' else None,
                        'name': clean_name(gs.get('names', {}).get(q) or '', q), 'main': q}
            added.append(q)
    if added:
        log(f'{len(added)} city pages found through guides that the hub does not list yet: {added[:10]}')

    # What to (re)read
    # Every page is read every run: Squarespace's sitemap dates lag behind edits, so a page that
    # changed would otherwise keep its old count for days. New and changed pages go first.
    due = []
    for p in list(place) + list(guides):
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
                            'k': r['keys'], 'fk': r['free_keys'], 'lang': r['lang'], 'lastmod': lastmod.get(p), 'at': today}
            elif st in (404, 410):
                pages.pop(p, None)
            else:
                failed += 1
    if failed:
        log(f'{failed} pages could not be read; their last known counts are kept')
    # Squarespace post ids for the sync (path -> id), kept for pages that still exist
    sq_ids = {p: i for p, i in sq_ids.items() if i and (p in place or p in guides)}
    os.makedirs(os.path.dirname(ids_path), exist_ok=True)
    json.dump(dict(sorted(sq_ids.items())), open(ids_path, 'w', encoding='utf-8'), indent=0, separators=(',', ':'))
    # Events that have passed since a page was read still drop out of its count.
    for p, v in pages.items():
        if v.get('x') and v['x'] < today:
            v['stale'] = True
    for p in list(pages):
        if p not in place and p not in guides:
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
    def roll(paths):
        k, fk, e_cities, q = set(), set(), 0, 0
        for p in paths:
            v = pages.get(p)
            if not v:
                continue
            k.update(v['k']); fk.update(v['fk']); q += v.get('q', 0)
            e_cities += 1 if v['e'] else 0
        return {'events': len(k), 'free': len(fk), 'cities_with_events': e_cities, 'faq': q}

    cities = {}
    for p, pl in place.items():
        if pl['main'] != p:
            continue  # local-language twin of the same city: count the city once
        twins = [q for q, o in place.items() if o['main'] == p]
        best = max(twins, key=lambda q: (pages.get(q) or {}).get('e', 0))  # same as the hub: the fuller language version
        cities[p] = {'country': pl['country'], 'state': pl['state'], 'name': pl['name'], 'paths': twins, 'best': best}
    by_country, by_state = collections.defaultdict(list), collections.defaultdict(list)
    for p, c in cities.items():
        by_country[c['country']].append(c)
        if c['state']:
            by_state[c['state']].append(c)

    def agg(cs):
        # One language version per city (the fuller one): the English and local-language pages list the
        # same events, sometimes under different card ids, so taking both would count events twice.
        r = roll([c['best'] for c in cs])
        r['cities'] = len(cs)
        r['cities_with_events'] = sum(1 for c in cs if (pages.get(c['best']) or {}).get('e'))
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
        'cities': {p: {'n': c['name'], 'co': c['country'], 'st': c['state'], 'e': (pages.get(c['best']) or {}).get('e', 0),
                       'f': (pages.get(c['best']) or {}).get('f', 0), 'alt': [q for q in c['paths'] if q != p],
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
        v = pages.get(c['best']) or {}
        g['events'].update(v.get('k', [])); g['free'].update(v.get('fk', []))
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
