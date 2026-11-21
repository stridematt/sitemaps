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
import urllib.parse
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

HUB_RAW = os.environ.get('RTT_HUB_RAW', 'https://rally-takes-the-train-site.squarespace.com')
GEO_PATH = os.path.join(HERE, 'geo.json')


def geocode(name, country, cc=''):
    """[lat, lng] of a city (2 decimals) from OpenStreetMap's Nominatim, or None. One request a second."""
    q = name if (name == country or not country or re.search(r'[^\x00-\x7f]', country)) else f'{name}, {country}'
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            'https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' + urllib.parse.quote(q)
            + (f'&countrycodes={cc.lower()}' if re.fullmatch(r'[A-Za-z]{2}', cc or '') else ''),   # "Jersey" is not Jersey County, Illinois
            headers={'User-Agent': 'rallytakesthetrain-counts/1.0 (hello@rallytakesthetrain.com)'}), timeout=30)
        j = json.loads(r.read())
        time.sleep(1.1)
        return [round(float(j[0]['lat']), 2), round(float(j[0]['lon']), 2)] if j else None
    except Exception:
        time.sleep(2)
        return None


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
from iso_names import ISO_NAMES
ISO_NAME = {**ISO_NAMES, **{v: k for k, v in L.ISO.items()}}


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
            r = urllib.request.urlopen(urllib.request.Request(SITE + path + ('&' if '?' in path else '?') + 'format=json', headers={**HDR, 'Accept-Encoding': 'gzip'}), timeout=90)
            b = r.read()
            return json.loads(gzip.decompress(b) if r.headers.get('Content-Encoding') == 'gzip' else b)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            time.sleep(8 * (i + 1) if e.code in (429, 503) else 3)
        except Exception:
            continue
    return None


THREADS = int(os.environ.get('RTT_THREADS', '16'))   # measured: the site answers 20 at once with no throttling


def pmap(fn, items):
    """fn over items, in parallel, results in order."""
    items = list(items)
    if len(items) < 2:
        return [fn(x) for x in items]
    with cf.ThreadPoolExecutor(min(THREADS, len(items))) as ex:
        return list(ex.map(fn, items))


