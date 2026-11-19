#!/usr/bin/env python3
"""Build llms.txt and llms-full.txt for www.rallytakesthetrain.com from the live site.

The hand-written parts (book facts, guides, museums, policies) live in tools/llms/template.md.
The big directories are rebuilt every run from the site itself:
  - Christmas events: the A to Z list on /christmas-events-for-kids, plus any English city
    guide in the site's sitemap.xml that the A to Z has not picked up yet.
  - Christmas Eve services: every page in the six Christmas Eve sections (?format=json).
  - Any other page in sitemap.xml that the template does not list yet goes under
    "Pages added recently", so new sections never fall out of the file.
Language codes come from tools/clusters.json (the hreflang source of truth).

Usage: python3 tools/llms/build_llms.py [--cache .state/llms-titles.json] [--out .]
Exits non-zero (and writes nothing) if the result looks wrong, so a bad run never
replaces a good file.
"""
import argparse, collections, concurrent.futures as cf, datetime, html, json, os, re, sys, time, urllib.request

SITE = 'https://www.rallytakesthetrain.com'
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
MAX_LOOKUPS = 1500  # new pages looked up per run; the rest wait for the next run

ISO = {'Austria': 'AT', 'Belgium': 'BE', 'Croatia': 'HR', 'Cyprus': 'CY', 'Denmark': 'DK', 'Estonia': 'EE', 'Finland': 'FI',
       'France': 'FR', 'Germany': 'DE', 'Greece': 'GR', 'Hungary': 'HU', 'Iceland': 'IS', 'Ireland': 'IE', 'Italy': 'IT',
       'Latvia': 'LV', 'Lithuania': 'LT', 'Luxembourg': 'LU', 'Netherlands': 'NL', 'Norway': 'NO', 'Poland': 'PL',
       'Portugal': 'PT', 'Romania': 'RO', 'Slovakia': 'SK', 'Slovenia': 'SI', 'Spain': 'ES', 'Sweden': 'SE',
       'Switzerland': 'CH', 'Ukraine': 'UA', 'United Kingdom': 'GB', 'Brazil': 'BR', 'Canada': 'CA', 'Colombia': 'CO',
       'Mexico': 'MX', 'United States': 'US', 'Australia': 'AU', 'Hong Kong': 'HK', 'Japan': 'JP', 'New Zealand': 'NZ',
       'Philippines': 'PH', 'Singapore': 'SG', 'South Korea': 'KR', 'Ethiopia': 'ET', 'Lebanon': 'LB', 'Madagascar': 'MG',
       'Czech Republic': 'CZ', 'Czechia': 'CZ', 'Bulgaria': 'BG', 'Serbia': 'RS', 'Malta': 'MT', 'Argentina': 'AR',
       'Chile': 'CL', 'Peru': 'PE', 'South Africa': 'ZA', 'India': 'IN', 'Nigeria': 'NG', 'Kenya': 'KE', 'Ghana': 'GH'}
EN_COUNTRIES = {'US', 'GB', 'IE', 'CA', 'AU', 'NZ', 'PH', 'SG', 'HK', 'LU', 'ZA', 'IN', 'NG', 'KE', 'GH', 'MT'}
LANG_NAMES = {'en': 'English', 'de': 'German', 'fr': 'French', 'nl': 'Dutch', 'it': 'Italian', 'es': 'Spanish', 'pt': 'Portuguese',
              'ja': 'Japanese', 'ko': 'Korean', 'pl': 'Polish', 'sv': 'Swedish', 'da': 'Danish', 'nb': 'Norwegian Bokmal',
              'fi': 'Finnish', 'hu': 'Hungarian', 'ro': 'Romanian', 'uk': 'Ukrainian', 'el': 'Greek', 'hr': 'Croatian',
              'et': 'Estonian', 'lv': 'Latvian', 'lt': 'Lithuanian', 'sk': 'Slovak', 'sl': 'Slovenian', 'is': 'Icelandic',
              'am': 'Amharic', 'ar': 'Arabic', 'mg': 'Malagasy', 'cs': 'Czech', 'bg': 'Bulgarian', 'sr': 'Serbian', 'zh': 'Chinese'}
