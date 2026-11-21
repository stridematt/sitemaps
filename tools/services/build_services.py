"""Build tools/services/live_services.json: what the Christmas Eve services pages actually list.

Reads every page of the Christmas Eve services collections in the sitemap (about 2,400), then:
  - a city page (data-cev="<slug>" and listed by a guide or the hub) counts its churches (ItemList Church
    items) and the churches with 2026 times (a Church that is the location of an Event dated 2026-12);
  - a denomination page (data-cev, not listed anywhere, slug = <city page>-<denomination>) adds its churches
    to its city (a church is counted once: name + street + town);
  - a guide (country, state, province, region, county) lists its cities and sub-guides (ItemList URLs).
Rolls up city -> guide -> country -> hub. The rtt-hreflang Worker reads this file to keep every number on
the services hub, guide pages and city pages true (worker/src/services.js).

Usage: python3 tools/services/build_services.py [--max 5000] [--threads 6]
"""
import argparse, collections, concurrent.futures as cf, datetime, html as H, json, os, re, sys, time, unicodedata, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, 'live_services.json')
SITE = 'https://www.rallytakesthetrain.com'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
HDR = {'User-Agent': UA, **({'x-rtt-key': os.environ['RTT_BOT_KEY']} if os.environ.get('RTT_BOT_KEY') else {})}
# Squarespace's own host answers ?format=json without the Worker in between (and without bot protection).
SQS = os.environ.get('RTT_SQS_HOST', 'https://rally-takes-the-train-site.squarespace.com')
COLLECTIONS = ['christmas-eve-services', 'christmas-eve-services-canada', 'christmas-eve-services-uk', 'christmas-eve-services-australia',
               'christmas-eve-services-in-ireland', 'christmas-eve-reihai-japan', 'gottesdienste-heiligabend-deutschland',
               'misa-de-nochebuena-mexico', 'pasterka-wigilia-polska', 'slujbe-de-craciun-romania', 'misa-del-gallo-espana',
               'messes-de-noel-france', 'missa-do-galo-brasil', 'messes-de-noel-quebec-canada', 'messe-vigilia-di-natale-italia']
HUB = '/christmas-eve-services-near-me'
CHURCH = re.compile(r'Church$|^Cathedral|Chapel|Place$|PlaceOfWorship|Mosque$')


def get(url, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return e.code, ''
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 + 3 * i)
                continue
            return e.code, ''
        except Exception:
            time.sleep(2 + 3 * i)
    return 0, ''


def page(path):
    st, t = get(SQS + path + '?format=json')
    if st != 200 or not t:
        return st, None
    try:
        d = json.loads(t)
    except Exception:
        return 0, None
    it = d.get('item') or {}
    return 200, {'title': it.get('title') or '', 'body': it.get('body') or d.get('mainContent') or '', 'id': it.get('id')}