def walk_slice(sl):
    """Posts of the Christmas events collection published in [lo, hi), newest first, as
    (path, publish time, title, body). The body is kept only where `keep(path, body)` says so:
    a list page holds 20 whole posts, and three days of them would not fit in memory."""
    hi, lo, keep = sl
    out, cur = [], hi
    for _ in range(400):
        j = item_json(f'/christmas-events?offset={cur}')
        items = (j or {}).get('items') or []
        if not items:
            break
        for it in items:
            if (it.get('publishOn') or 0) < lo:
                return out
            p, b = it.get('fullUrl', ''), it.get('body') or ''
            out.append((p, it.get('publishOn') or 0, it.get('title', ''), keep(p, b)))
        nxt = ((j.get('pagination') or {}).get('nextPageOffset')) or 0
        if not nxt or nxt >= cur:
            break
        cur = nxt
    return out


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
    want = set()   # pages that new posts name in their breadcrumbs (their country guide, their city page)

    def crumbs(body, self_path):
        out = []
        for blk in re.findall(r'"@type"\s*:\s*"BreadcrumbList".{0,3000}?\]', body, re.S):
            for u in re.findall(r'rallytakesthetrain\.com(/christmas-events/[a-z0-9-]+)', blk):
                u = u.rstrip('/')
                if u != self_path and u not in out:
                    out.append(u)
        return out

    def is_list(b):
        return '<li class="rtt-rc">' in b or 'class="rtt-rcs"' in b
    # How far back: six hours on most runs (bulk publishing stamps posts a little in the past), and three
    # days on the first run of each day as a safety net. Three days on every run meant re-reading about
    # 9,000 posts, 15 minutes of each run. A one-page country that later becomes a guide with city pages
    # is not missed in between: it is already a guide here, and guides are re-read once a day below.
    # Read in half-hour slices, in parallel.
    now = int(time.time() * 1000) + 3600000
    deep = found.get('deep') != today
    lo = (hw - (72 if deep else 6) * 3600000) if hw else now - 30 * 86400000
    found['deep'] = today

    def keep(p, b):   # ('list' | 'single', body) for a guide to crawl, ('up', parents) for the rest; None for known pages
        if not p or p in known_guides or p in known_places:
            return None
        up = crumbs(b, p)
        if is_list(b):
            return ('list', b)
        if '<section class="rtt-pe-ride' in b and not up:
            return ('single', b)   # cards and no parent page: a country that is one page (Gibraltar, The Gambia)
        return ('up', up)          # an event or city page: its breadcrumb names its country guide and its city page

    step, edges = 1800000, []
    t = now
    while t > lo:
        edges.append((t, max(lo, t - step), keep))
        t -= step
    seen_posts = set()
    for items in pmap(walk_slice, edges):
        for p, pub, title, k in items:
            if not p or p in seen_posts or pub > now:
                continue
            seen_posts.add(p)
            newest = max(newest, pub)
            if not k:
                continue
            if k[0] == 'list':
                if p not in guides or not guides[p].get('cities'):
                    roots.append((p, title, k[1]))
            elif k[0] == 'single':
                if p not in guides:
                    roots.append((p, title, k[1]))
            else:
                want.update(k[1])
    log(f'{len(seen_posts)} posts published since {datetime.datetime.fromtimestamp(lo / 1000, datetime.timezone.utc):%b %d %H:%M} UTC read in {len(edges)} slices')
    found['hw'] = newest
    # Guides published before the walk reached them (or in a list format the walk didn't know yet): tools/truth/guide-seed.txt
    seed = os.path.join(HERE, 'guide-seed.txt')
    if os.path.exists(seed):
        sg = [g for g in dict.fromkeys(l.strip() for l in open(seed, encoding='utf-8'))
              if g.startswith('/christmas-events/') and g not in known_guides and g not in [r[0] for r in roots]]   # re-read every run
        for g, j in zip(sg, pmap(item_json, sg)):
            if j and j.get('item'):
                roots.append((g, j['item'].get('title', ''), j['item'].get('body') or ''))
    # Pages the new posts point up to that nothing knows yet: read them, and their own parents (3 levels at most)
    have = lambda g: g in known_guides or g in guides or g in known_places or g in [r[0] for r in roots]
    for _ in range(3):
        nxt, todo = set(), sorted(g for g in want if not have(g))[:150]
        for g, j in zip(todo, pmap(item_json, todo)):
            b = ((j or {}).get('item') or {}).get('body') or ''
            if not b:
                continue
            up = crumbs(b, g)
            if is_list(b) or ('<section class="rtt-pe-ride' in b and not up):
                roots.append((g, j['item'].get('title', ''), b))
            else:
                nxt.update(up)
        want = nxt
        if not want:
            break
    # re-crawl guides found earlier once a day (they gain cities as they are built out)
    # (v != 3: filed before the country/region test and the naming by country code were fixed; read again once)
    again = [g for g, v in guides.items() if (v.get('at', '') < today and v.get('kind') == 'country') or v.get('v') != 3]
    for g, j in zip(again, pmap(item_json, again)):
        if j and j.get('item'):
            roots.append((g, j['item'].get('title', ''), j['item'].get('body') or ''))
    sub_of = {s: g for g, v in guides.items() for s in v.get('subs', {})}
    for root, title, body in roots:
        if root in sub_of:
            continue
        cities, subs, seen = {}, {}, {root}
        queue = [(root, body, None)]
        while queue:   # one level at a time, each level's pages read in parallel
            ask = []
            for path, b, parent in queue:
                for q, name in linked_cities(b, path).items():
                    if q in seen or q in known_guides:
                        continue
                    seen.add(q)
                    if q in known_places:
                        cities[q] = name
                        continue
                    ask.append((q, name, path))
            queue = []
            for (q, name, path), j in zip(ask, pmap(item_json, [x[0] for x in ask])):
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
        # The name comes from the country code first: a guide's title is a sentence, and its Thai, Russian or
        # Arabic version must land in the same country, not start a second one under a translated name.
        tm0 = re.search(r'(?i)(?:for kids |with kids |Christmas )in (.+?)\s*(?:\(?20\d\d\)?)?\s*(?::.*)?$', title.strip())
        country = code2name.get(cc) or ISO_NAME.get(cc) or (plain(ld.group(1)) if ld else '') or (tm0.group(1).strip() if tm0 else re.sub(r'\s*\(\d{4}\)\s*$', '', title))
        single = not cities and '<section class="rtt-pe-ride' in body   # the country is this one page; its cards count as its city
        if single:
            cc = own_country(body) or collections.Counter(re.findall(r'href="/christmas-events/[a-z0-9-]+-([a-z]{2})"', body)).most_common(1)[0:1] and collections.Counter(re.findall(r'href="/christmas-events/[a-z0-9-]+-([a-z]{2})"', body)).most_common(1)[0][0].upper() or ''
            tm = re.search(r'(?i)(?:for kids |with kids |Christmas )in (.+?)\s*(?:\(?20\d\d\)?)?\s*(?::.*)?$', title.strip())
            country = code2name.get(cc) or ISO_NAME.get(cc) or (tm.group(1).strip() if tm else re.sub(r'\s*\(\d{4}\)\s*$', '', title))
        if not cities and not single:
            continue
        # A country guide has no parent page in its breadcrumb; a state or region guide has its country's guide.
        # (The country code alone is not enough: once the hub lists a new country, its code is "known", and the
        # country's own guide would turn into a region and drop off the hub again on the next run.)
        kind = 'region' if cc in code2name and not single and (crumbs(body, root) or not (ld or plain(code2name[cc]).lower() in plain(title).lower())) else 'country'
        guides[root] = {'kind': kind, 'name': country if kind == 'country' else re.sub(r'\s*\(\d{4}\)\s*$', '', title),
                        'country': country, 'cc': cc, 'cities': cities, 'subs': subs, 'at': today, 'v': 3}
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
    keys_before = {p: sorted(v.get('k', [])) for p, v in pages.items()}   # to tell which pages' events changed this run

    # The hub as stored in Squarespace, never the copy the Worker has already written this job's last numbers
    # into: reading our own output back made districts return as cities and new countries flip to regions.
    _, hb = L.get(HUB_RAW + '/christmas-events-for-kids')
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
    # The registry of discovered guides is kept in the repo too (found.json): the job's saved state can be
    # lost, and a cold start would otherwise forget every country the hub does not list yet.
    fpath = os.path.join(HERE, 'found.json')
    prev_found = old.get('found') or {}
    if not prev_found.get('guides') and os.path.exists(fpath):
        prev_found = json.load(open(fpath, encoding='utf-8'))
        log(f"saved state had no discovered guides: starting from found.json ({len(prev_found.get('guides', {}))} guides)")
    found = discover_guides(guides, place, code2name, prev_found, today, log)
    json.dump(found, open(fpath, 'w', encoding='utf-8'), ensure_ascii=False, sort_keys=True, indent=0)
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
    # A district page that a guide or the hub lists as if it were a city (Madrid's barrios on the Spain guide; the
    # healed hub then lists whatever the last run counted as a city) is still a district. Such a page stays a
    # candidate until it is read: it is a district when it links back to its city page.
    cand = {}
    for q in re.findall(r'<loc>https://www\.rallytakesthetrain\.com(/christmas-events/[a-z0-9-]+)</loc>', sm.decode('utf-8')):
        if q in guides or q in odd:
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
            if par == q or place[par]['main'] == (place.get(q) or {}).get('main'):
                continue   # itself, or another language version of the same city
            if DISTRICT.match(rest) or prefixed:
                if q in place:
                    if place[q].get('country') == place[par].get('country'):   # madrid-cundinamarca is Colombia, not a barrio
                        cand[q] = place[par]['main']
                else:
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
    with cf.ThreadPoolExecutor(THREADS) as ex:
        for p, (st, h) in zip(todo, ex.map(fetch, todo)):
            if st == 200 and h and p in guides:
                hrefs = set(re.findall(r'href="(/christmas-events/[a-z0-9-]+)(?:#[^"]*)?"', h))
                links = sorted(hrefs & set(place))
                cities = linked_cities(h, p)
                gstate[p] = {'links': links, 'subs': sorted(q for q in (set(cities) & set(guides)) if q != p), 'cities': sorted(cities), 'names': cities, 'lang': (re.search(r'<html[^>]*\blang="([^"]+)"', h) or [None, ''])[1], 'lastmod': lastmod.get(p), 'at': today}
                sq_ids[p] = item_id(h) or sq_ids.get(p)
                pages.setdefault(p, {}).update({'guide': True, 'lastmod': lastmod.get(p), 'at': today, 'e': 0, 'f': 0, 'k': [], 'fk': [], 'x': None})
                if '<section class="rtt-pe-ride' in h:   # a guide that is also a city page (Washington, DC): its cards count
                    r = analyze(h, today)
                    pages[p].update({'e': r['events'], 'f': r['free'], 'x': r['next_expiry'], 'c': r['checked'], 'q': r['faq'],
                                     'k': r['keys'], 'fk': r['free_keys'], 'sg': r.get('sigs', []), 'cards': True})
            elif st == 200 and h:
                r = analyze(h, today)
                sq_ids[p] = r['sq'] or sq_ids.get(p)
                pages[p] = {'e': r['events'], 'f': r['free'], 'x': r['next_expiry'], 'c': r['checked'], 'q': r['faq'],
                            'k': r['keys'], 'fk': r['free_keys'], 'sg': r.get('sigs', []), 'lang': r['lang'], 'co': own_country(h), 'lastmod': lastmod.get(p), 'at': today}
                if p in parent_of:  # a district page links back to its city (any language version)
                    ups = {q for q, o in place.items() if o['main'] == parent_of[p]}
                    pages[p]['up'] = any(f'href="{u}"' in h or f'href="{u}#' in h for u in ups)
                elif p in cand:
                    # Listed as a city: only a district if its own breadcrumb runs through the city page
                    # (Spain > Madrid > Retiro). A link alone is not enough: Sao Jose de Ribamar links to Sao Jose.
                    ups = {q for q, o in place.items() if o['main'] == cand[p]}
                    crumbs = set()
                    for blk in re.findall(r'"@type"\s*:\s*"BreadcrumbList".{0,3000}?\]', h, re.S):
                        crumbs |= {u.rstrip('/') for u in re.findall(r'https://www\.rallytakesthetrain\.com(/christmas-events/[a-z0-9-]+)', blk)}
                    pages[p]['up'] = bool(crumbs & ups)
            elif st in (404, 410):
                pages.pop(p, None)
            else:
                failed += 1
    if failed:
        log(f'{failed} pages could not be read; their last known counts are kept')
    moved = [q for q, par in cand.items() if (pages.get(q) or {}).get('up') and q in place and place[q]['main'] == q]
    for q in moved:
        del place[q]
        parent_of[q] = cand[q]
    if moved:
        log(f'{len(moved)} pages listed as cities are districts of a city (they link back to it): {sorted(moved)[:14]}')
    for g, gi in guides.items():
        v = pages.get(g) or {}
        if v.get('cards') and g not in place:
            country = gi['name'] if gi['kind'] == 'country' else gi.get('country', '')
            place[g] = {'country': country, 'state': g if gi['kind'] == 'state' and country == 'United States' else None,
                        'name': re.sub(r'^Christmas Events for Kids in |\s*\(\d{4}\)$', '', gi.get('name', '')) or gi.get('name', ''), 'main': g}
            log(f'guide page with its own event cards counted as a city too: {g} ({v.get("e", 0)} events)')
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
    # The same event in two language versions of a city page (English and French Paris) has two cards and often
    # two event pages. Cards with the same place and dates are one event: every key maps to one canonical key.
    canon, by_sig = {}, collections.defaultdict(lambda: collections.defaultdict(list))
    for pg, v in pages.items():
        for x, sg in zip(v.get('k', []), v.get('sg', [])):
            if sg and x not in by_sig[sg][pg]:
                by_sig[sg][pg].append(x)
    merged = 0
    for per_page in by_sig.values():
        if len(per_page) < 2:
            continue
        # Only cards on different pages merge: two cards on one page with the same link and dates are two events.
        # The page with the most such cards sets the events; the others' cards map onto them one to one.
        base = sorted(max(per_page.values(), key=len))
        for ks in per_page.values():
            for x, y in zip(sorted(ks), base):
                if x != y and canon.get(x, x) == x:
                    canon[x] = y
                    merged += 1
    log(f'{merged} cards are another language version (or another page) of an event already counted')
    C = lambda keys: [canon.get(x, x) for x in keys]

    for p, g in guides.items():
        # only this guide's own cities (guides also link "nearby" cities in other states or countries)
        country = g['name'] if g['kind'] == 'country' else g.get('country', '')
        own = lambda q: (place.get(q) or {}).get('country') == country and (g['kind'] != 'state' or (place.get(q) or {}).get('state') in (p, None))
        links = sorted(q for q in all_links(p) if own(q))
        k, fk = set(), set()
        for q in links:
            v = pages.get(q) or {}
            k.update(C(v.get('k', []))); fk.update(C(v.get('fk', [])))
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
            k |= scoped(C(v['k']), scope); fk |= scoped(C(v['fk']), scope); q += v.get('q', 0)
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
        # Every language version of a city counts (an event only on the French Paris page is still an event);
        # the same event on both versions counts once (canonical keys above). FAQs come from one version.
        k, fk, qn, ew = set(), set(), 0, 0
        for c in cs:
            x = roll(c['paths'] + c['parts'], c['key'] if c['parts'] else None)
            k |= x['_k']; fk |= x['_fk']; qn += roll([c['best']] + c['parts'])['faq']
        r = {'events': len(k), 'free': len(fk), 'cities_with_events': ew, 'faq': qn, '_k': k}
        r['cities'] = len(cs)
        r['cities_with_events'] = sum(1 for c in cs if any((pages.get(q) or {}).get('e') for q in c['paths'] + c['parts']))
        return r

    total = agg(list(cities.values()))
    counted = total.pop('_k')
    total['countries'] = len(by_country)
    # Merry Christmas language guides (one /merry-christmas/<language> page each)
    total['languages'] = len({u for u in re.findall(r'<loc>https://www\.rallytakesthetrain\.com/merry-christmas/([a-z-]+)</loc>', sm.decode('utf-8'))
                              if not u.startswith('blog-post-title')})
    nok = lambda r: {k: v for k, v in r.items() if k != '_k'}
    # Every event the site counts, by event page (cards without a page link are counted by name). The events
    # directory compares its live pages against this list, so the database and the site agree on one number.
    with open(os.path.join(HERE, 'counted_events.json'), 'w', encoding='utf-8') as fh:
        json.dump({'today': today, 'events': len(counted),
                   'pages': sorted({x.rstrip('/').rsplit('/', 1)[-1] for x in counted if not x.startswith('n:')}),
                   'by_name': sum(1 for x in counted if x.startswith('n:')),
                   # upcoming event pages carded on any city page, every language version included (the counts take
                   # one language version per city, so a page here but not in "pages" is on the other version)
                   'listed': sorted({x.rstrip('/').rsplit('/', 1)[-1] for v in pages.values() for x in v.get('k', []) if not x.startswith('n:')})}, fh, ensure_ascii=False, separators=(',', ':'))
    truth = {
        'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'today': today,
        'total': total,
        'countries': {n: nok(agg(cs)) for n, cs in by_country.items()},
        'states': {s: nok(agg(cs)) for s, cs in by_state.items()},
        'cities': {p: {'n': c['name'], 'co': c['country'], 'st': c['state'], 'e': roll(c['paths'] + c['parts'], c['key'] if c['parts'] else None)['events'],
                       'f': roll(c['paths'] + c['parts'], c['key'] if c['parts'] else None)['free'], 'alt': [q for q in c['paths'] if q != p],
                       'hub': p not in missing} for p, c in sorted(cities.items())},
        'pages': pages, 'odd': odd, 'guide_pages': gstate, 'found': found,
    }
    # the country's main guide: the found guide with the most city pages
    for g, fg in sorted(found.get('guides', {}).items(), key=lambda x: len(x[1].get('cities', {})) + len(x[1].get('subs', {}))):
        if fg.get('kind') == 'country' and fg.get('country') in truth['countries']:
            truth['countries'][fg['country']].update({'cc': fg.get('cc', ''), 'guide': g, 'hub': 0})
    # Where each city the stored hub does not have is, so the Worker can light it on the hub's map.
    geo = json.load(open(GEO_PATH, encoding='utf-8')) if os.path.exists(GEO_PATH) else {}
    looked = 0
    for p, c in truth['cities'].items():
        if c['hub'] or p in geo or looked >= 150:
            continue
        looked += 1
        m2 = re.search(r'-([a-z]{2})$', p)
        ll = geocode(c['n'], c['co'], (truth['countries'].get(c['co']) or {}).get('cc') or (m2.group(1) if m2 and m2.group(1).upper() in ISO_NAME or m2 and c['co'] != 'United States' else ''))
        if ll:
            geo[p] = ll
    if looked:
        json.dump(geo, open(GEO_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=0, sort_keys=True)
        log(f'looked up where {looked} new cities are; {len(geo)} known')
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
        x = roll(c['paths'] + c['parts'], c['key'] if c['parts'] else None)
        g['events'] |= x['_k']; g['free'] |= x['_fk']
        g['cities'] += 1
        g['cities_with_events'] += 1 if (pages.get(p) or {}).get('e') else 0
    live = {
        'generated': truth['generated'], 'today': today, 'total': total,
        'countries': truth['countries'], 'states': truth['states'],
        'regions': {k: {'events': len(v['events']), 'free': len(v['free']), 'cities': v['cities'], 'cities_with_events': v['cities_with_events']} for k, v in regions.items()},
        # path: [events, free, name, country, state path, in hub A to Z (1/0), other-language paths]
        # [events, free, name, country, state, on the stored hub, other language pages, lat, lng (cities the hub's map does not have)]
        'cities': {p: [c['e'], c['f'], c['n'], c['co'], c['st'] or '', 1 if c['hub'] else 0, c['alt']] + (geo.get(p) or [])
                   for p, c in truth['cities'].items()},
        'pages': {p: [v['e'], v['f']] for p, v in pages.items() if not v.get('guide')},
        'guides': gout,
    }
    if total['cities'] < 0.9 * len(old.get('cities', {}) or {'x': 0}) - 5:
        raise SystemExit('city count dropped by more than 10%; not writing')
    # The same for events and countries against the numbers now live: a bad read or a bug must never publish low counts.
    was = (json.load(open(os.path.join(HERE, 'live.json'), encoding='utf-8')) if os.path.exists(os.path.join(HERE, 'live.json')) else {}).get('total') or {}
    for k, floor in (('events', 0.9), ('countries', 0.9), ('cities_with_events', 0.85)):
        if was.get(k) and total[k] < floor * was[k] and not os.environ.get('RTT_ALLOW_DROP'):
            raise SystemExit(f"{k} dropped from {was[k]:,} to {total[k]:,}; not writing (run again with RTT_ALLOW_DROP=1 if this is real)")
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    json.dump(truth, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    # live.json only changes when a displayed number changes (or the day changes), so the
    # Worker's healed-page cache stays valid between runs that found nothing new.
    live_path = os.path.join(HERE, 'live.json')
    prev = json.load(open(live_path, encoding='utf-8')) if os.path.exists(live_path) else {}
    # Pages whose shown content changed since the last run (their events, or the numbers the Worker writes into
    # them): sent to IndexNow by the workflow, because Squarespace's sitemap dates lag behind edits by days.
    ch = set()
    if prev:
        ch = {p for p, v in live['pages'].items() if (prev.get('pages') or {}).get(p) != v}
        ch |= {p for p, v in live['cities'].items() if ((prev.get('cities') or {}).get(p) or [None, None])[:2] != v[:2]}
        ch |= {p for p, v in live['guides'].items() if (prev.get('guides') or {}).get(p) != v}
        for p, v in pages.items():   # same number of events but different events
            if p in keys_before and not v.get('guide') and keys_before[p] != sorted(v.get('k', [])):
                ch.add(p)
        if prev.get('total') != live['total']:
            ch.add('/christmas-events-for-kids')
    # mod: the day each page's shown content last really changed (new or different events, events passing,
    # new counts). The Worker writes it as the page's dateModified, so dates move only when the page does
    # (Google: update the date only for real changes). A page first seen takes its sitemap date.
    pmod = prev.get('mod') or {}
    live['mod'] = {}
    for p in sorted(set(live['pages']) | set(live['guides']) | {'/christmas-events-for-kids'}):
        if p in ch:
            live['mod'][p] = today
        elif p in pmod:
            live['mod'][p] = pmod[p]
        else:
            seed = ((pages.get(p) or {}).get('lastmod') or '')[:10]
            live['mod'][p] = min(seed, today) if re.match(r'\d{4}-\d\d-\d\d$', seed) else today
    strip = lambda d: {k: v for k, v in d.items() if k != 'generated'}
    if prev and strip(prev) == strip(live):
        live['generated'] = prev.get('generated', live['generated'])
    json.dump(live, open(live_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    if prev:
        with open(os.path.join(os.path.dirname(out_path) or '.', 'changed-pages.txt'), 'w', encoding='utf-8') as fh:
            fh.write('\n'.join('https://www.rallytakesthetrain.com' + p for p in sorted(ch)))
        log(f'{len(ch)} pages changed since the last run')
    log(f"truth: {total['events']:,} events ({total['free']:,} free) in {total['cities']:,} cities "
        f"({total['cities_with_events']:,} with events) across {total['countries']} countries")


if __name__ == '__main__':
    main()