US_ABBR = {'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA', 'colorado': 'CO',
           'connecticut': 'CT', 'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL',
           'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
           'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT',
           'nebraska': 'NE', 'nevada': 'NV', 'new-hampshire': 'NH', 'new-jersey': 'NJ', 'new-mexico': 'NM', 'new-york': 'NY',
           'north-carolina': 'NC', 'north-dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA',
           'rhode-island': 'RI', 'south-carolina': 'SC', 'south-dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT',
           'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA', 'west-virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY',
           'washington-dc': 'DC', 'district-of-columbia': 'DC'}
CA_PROV = {'on', 'qc', 'bc', 'ab', 'ns', 'sk', 'nl', 'nb', 'pe', 'mb', 'nt', 'yt', 'nu'}

# Christmas Eve sections: path, country hub slug, heading, language, code, word for regions
EVE_SECTIONS = [
    ('christmas-eve-services', 'united-states', 'United States', 'English', 'en-US', 'state'),
    ('christmas-eve-services-canada', 'canada', 'Canada', 'English', 'en-CA', 'province'),
    ('messes-de-noel-quebec-canada', 'quebec-et-canada-francais', 'Quebec and French-speaking Canada', 'French', 'fr-CA', 'region'),
    ('christmas-eve-services-uk', 'united-kingdom', 'United Kingdom', 'British English', 'en-GB', 'nation'),
    ('christmas-eve-services-australia', 'australia', 'Australia', 'English', 'en-AU', 'state'),
    ('christmas-eve-reihai-japan', 'japan', 'Japan', 'Japanese', 'ja-JP', 'prefecture'),
]
FR_TRAD = {'united': 'Église Unie', 'presbyterian': 'presbytériennes', 'pentecostal': 'pentecôtistes', 'orthodox': 'orthodoxes',
           'nondenominational': 'non confessionnelles', 'catholic': 'catholiques', 'baptist': 'baptistes', 'anglican': 'anglicanes',
           'adventist': 'adventistes', 'lutheran': 'luthériennes', 'methodist': 'méthodistes'}
JA_TRAD = {'united': '日本基督教団', 'orthodox': '正教会', 'lutheran': 'ルーテル', 'evangelical-free': '福音派', 'catholic': 'カトリック',
           'baptist': 'バプテスト', 'anglican': '聖公会', 'methodist': 'メソジスト', 'presbyterian': '長老派',
           'nondenominational': '超教派', 'pentecostal': 'ペンテコステ'}

# Pages in sitemap.xml that never go in the file
SKIP_PATH = re.compile(r'/(?:tag|category)/|^/home$|^/search|blog-post-title|^/cart|^/account|^/checkout|^/s/')
ENGLISH_GUIDE = re.compile(r'^(?:\d+ )?Christmas Events for Kids (?:in|on) (?:the )?(.+?)(?:,\s*[A-Z]{2})?\s*\(?2026\)?(?::.*)?$')


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, limit=None, tries=4, timeout=60):
    err = None
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=timeout)
            return r.status, r.read(limit) if limit else r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 410, 403, 429) and tries == 1:
                return e.code, b''
            if e.code in (404, 410):
                return e.code, b''
            err = e
        except Exception as e:
            err = e
        time.sleep(2 * (i + 1))
    raise RuntimeError(f'{url}: {err}')


def head_info(path):
    """(path, status, title, description) from the first 80 KB of a page."""
    try:
        st, b = get(SITE + path, limit=80000, tries=1, timeout=20)
    except Exception as e:
        return path, 0, '', ''
    t = b.decode('utf-8', 'ignore')
    title = re.search(r'<title>(.*?)</title>', t, re.S)
    desc = re.search(r'<meta name="description" content="([^"]*)"', t)
    return path, st, html.unescape(title.group(1).strip()) if title else '', html.unescape(desc.group(1)) if desc else ''


