#!/usr/bin/env python3
"""Build tools/truth/truth.json: what the Christmas events pages actually contain.

Every city guide is read for its event cards (dates and free flags), past events are
dropped, and the result is rolled up by state, country and for the whole hub. Pages are
only re-read when Squarespace says they changed (sitemap lastmod), when one of their
events has passed, or once a week, so a normal run reads a few dozen pages.

The Cloudflare Worker reads truth.json to keep every number on the hub, country and
state pages right, and to list city guides the hub's A to Z has not picked up yet.
"""
import argparse, collections, concurrent.futures as cf, datetime, gzip, json, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import analyze

SITE = 'https://www.rallytakesthetrain.com'
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
sys.path.insert(0, os.path.join(ROOT, 'tools', 'llms'))
import build_llms as L  # hub parser, ISO codes, English city guide pattern


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fetch(path, tries=2):
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
        except Exception:
            pass
        time.sleep(3)
    return 0, ''


def ref_today():
    # An event stays listed until its last day is over everywhere (UTC-12).
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=12)).date().isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=1500, help='most pages to read this run')
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
                guides[g['state'][0]] = {'kind': 'state', 'name': g['state'][1]}
    gstate = old.get('guide_pages', {})

    # What to (re)read
    due = []
    for p in list(place) + list(guides):
        prev = pages.get(p)
        if not prev:
            due.append((0, p))
        elif prev.get('lastmod') != lastmod.get(p):
            due.append((1, p))
        elif prev.get('x') and prev['x'] < today:
            due.append((2, p))
        elif prev.get('at', '') < (datetime.date.fromisoformat(today) - datetime.timedelta(days=7)).isoformat():
            due.append((3, p))
    due.sort()
    todo = [p for _, p in due[:args.max]]
    log(f'{len(place)} city guide pages ({len(missing)} cities not in the hub A to Z); reading {len(todo)} of {len(due)} due')
    if odd:
        log(f'pages that look like leftover copies: {odd}')
    failed = 0
    with cf.ThreadPoolExecutor(8) as ex:
        for p, (st, h) in zip(todo, ex.map(fetch, todo)):
            if st == 200 and h and p in guides:
                links = sorted(set(re.findall(r'href="(/christmas-events/[a-z0-9-]+)(?:#[^"]*)?"', h)) & set(place))
                gstate[p] = {'links': links, 'lang': (re.search(r'<html[^>]*\blang="([^"]+)"', h) or [None, ''])[1], 'lastmod': lastmod.get(p), 'at': today}
                pages.setdefault(p, {}).update({'guide': True, 'lastmod': lastmod.get(p), 'at': today, 'e': 0, 'f': 0, 'k': [], 'fk': [], 'x': None})
            elif st == 200 and h:
                r = analyze(h, today)
                pages[p] = {'e': r['events'], 'f': r['free'], 'x': r['next_expiry'], 'c': r['checked'], 'q': r['faq'],
                            'k': r['keys'], 'fk': r['free_keys'], 'lang': r['lang'], 'lastmod': lastmod.get(p), 'at': today}
            elif st in (404, 410):
                pages.pop(p, None)
            else:
                failed += 1
    if failed:
        log(f'{failed} pages could not be read; their last known counts are kept')
    # Events that have passed since a page was read still drop out of its count.
    for p, v in pages.items():
        if v.get('x') and v['x'] < today:
            v['stale'] = True
    for p in list(pages):
        if p not in place and p not in guides:
            pages.pop(p)
    gout = {}
    for p, g in guides.items():
        links = (gstate.get(p) or {}).get('links', [])
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
        r = roll([q for c in cs for q in c['paths']])
        r['cities'] = len(cs)
        r['cities_with_events'] = sum(1 for c in cs if (pages.get(c['best']) or {}).get('e'))
        return r

    total = agg(list(cities.values()))
    total['countries'] = len(by_country)
    truth = {
        'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'today': today,
        'total': total,
        'countries': {n: agg(cs) for n, cs in by_country.items()},
        'states': {s: agg(cs) for s, cs in by_state.items()},
        'cities': {p: {'n': c['name'], 'co': c['country'], 'st': c['state'], 'e': (pages.get(c['best']) or {}).get('e', 0),
                       'f': (pages.get(c['best']) or {}).get('f', 0), 'alt': [q for q in c['paths'] if q != p],
                       'hub': p not in missing} for p, c in sorted(cities.items())},
        'pages': pages, 'odd': odd, 'guide_pages': gstate,
    }
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
        for q in c['paths']:
            v = pages.get(q) or {}
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