def norm(s):
    s = unicodedata.normalize('NFKD', H.unescape(s or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def graphs(body):
    out = []
    for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', body, re.S):
        try:
            d = json.loads(x)
        except Exception:
            continue
        for n in (d.get('@graph') or [d]) if isinstance(d, dict) else d:
            if isinstance(n, dict):
                out.append(n)
    return out


def church_key(c):
    a = c.get('address') or {}
    if isinstance(a, list):
        a = a[0] if a else {}
    return '|'.join([norm(c.get('name')), norm(a.get('streetAddress') if isinstance(a, dict) else ''), norm(a.get('addressLocality') if isinstance(a, dict) else '')])


HREF = re.compile(r'href="(?:https?://(?:www\.)?rallytakesthetrain\.com)?/(' + '|'.join(map(re.escape, COLLECTIONS)) + r')/([a-z0-9][a-z0-9-]*)/?["#?]')


def analyze(path, body):
    """Listing page (city or denomination) or guide."""
    cev = re.search(r'data-cev="([^"]+)"', body)
    ns = graphs(body)
    churches, timed, links, desc = set(), set(), [], {}
    for n in ns:
        if n.get('@type') == 'ItemList':
            for li in n.get('itemListElement') or []:
                it = li.get('item') if isinstance(li.get('item'), dict) else None
                if it and CHURCH.search(str(it.get('@type', ''))):
                    k = church_key(it)
                    churches.add(k)
                    desc[k] = norm(' '.join(str(x) for x in (it.get('description'), it.get('@type')) if x))   # the label, e.g. "Anglican church", "Eglise catholique", "Kirche evangelisch"
                elif li.get('url') or (isinstance(li.get('item'), str)):
                    u = li.get('url') or li.get('item')
                    links.append(re.sub(r'^https?://[^/]+', '', u).split('#')[0].rstrip('/'))
    for n in ns:
        if n.get('@type') in ('Event', 'EventSeries') and str(n.get('startDate', '')).startswith('2026-12'):
            loc = n.get('location')
            loc = loc[0] if isinstance(loc, list) and loc else loc
            if isinstance(loc, dict):
                k = church_key(loc)
                if k in churches:
                    timed.add(k)
                else:   # same church written differently (no street on the Event): match by name and town
                    nm, tw = k.split('|')[0], k.split('|')[2]
                    hit = next((c for c in churches if c.split('|')[0] == nm and (not tw or c.split('|')[2] == tw)), None)
                    if hit:
                        timed.add(hit)
    hrefs = {'/%s/%s' % m for m in HREF.findall(body)}
    return {'_hrefs': hrefs, 'cev': cev.group(1) if cev else None, 'churches': sorted(churches), 'timed': sorted(timed), 'links': links, 'desc': desc}


DENOMS = {   # a denomination guide's slug word -> words that mark that tradition in a church's label, in every site language
    'anglican': ['anglican', 'church of england', 'episcopal'], 'episcopal': ['episcopal', 'anglican'],
    'baptist': ['baptist', 'bautista', 'baptiste', 'batista', 'battista', 'baptyst'],
    'catholic': ['catholic', 'catolica', 'catholique', 'katholisch', 'cattolica', 'katolick', 'catolic'],
    'lutheran': ['lutheran', 'lutherien', 'luterana', 'lutherisch', 'evangelisch', 'luteran', 'ewangelick'],
    'methodist': ['methodist', 'metodista', 'methodiste', 'methodistisch', 'metodyst'],
    'presbyterian': ['presbyterian', 'presbyterien', 'presbiterian'], 'adventist': ['adventist', 'adventista', 'adventiste'],
    'nazarene': ['nazarene', 'nazareno'], 'church-of-christ': ['church of christ', 'churches of christ'],
    'uniting': ['uniting'], 'united': ['united', 'uniting', 'ucc', 'unie'],
    'orthodox': ['orthodox', 'ortodox', 'orthodoxe', 'prawoslaw'], 'pentecostal': ['pentecostal', 'assemblies of god', 'pentecotiste', 'pfingst', 'pentecost', 'zielonoswiat'],
    'reformed': ['reformed', 'reformee', 'reformiert', 'reformada', 'reformat'], 'congregational': ['congregational', 'ucc'],
    'evangelical': ['evangelical', 'evangelique', 'evangelica', 'evangelisch', 'evangelic'], 'salvation-army': ['salvation army', 'armee du salut', 'heilsarmee'],
    'nondenominational': ['nondenominational', 'non denominational', 'independ', 'freikirch', 'interconfession', 'sans denomination', 'non confessionn', 'non confessional', 'sin denominacion', 'no denominacional', 'nao denominacional', 'interdenominacional', 'interdenominational'],
    'christian': ['christian'], 'quaker': ['quaker', 'friends'],
    'brethren': ['brethren'], 'covenant': ['covenant'], 'mennonite': ['mennonite'], 'moravian': ['moravian'], 'wesleyan': ['wesleyan'],
    'church-of-god': ['church of god'], 'disciples': ['disciples'], 'unitarian': ['unitarian'], 'apostolic': ['apostolic'],
    'alliance': ['alliance'], 'foursquare': ['foursquare'], 'vineyard': ['vineyard'], 'coptic': ['coptic'], 'free-church': ['free church'],
    'katholisch': ['katholisch', 'catholic'], 'evangelisch': ['evangelisch', 'evangelical', 'lutheran'], 'catolica': ['catolica', 'catholic'],
    'catholique': ['catholique', 'catholic'], 'protestant': ['protestant', 'reformee', 'reformed', 'lutheran', 'evangel']}


def by_tradition(r):
    out = {}
    for k, words in DENOMS.items():
        if not re.fullmatch(r'[a-z-]+', k) or k in ('katholisch', 'evangelisch', 'catolica', 'catholique', 'protestant', 'christian'):
            continue
        ch = {x for x in r['churches'] if any(w in r['desc'].get(x, '') for w in words)}
        if ch:
            out[k] = [len(ch), len(ch & r['timed'])]
    return out


def denom_of(g):
    s = g.rsplit('/', 1)[-1].replace('-christmas-eve-services', '')
    for k in sorted(DENOMS, key=len, reverse=True):
        if s == k or s.endswith('-' + k):
            return DENOMS[k]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=6000)
    ap.add_argument('--threads', type=int, default=6)
    ap.add_argument('--only', default='', help='comma-separated collections (testing)')
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args()
    log = lambda *x: print(*x, flush=True)
    st, sm = get(SQS + '/sitemap.xml')
    if st != 200:
        sys.exit(f'sitemap HTTP {st}')
    cols = [c for c in COLLECTIONS if not a.only or c in a.only.split(',')]
    urls = sorted({u for u in re.findall(r'<loc>https?://[^/<]+(/[^<]+)</loc>', sm)
                   if u.count('/') == 2 and u.split('/')[1] in cols and '/category/' not in u and '/tag/' not in u})[:a.max]
    log(f'{len(urls)} services pages in {len(cols)} collections')
    pages, failed = {}, []

    def read_all(paths, threads):
        miss = []
        with cf.ThreadPoolExecutor(threads) as ex:
            for p, (s, d) in zip(paths, ex.map(page, paths)):
                if d is None:
                    if s not in (404, 410):
                        miss.append(p)
                    continue
                r = analyze(p, d['body'])
                r['title'] = d['title']
                r['sq'] = d['id']
                pages[p] = r
        return miss

    failed = read_all(urls, a.threads)
    if failed:   # Squarespace throttles bursts: a slower second pass picks up what the first missed
        time.sleep(20)
        failed = read_all(failed, 2)
    log(f'read {len(pages)} of {len(urls)} from the sitemap; {len(failed)} could not be read')
    if len(failed) > max(10, 0.01 * len(urls)):
        sys.exit(f'{len(failed)} pages could not be read; keeping the last counts rather than writing low ones')
    # the sitemap lags (new pages appear days later): follow every link inside the services collections until nothing new turns up
    tried = set(pages) | set(urls)
    frontier = set()
    for p, r in pages.items():
        frontier |= {q for q in r.pop('_hrefs', set()) if q not in tried}
    rounds = 0
    while frontier and rounds < 12 and len(pages) < a.max:
        rounds += 1
        batch = sorted(frontier)[:a.max - len(pages)]
        tried |= set(batch)
        frontier = set()
        with cf.ThreadPoolExecutor(a.threads) as ex:
            for p, (s, d) in zip(batch, ex.map(page, batch)):
                if d is None:
                    continue
                r = analyze(p, d['body'])
                r['title'] = d['title']; r['sq'] = d['id']
                frontier |= {q for q in r.pop('_hrefs', set()) if q not in tried}
                pages[p] = r
        log(f'link round {rounds}: read {len(batch)}, now {len(pages)} pages')
    # the hub: its finder data lists every city page (and gives each city its region and country)
    st, hb = get(SITE + HUB) if os.environ.get('RTT_BOT_KEY') else (0, '')
    hubp = set()
    m = re.search(r'<script type="application/json" id="xn-data">(.*?)</script>', hb or '', re.S)
    if m:
        D = json.loads(m.group(1))
        for x in D.get('p', []):
            for s in str(x[6]).split(','):
                s = s.split(':', 1)[-1]
                hubp.add(s if s.startswith('/') else '/christmas-eve-services/' + s)
    listed = set(hubp)
    for p, r in pages.items():
        if not r['cev']:
            listed.update(q for q in r['links'] if q in pages)
    cev = {p: r for p, r in pages.items() if r['cev']}
    # a denomination page: its slug is a city page's slug plus "-<denomination>", in the same collection
    city_of = {}
    for p in cev:
        col = p.rsplit('/', 1)[0]
        cand = [c for c in cev if c != p and c.rsplit('/', 1)[0] == col and p.startswith(c + '-')]
        city_of[p] = max(cand, key=len) if cand else p
    while any(city_of[city_of[p]] != city_of[p] for p in city_of):
        city_of = {p: city_of[c] for p, c in city_of.items()}
    cities = {}
    for p, r in cev.items():
        c = city_of[p]
        x = cities.setdefault(c, {'churches': set(), 'timed': set(), 'desc': {}})
        x['churches'] |= set(r['churches']); x['timed'] |= set(r['timed']); x['desc'].update(r['desc'])
    denoms = [p for p in cev if city_of[p] != p]
    guides = {p: r for p, r in pages.items() if not r['cev'] and r['links']}
    memo = {}

    def roll(g, seen=()):
        """listing pages a guide covers (directly or through its sub-guides)"""
        if g in memo:
            return memo[g]
        ls = set()
        for q in guides[g]['links']:
            if q in cev:
                ls.add(q)
            elif q in guides and q not in seen and q != g:
                ls |= roll(q, seen + (g,))
        memo[g] = ls
        return ls

    out_g = {}
    for g in guides:
        ls = roll(g)
        dk = denom_of(g)
        ch, tm, cs, rows = set(), set(), set(), {}
        direct = set(guides[g]['links'])
        for q in ls:
            c = city_of[q]
            cs.add(c)
            src = cities[c] if q == c else {'churches': cev[q]['churches'], 'timed': cev[q]['timed']}   # a city page brings its whole city
            if dk:   # a denomination guide counts that tradition's churches in the city: its denomination page plus any on the city page
                keep = {x for x in cities[c]['churches'] if any(w in cities[c]['desc'].get(x, '') for w in dk)}
                if q != c:
                    keep |= set(cev[q]['churches'])
                src = {'churches': keep, 'timed': set(cities[c]['timed']) & keep}
            if dk and q in direct:   # what this guide's row for the city should say
                rows[q] = [len(src['churches']), len(set(src['timed']))]
            ch |= {c + '#' + x for x in src['churches']}
            tm |= {c + '#' + x for x in src['timed']}
        out_g[g] = {'name': re.sub(r'\s*\(\d{4}\)$', '', guides[g]['title']), 'cities': len(cs), 'churches': len(ch),
                    'timed': len(tm), 'cw': len({x.split('#')[0] for x in tm})}
        if dk:
            out_g[g]['denom'] = 1
            out_g[g]['rows'] = dict(sorted(rows.items()))
    allc = set(cities)
    total = {'cities': len(allc), 'churches': sum(len(cities[c]['churches']) for c in allc),
             'timed': sum(len(cities[c]['timed']) for c in allc), 'cw': sum(1 for c in allc if cities[c]['timed'])}
    def denom_row(p):   # a denomination page plus that tradition's churches on its city page (guides count it that way)
        c = city_of[p]
        ch = set(cev[p]['churches'])
        words = DENOMS.get(p[len(c) + 1:])
        if words:
            ch |= {x for x in cities[c]['churches'] if any(w in cities[c]['desc'].get(x, '') for w in words)}
        return [len(ch), len(ch & cities[c]['timed']), c]

    live = {'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'total': total,
            # path: [churches, churches with 2026 times]
            # city page: [churches, with times, {tradition: [churches, with times]}] (the tradition split feeds "#t-anglican" links)
            'cities': {c: [len(r['churches']), len(r['timed']), by_tradition(r)] for c, r in sorted(cities.items())},
            # denomination page: [churches, with times, its city page]
            'denoms': {p: denom_row(p) for p in sorted(denoms)},
            'guides': dict(sorted(out_g.items())),
            'unlisted_cities': sorted(c for c in cities if hubp and c not in hubp)}
    OUTP = a.out
    prev = json.load(open(OUTP)) if os.path.exists(OUTP) and not a.only else {}
    if prev and live['total']['cities'] < 0.9 * prev.get('total', {}).get('cities', 0):
        sys.exit('city count dropped by more than 10%; not writing')
    strip = lambda d: {k: v for k, v in d.items() if k != 'generated'}
    if prev and strip(prev) == strip(live):
        live['generated'] = prev['generated']
    json.dump(live, open(OUTP, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log(f"services: {total['churches']:,} churches ({total['timed']:,} with 2026 times) in {total['cities']:,} cities "
        f"({total['cw']:,} with times); {len(out_g)} guides; {len(denoms)} denomination pages")


if __name__ == '__main__':
    main()