def many(paths, workers=6):
    out = {}
    with cf.ThreadPoolExecutor(workers) as ex:
        for p, st, t, d in ex.map(head_info, paths):
            out[p] = (st, t, d)
    return out


def strip(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s)).strip()


def collection(sec):
    items, off = [], None
    for _ in range(500):
        url = f'{SITE}/{sec}?format=json' + (f'&offset={off}' if off else '')
        st, b = get(url)
        d = json.loads(b)
        for i in d.get('items', []):
            items.append((i['fullUrl'].rstrip('/').split('/')[-1], i.get('title', ''), strip(i.get('excerpt') or '')))
        pg = d.get('pagination', {})
        if not pg.get('nextPage'):
            break
        off = pg.get('nextPageOffset')
    return items


# ------------------------------------------------------------------ Christmas Eve
def clean_title(t):
    return re.sub(r'\s*[\(（]2026年?[\)）]\s*$', '', t).strip()


def eve_directory(data, counts):
    out, meta = [], {}
    for sec, hub, heading, lang, code, rw in EVE_SECTIONS:
        items = [(s, clean_title(t), e) for s, t, e in data[sec]]
        by = {s: (t, e) for s, t, e in items}
        if hub not in by:
            raise SystemExit(f'Christmas Eve section {sec} has no {hub} page')
        nat = {s[:-len('-christmas-eve-services')]: t for s, t, e in items if s.endswith('-christmas-eve-services')}
        trads = sorted(set(nat) | {'christian-church', 'church-of-christ', 'evangelical-free', 'congregational', 'reformed', 'unitarian'},
                       key=len, reverse=True)

        def tlabel(k):
            if sec == 'messes-de-noel-quebec-canada':
                return FR_TRAD.get(k, k)
            if sec == 'christmas-eve-reihai-japan':
                return JA_TRAD.get(k, k)
            m = re.match(r'^(.*?) Christmas Eve', nat.get(k, ''))
            return m.group(1) if m else k.replace('-', ' ').title()

        def pname(slug, title):
            if sec == 'christmas-eve-reihai-japan':
                m = re.match(r'^(.*?)のクリスマスイブ', title)
                return m.group(1) if m else title
            if sec == 'messes-de-noel-quebec-canada':
                m = re.search(r' (?:à|au|en|aux) (.+)$', title)
                return m.group(1) if m else title
            m = re.search(r' (?:in|on) (?:the )?(.+)$', title)
            name = m.group(1) if m else title
            c = re.search(r'-([a-z]{2,3})$', slug)
            if c and c.group(1) not in ('uk', 'jp') and sec != 'christmas-eve-services-uk' and not name.endswith(', ' + c.group(1).upper()):
                name += ', ' + c.group(1).upper()
            return name

        groups = collections.OrderedDict()
        for s, t, e in items:
            if s.endswith('-christmas-eve-services'):
                continue
            base, tk = s, None
            for k in trads:
                if s.endswith('-' + k):
                    base, tk = s[:-len(k) - 1], k
                    break
            groups.setdefault(base, [])
            if tk:
                groups[base].append((tk, s))
        regions, cities = [], []
        for base in groups:
            if base == hub:
                continue
            if sec == 'christmas-eve-reihai-japan':
                is_city = base.endswith('-jp')
            else:
                is_city = bool(re.search(r'-(?:[a-z]{2}|nsw|qld|vic|tas|act)$', base)) and (base not in US_ABBR or base == 'washington-dc')
            (cities if is_city else regions).append(base)

        def name_for(base):
            if base in by:
                return pname(base, by[base][0])
            return pname(base, by[groups[base][0][1]][0])

        def line(base):
            tl = [f'[{tlabel(tk)}](/{sec}/{s})' for tk, s in sorted(groups[base], key=lambda x: tlabel(x[0]).lower())]
            head = f'[{name_for(base)}](/{sec}/{base})' if base in by else name_for(base)
            if not tl:
                return f'- {head}'
            return f'- {head}' + ('; ' if base in by else ': ') + ', '.join(tl)

        key = (lambda x: x) if sec == 'christmas-eve-reihai-japan' else (lambda x: name_for(x).lower())
        hubt, hube = by[hub]
        o = [f'### {heading} ({len(items):,} pages in {lang}, hreflang {code})', '',
             f'- [{hubt}](/{sec}/{hub}): {hube}', f'- [All {heading} Christmas Eve pages, newest first](/{sec})', '',
             'By tradition, nationwide:', '']
        o += [f'- [{nat[k]}](/{sec}/{k}-christmas-eve-services)' for k in sorted(nat, key=lambda k: tlabel(k).lower())]
        o += ['', f'By {rw}, with tradition pages after the semicolon:', '']
        o += [line(b) for b in sorted(regions, key=key)]
        o += ['', 'By city, with tradition pages after the semicolon:', '']
        o += [line(b) for b in sorted(cities, key=key)]
        o.append('')
        listed = set(re.findall(r'\]\((/[^)]+)\)', '\n'.join(o)))
        missing = {f'/{sec}/{s}' for s, t, e in items} - listed
        if missing:
            raise SystemExit(f'Christmas Eve {sec}: {len(missing)} pages not placed, e.g. {sorted(missing)[:5]}')
        counts[code] += len(items)
        out += o
        meta[sec] = {'pages': len(items), 'hub': (hubt, f'/{sec}/{hub}', hube), 'code': code}
    return out, meta


# ------------------------------------------------------------------ Christmas events
def parse_hub(h):
    out = []
    for b in re.findall(r'<details[^>]*class="[^"]*xn-az__c[^"]*"[^>]*>.*?</details>', h, re.S):
        summ = strip(re.search(r'<summary[^>]*>(.*?)<span', b, re.S).group(1))
        name = re.sub(r'^Christmas events for kids in (the )?', '', summ)
        c = {'name': name, 'guides': [], 'groups': []}
        st = re.search(r'<p class="xn-az__st">(.*?)</p', b, re.S)
        if st:
            c['guides'] = [(hr, a, strip(tx)) for hr, a, tx in re.findall(r'<a href="([^"]+)"([^>]*)>(.*?)</a>', st.group(1))]
        cur = None
        for p in re.split(r'(<h4[^>]*>.*?</h4>)', b, flags=re.S):
            m = re.match(r'<h4[^>]*>(.*?)</h4>', p, re.S)
            if m:
                a = re.search(r'<a href="([^"]+)">(.*?)</a>', m.group(1))
                cur = {'state': (a.group(1), strip(a.group(2))), 'cities': []}
                c['groups'].append(cur)
                continue
            for li in re.findall(r'<li>(.*?)</li>', p, re.S):
                anchors = [(hr, a, strip(tx)) for hr, a, tx in re.findall(r'<a href="([^"]+)"([^>]*)>(.*?)</a>', li)]
                if cur is None:
                    cur = {'state': None, 'cities': []}
                    c['groups'].append(cur)
                cur['cities'].append(anchors)
        out.append(c)
    if len(out) < 20:
        raise SystemExit(f'Christmas events A to Z list looks broken ({len(out)} countries)')
    return out


def events_directory(hub, codes, extra, desc):
    lines, counts, guides_by_code = [], collections.Counter(), collections.defaultdict(list)
    total = 0
    countries = []
    for c in hub:
        name = c['name']
        iso = ISO.get(name)
        if not iso:
            log(f'warning: no country code for {name}; add it to ISO in build_llms.py')

        def code_for(path, attrs):
            if path in codes:
                cs = codes[path]
                if 'en-US' in cs:
                    return 'en-US'
                reg = [x for x in cs if '-' in x]
                return reg[0] if reg else cs[0]
            m = re.search(r'hreflang="([\w-]+)"', attrs)
            if m:
                l = m.group(1)
                return l if '-' in l or not iso else f'{l}-{iso}'
            if name == 'United States':
                return 'en-US'
            return f'en-{iso}' if iso in EN_COUNTRIES else 'en'

        ex = extra.get(name, [])
        ncities = sum(len(g['cities']) for g in c['groups']) + len(ex)
        total += ncities
        countries.append((name, iso))
        pc = collections.Counter()
        for g in c['groups']:
            for anchors in g['cities']:
                for hr, a, tx in anchors:
                    pc[code_for(hr, a)] += 1
        for p, nm, cd in ex:
            pc[cd] += 1
        for hr, a, tx in c['guides']:
            pc[code_for(hr, a)] += 1
        default = pc.most_common(1)[0][0]
        others = [k for k in pc if k != default]
        lname = LANG_NAMES.get(default.split('-')[0], default)
        lines += [f'### {name} ({ncities:,} {"city" if ncities == 1 else "cities"}; {lname} pages, hreflang {default}'
                  + (', unless marked)' if others else ')'), '']
        for hr, a, tx in c['guides']:
            cd = code_for(hr, a)
            d = desc.get(hr, '')
            mark = f' (hreflang {cd})' if cd != default else ''
            lines.append(f'- [{name}: ' + tx.replace('Country guide', 'country guide') + f']({hr})' + (f': {d}' if d else '') + mark)
            counts[cd] += 1
            guides_by_code[cd].append((name, hr))
        for g in c['groups']:
            cities = list(g['cities'])
            st = g['state']
            if st:
                ab = US_ABBR.get(st[0].split('/')[-1], '').lower()
                cities += [[(p, '', nm)] for p, nm, cd in ex if ab and p.endswith('-' + ab)]
                cities.sort(key=lambda a: a[0][2].lower())
                links = ', '.join(f'[{a[0][2]}]({a[0][0]})' for a in cities)
                lines.append(f'- [{st[1]}: state guide]({st[0]})' + (f'; cities: {links}' if links else ''))
                counts['en-US'] += 1 + len(cities)
                continue
            cities += [[(p, f'hreflang="{cd}"', nm)] for p, nm, cd in ex]
            cities.sort(key=lambda a: a[0][2].lower())
            for anchors in cities:
                parts = []
                for hr, a, tx in anchors:
                    cd = code_for(hr, a)
                    counts[cd] += 1
                    parts.append(f'[{tx}]({hr})' + (f' hreflang {cd}' if cd != default else ''))
                lines.append('- ' + '; '.join(parts))
        lines.append('')
    # every extra city must have landed somewhere
    body = '\n'.join(lines)
    lost = [p for v in extra.values() for p, _, _ in v if f'({p})' not in body]
    if lost:
        log(f'warning: {len(lost)} new city guides had no state or country to go under, e.g. {lost[:5]}')
    return lines, counts, guides_by_code, total, countries


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', default=os.path.join(ROOT, '.state', 'llms-titles.json'))
    ap.add_argument('--out', default=ROOT)
    ap.add_argument('--date', default=None)
    args = ap.parse_args()
    date = args.date or datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-8))).strftime('%B %-d, %Y')

    template = open(os.path.join(HERE, 'template.md'), encoding='utf-8').read()
    start_links = json.load(open(os.path.join(HERE, 'start_links.json'), encoding='utf-8'))
    clusters = json.load(open(os.path.join(ROOT, 'tools', 'clusters.json'), encoding='utf-8'))
    codes = {}
    for cl in clusters['clusters']:
        for p in cl['pages']:
            codes[p['url'].replace(SITE, '')] = p['hreflang']
    cache = {}
    if os.path.exists(args.cache):
        cache = json.load(open(args.cache, encoding='utf-8'))
    else:
        seed = os.path.join(HERE, 'titles-seed.json')
        if os.path.exists(seed):
            cache = json.load(open(seed, encoding='utf-8'))

    log('reading the site...')
    _, hb = get(SITE + '/christmas-events-for-kids')
    hub = parse_hub(hb.decode('utf-8'))
    eve_data = {sec: collection(sec) for sec, *_ in EVE_SECTIONS}
    _, sm = get(SITE + '/sitemap.xml')
    sitemap = [u.replace(SITE, '') for u in re.findall(r'<loc>([^<]+)</loc>', sm.decode('utf-8'))]
    if len(sitemap) < 1000:
        raise SystemExit(f'sitemap.xml looks broken ({len(sitemap)} URLs)')

    hub_paths = set()
    for c in hub:
        hub_paths |= {hr for hr, a, tx in c['guides']}
        for g in c['groups']:
            if g['state']:
                hub_paths.add(g['state'][0])
            for an in g['cities']:
                hub_paths |= {hr for hr, a, tx in an}

    # Titles: city guides missing from the A to Z, and pages the template doesn't list.
    template_links = set(re.findall(r'\]\((?:https://www\.rallytakesthetrain\.com)?(/[^)\s]*)\)', template))
    eve_prefix = tuple('/' + s[0] + '/' for s in EVE_SECTIONS) + tuple('/' + s[0] for s in EVE_SECTIONS)
    want = []
    for p in sitemap:
        if p in cache or p in hub_paths or p in template_links or SKIP_PATH.search(p) or p.startswith(eve_prefix):
            continue
        if p.startswith('/christmas-events/') and len(p.split('/')[-1].split('-')) > 5:
            continue  # individual events have long slugs
        want.append(p)
    guides = [hr for c in hub for hr, a, tx in c['guides']]
    if len(want) > MAX_LOOKUPS:
        log(f'{len(want)} new pages; looking up {MAX_LOOKUPS} now, the rest on later runs')
        want = want[:MAX_LOOKUPS]
    log(f'{len(want)} new pages to look at, {len(guides)} country guide descriptions')
    got = many(want + guides)
    for p in want:
        st, t, d = got[p]
        if st in (200, 404, 410):
            cache[p] = t if st == 200 else f'#{st}'  # blocked or timed out: try again next run
    desc = {}
    for p in guides:
        st, t, d = got[p]
        if st == 200 and d:
            cache['desc:' + p] = d  # keep the last good description
        desc[p] = cache.get('desc:' + p, '')
    os.makedirs(os.path.dirname(args.cache) or '.', exist_ok=True)
    json.dump(cache, open(args.cache, 'w', encoding='utf-8'), ensure_ascii=False)
    blocked = sum(1 for p in want if got[p][0] not in (200, 404, 410))
    if blocked:
        log(f'{blocked} pages could not be read this run (blocked or slow); they will be tried again')

    extra = collections.defaultdict(list)
    recent = []
    for p in sitemap:
        if p in hub_paths or p in template_links or SKIP_PATH.search(p) or p.startswith(eve_prefix):
            continue
        t = cache.get(p)
        if not t or t.startswith('#'):
            continue
        if p.startswith('/christmas-events/'):
            m = ENGLISH_GUIDE.match(t)
            if m:
                st = p.rsplit('-', 1)[-1]
                if st in CA_PROV:
                    extra['Canada'].append((p, m.group(1).strip(), 'en-CA'))
                elif len(st) == 2:
                    extra['United States'].append((p, m.group(1).strip(), 'en-US'))
            continue
        recent.append((p, re.sub(r'\s*\|\s*Rally Takes the Train\s*$', '', t)))

    ev_lines, ev_counts, guides_by_code, n_cities, countries = events_directory(hub, codes, extra, desc)
    eve_counts = collections.Counter()
    eve_lines, eve_meta = eve_directory(eve_data, eve_counts)

    churches = eve_cities = 0
    for m in eve_meta.values():
        d = m['hub'][2]
        a = re.search(r'([\d,]+)\s*(?:churches|églises)', d) or re.search(r'教会([\d,]+)か所', d)
        b = re.search(r'([\d,]+)\s*(?:cities|villes)', d) or re.search(r'([\d,]+)都市', d)
        churches += int(a.group(1).replace(',', '')) if a else 0
        eve_cities += int(b.group(1).replace(',', '')) if b else 0

    # Language list
    iso_name = {iso: n for n, iso in countries if iso}
    eve_hub_by_code = {m['code']: m['hub'] for m in eve_meta.values()}
    allc = set(ev_counts) | set(eve_counts)
    rows_local, rows_en = [], []
    for code in allc:
        if code in ('en-US', 'en') or '-' not in code:
            continue
        lang, reg = code.split('-', 1)
        if lang == 'en' and reg not in EN_COUNTRIES:
            continue  # English guide for a non-English country: counted in the English versions line
        country = iso_name.get(reg, reg)
        n, m = ev_counts.get(code, 0), eve_counts.get(code, 0)
        s = f'- {LANG_NAMES.get(lang, lang)} ({country}), hreflang {code}: {n} Christmas event pages'
        if m:
            s += f' and {m} Christmas Eve service pages'
        starts = [f'[{c} country guide]({SITE}{p})' for c, p in guides_by_code.get(code, [])]
        starts += [f'[{t}]({SITE}{p})' for t, p in start_links.get(code, [])]
        if code in eve_hub_by_code:
            t, p, _ = eve_hub_by_code[code]
            starts.append(f'[{t}]({SITE}{p})')
        if starts:
            s += '. Start at: ' + '; '.join(starts)
        (rows_en if lang == 'en' else rows_local).append((LANG_NAMES.get(lang, lang) + country, s))
    en_other = sum(v for k, v in ev_counts.items() if k.startswith('en-') and k.split('-')[1] not in EN_COUNTRIES)
    lang_list = [r for _, r in sorted(rows_local)] + [r for _, r in sorted(rows_en)]
    lang_list.append(f'- English versions of international city and country guides: {ev_counts.get("en", 0)} city guides use hreflang en '
                     f'(English for any region), each linked beside its local-language page in the Christmas events directory. '
                     f'The {en_other} English country guides for countries where English is not the main language carry the country\'s own code, '
                     f'for example en-AT for the Austria guide and en-JP for the Japan guide.')

    eve_section = [
        '## Christmas Eve services by country, region, city and tradition (2026)', '',
        f'Christmas Eve is Thursday, December 24, 2026. Each page lists churches with a Christmas Eve service, family and children\'s services first, with addresses, maps and 2026 times as each church posts them. Every listing links to the church\'s own page; confirm times there. As of {date}: {churches:,} churches in {eve_cities:,} cities in five countries (the United States, Canada, the United Kingdom, Australia and Japan), plus French-language pages for Quebec and French-speaking Canada. Cities are added weekly.', '',
        f'- [Christmas Eve Services Near Me 2026: Times by City]({SITE}/christmas-eve-services-near-me): the searchable hub, with a guide for each country',
        f'- [Add your church\'s Christmas Eve services (free listing)]({SITE}/add-christmas-eve-service)', '',
        'Links under the headings below are written as paths on this site: put https://www.rallytakesthetrain.com in front of each one. For example, /christmas-eve-services-canada/ajax-on is https://www.rallytakesthetrain.com/christmas-eve-services-canada/ajax-on. Each country has its own section of the site and its own language and region code, given in its heading; the pages for Canada and Australia use local church names (for example United Church in Canada and Uniting Church in Australia). In each list a place comes first, then its pages for single traditions after the semicolon.', '',
    ] + eve_lines
    evt_section = [
        '## Christmas events for kids: every country, state and city guide (2026)', '',
        f'{n_cities:,} city guides in {len(countries)} countries (as of {date}). Each guide lists confirmed Christmas events for kids (Santa visits, story times, tree lightings, markets, light displays, holiday shows) with dates, times, costs and a link to the host, plus the story of Christmas in that city. Thousands of individual event pages sit under these guides and are not listed here; each city guide links to them.', '',
        f'- [Christmas Events for Kids Near Me 2026]({SITE}/christmas-events-for-kids): the searchable finder and map',
        f'- [Christmas Events for Kids: latest guides]({SITE}/christmas-events): the running index', '',
        'Links under the headings below are written as paths on this site: put https://www.rallytakesthetrain.com in front of each one. For example, /christmas-events/christmas-in-austria-with-kids is https://www.rallytakesthetrain.com/christmas-events/christmas-in-austria-with-kids. Each country heading names the language code that most of its pages use; a page in another language or region is marked "hreflang xx-XX" right after its link. A city line lists the city\'s guide first, then the same guide in other languages after each semicolon (labelled with the language\'s own name, for example Deutsch or Français). In the United States list, each state guide is followed by its city guides.', '',
    ] + ev_lines
    rec = []
    if recent:
        rec = ['## Pages added recently', '',
               'New pages on the site that have not been sorted into the sections above yet. Each one declares its own language in its head.', '']
        rec += [f'- [{t}]({SITE}{p})' for p, t in sorted(recent, key=lambda x: x[0])] + ['', '']

    out = template
    rep = {
        'DATE': date, 'N_CITIES': f'{n_cities:,}', 'N_COUNTRIES': str(len(countries)), 'CHURCHES': f'{churches:,}',
        'EVE_CITIES': f'{eve_cities:,}', 'LANG_LIST': '\n'.join(lang_list), 'US_EVE_PAGES': f'{eve_counts["en-US"]:,}',
        'CLUSTER_PAGES': str(len(codes)), 'CLUSTERS': str(len(clusters['clusters'])),
        'EVE_HUB_LINKS': '; '.join(f'[{m["hub"][0]}]({SITE}{m["hub"][1]})' for m in eve_meta.values()),
        'EVE_DIRECTORY': '\n'.join(eve_section).rstrip('\n'), 'EVENTS_DIRECTORY': '\n'.join(evt_section).rstrip('\n'),
        'RECENT': '\n'.join(rec),
    }
    for k, v in rep.items():
        out = out.replace('{{' + k + '}}', v)
    links = set(re.findall(r'\]\((?:https://www\.rallytakesthetrain\.com)?(/[^)\s]*)\)', out))
    out = out.replace('{{PAGECOUNT}}', f'{(len(links) // 50) * 50:,}')
    out = re.sub(r'\n{3,}', '\n\n', out).rstrip('\n') + '\n'

    # ---- checks: never replace a good file with a bad one
    left = re.findall(r'\{\{\w+\}\}', out)
    if left:
        raise SystemExit(f'unfilled placeholders: {left}')
    if '—' in out:
        raise SystemExit('em dash in output')
    prev_path = os.path.join(args.out, 'llms.txt')
    if os.path.exists(prev_path):
        prev = set(re.findall(r'\]\((?:https://www\.rallytakesthetrain\.com)?(/[^)\s]*)\)', open(prev_path, encoding='utf-8').read()))
        if len(links) < 0.95 * len(prev):
            raise SystemExit(f'only {len(links)} links, last file had {len(prev)}; not writing')
    for h in ('## Key facts', '## Train museums', '## Christmas Eve services by country', '## Christmas events for kids: every'):
        if h not in out:
            raise SystemExit(f'missing section {h}')

    full = re.sub(r'\]\((/[^)\s]*)\)', r'](https://www.rallytakesthetrain.com\1)', out)
    full = re.sub(r'^Links under the headings below are written as paths on this site: put https://www\.rallytakesthetrain\.com in front of each one\. For example, \S+ is \S+\. ?', '', full, flags=re.M)
    full = full.replace(' In those three directories the links are written as paths on this site (https://www.rallytakesthetrain.com plus the path). A copy of this file with every address written in full is at [llms-full.txt](https://www.rallytakesthetrain.com/llms-full.txt).', ' Every address in this copy is written in full.')

    open(os.path.join(args.out, 'llms.txt'), 'w', encoding='utf-8').write(out)
    open(os.path.join(args.out, 'llms-full.txt'), 'w', encoding='utf-8').write(full)
    print(f'llms.txt: {len(out.encode()):,} bytes, {len(links):,} links; {n_cities:,} city guides in {len(countries)} countries '
          f'({sum(len(v) for v in extra.values())} not yet in the A to Z); {sum(m["pages"] for m in eve_meta.values()):,} Christmas Eve pages; '
          f'{len(recent)} recent pages')


if __name__ == '__main__':
    main()
