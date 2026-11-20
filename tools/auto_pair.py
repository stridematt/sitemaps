#!/usr/bin/env python3
"""Add new translated or country pages to clusters.json automatically.

Runs every 3 hours in GitHub Actions. It reads the site sitemap, opens pages it
hasn't seen before, and pairs pages the site itself declares as language versions
of each other: the language switcher link ("Lire en français", "Lees in het
Nederlands") in the page's rtt-post__meta line, which carries hreflang and lang.
It also reads the cluster list (C) in the site-wide Squarespace language script,
which the page-building process keeps up to date, and adds any entries that
aren't in clusters.json yet. Christmas Eve denomination pages are paired by their
matching URLs across the US, Canada, UK and Quebec sections.

A pair is only added when both pages load (200, no redirect), point their
canonical at themselves, aren't noindex, and the target page declares the
language the switcher says it's in. Anything doubtful goes to the review list
instead (for example two pages already in different clusters).

Usage:
  python3 tools/auto_pair.py --state STATE.json [--sitemap FILE] [--sweep FILE] [--report report.md]
    --state   JSON file remembering pages already looked at (kept in the Actions cache)
    --sitemap use a saved copy of the site sitemap instead of downloading it
    --sweep   also check every URL listed in FILE (one per line), seen or not
Exit code: 0 always unless something crashed; the report says what changed.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_hreflang  # noqa: E402

SITE = 'https://www.rallytakesthetrain.com'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
# Our own pipeline proves itself to Cloudflare with this header (GitHub secret RTT_BOT_KEY), so bot protection never challenges it.
HDR = {'User-Agent': UA, **({'x-rtt-key': os.environ['RTT_BOT_KEY']} if os.environ.get('RTT_BOT_KEY') else {})}
READ_BYTES = 450_000          # the switcher sits ~150 KB into the page
MAX_NEW_PER_RUN = 3000
PENDING_DAYS = 7              # keep retrying a declared pair whose partner isn't live yet
EVE_SECTIONS = {
    'christmas-eve-services': ['en-US'],
    'christmas-eve-services-canada': ['en-CA'],
    'christmas-eve-services-uk': ['en-GB'],
    'messes-de-noel-quebec-canada': ['fr-CA'],
    'christmas-eve-services-australia': ['en-AU'],
    'christmas-eve-reihai-japan': ['ja', 'ja-JP'],
}
# Each country's national Christmas Eve page, which joins the Christmas Eve hub cluster.
EVE_HUB_CLUSTER = 'christmas-eve-services-hub'
EVE_HUBS = {
    'christmas-eve-services-canada': 'canada',
    'christmas-eve-services-uk': 'united-kingdom',
    'messes-de-noel-quebec-canada': 'quebec-et-canada-francais',
    'christmas-eve-services-australia': 'australia',
    'christmas-eve-reihai-japan': 'japan',
}
EVE_ORDER = list(EVE_SECTIONS)


def path_of(url):
    p = url.replace(SITE, '', 1)
    return p.rstrip('/') or '/'


def site_pages(sitemap_file=None):
    if sitemap_file:
        xml = open(sitemap_file, encoding='utf-8').read()
    else:
        req = urllib.request.Request(SITE + '/sitemap.xml', headers={**HDR})
        xml = urllib.request.urlopen(req, timeout=180).read().decode('utf-8')
    locs = re.findall(r'<loc>([^<]+)</loc>', xml)
    return {path_of(l) for l in locs if l.startswith(SITE) and not re.search(r'\.(jpe?g|png|gif|webp)$', l, re.I)}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(path):
    """Fetch the start of a page and pull out what pairing needs."""
    url = SITE + path
    info = {'path': path, 'ok': False}
    for attempt in range(3):
        try:
            r = OPENER.open(urllib.request.Request(url, headers={**HDR}), timeout=60)
            s = r.read(READ_BYTES).decode('utf-8', 'ignore')
            break
        except urllib.error.HTTPError as e:
            info['status'] = e.code
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            return info
        except Exception as e:
            info['status'] = 'error: ' + str(e)[:60]
            time.sleep(3)
    else:
        return info
    info['status'] = 200
    canon = re.search(r'<link rel="canonical" href="([^"]+)"', s)
    robots = re.search(r'<meta name="robots" content="([^"]+)"', s)
    info['canonical_ok'] = bool(canon) and path_of(canon.group(1)) == path
    info['indexable'] = not (robots and 'noindex' in robots.group(1).lower())
    # Declared content language: the first div with a lang attribute in the page body.
    loc = re.search(r'<div[^>]*\slang="([A-Za-z]{2}(?:-[A-Za-z]{2})?)"', s)
    info['locale'] = loc.group(1) if loc else None
    sw = []
    m = re.search(r'<p[^>]*class="[^"]*rtt-post__meta[^"]*"[^>]*>(.*?)</p>', s, re.S)
    if m:
        for a in re.finditer(r'<a\s[^>]*>', m.group(1)):
            tag = a.group(0)
            href = re.search(r'href="([^"]+)"', tag)
            hl = re.search(r'hreflang="([^"]+)"', tag)
            lg = re.search(r'\slang="([^"]+)"', tag)
            if href and hl and lg and (href.group(1).startswith('/') or href.group(1).startswith(SITE)):
                sw.append((hl.group(1), path_of(href.group(1).split('?')[0].split('#')[0])))
    info['switchers'] = sw
    info['ok'] = info['canonical_ok'] and info['indexable']
    return info


def codes_for(locale):
    """hreflang codes for a page, matching the conventions already in clusters.json."""
    if not locale:
        return None
    parts = locale.split('-')
    lang = parts[0].lower()
    region = parts[1].upper() if len(parts) > 1 else None
    if lang == 'en' and region in (None, 'US'):
        return ['en']
    if region:
        return [lang, 'no', f'{lang}-{region}'] if lang == 'nb' else [lang, f'{lang}-{region}']
    return [lang]


def script_clusters():
    """Read the cluster list from the site-wide language script (variables P and C)."""
    req = urllib.request.Request(SITE + '/christmas-events-for-kids', headers={**HDR})
    s = urllib.request.urlopen(req, timeout=90).read(400_000).decode('utf-8', 'ignore')
    m = re.search(r"C=(\[\".*?\"\]),\s*\n?\s*p=location", s, re.S)
    if not m:
        return None
    prefix = re.search(r"var P='([^']+)'", s)
    prefix = prefix.group(1) if prefix else '/christmas-events/'
    out = []
    for c in json.loads(m.group(1)):
        no_xd = c.startswith('~')
        members, xd = [], None
        for part in (c[1:] if no_xd else c).split('|'):
            code, _, q = part.partition(':')
            q = q if q.startswith('/') else prefix + q
            members.append((code, path_of(q)))
            if code == 'en-US' or (code == 'en' and not xd):
                xd = path_of(q)
        out.append({'members': members, 'x_default': xd})
    return out


class Clusters:
    def __init__(self, data):
        self.data = data
        self.where = {}
        for c in data['clusters']:
            for p in c['pages']:
                self.where[path_of(p['url'])] = c

    def used_codes(self, c):
        return {code for p in c['pages'] for code in p['hreflang']}

    def add_pair(self, a_path, a_codes, b_path, b_codes, name):
        ca, cb = self.where.get(a_path), self.where.get(b_path)
        if ca and cb:
            return None if ca is cb else f'{a_path} and {b_path} are already in different clusters ({ca["name"]}, {cb["name"]})'
        if not ca and not cb:
            if set(a_codes) & set(b_codes):
                return f'{a_path} and {b_path} would share a code ({a_codes} / {b_codes})'
            english = a_path if a_codes[0] == 'en' else b_path if b_codes[0] == 'en' else a_path
            c = {'name': name, 'x_default': SITE + english, 'pages': [
                {'url': SITE + a_path, 'hreflang': a_codes}, {'url': SITE + b_path, 'hreflang': b_codes}]}
            if build_hreflang.check({'site': SITE, 'clusters': [c]}):
                return f'{a_path} + {b_path}: invalid codes {a_codes} / {b_codes}'
            self.data['clusters'].append(c)
            self.where[a_path] = self.where[b_path] = c
            return 'added'
        # One page is already in a cluster: the other joins it.
        c, new_path, new_codes, partner = (ca, b_path, b_codes, a_path) if ca else (cb, a_path, a_codes, b_path)
        used = self.used_codes(c)
        lang = new_codes[0].split('-')[0]
        codes = [x for x in new_codes if x not in used]
        if any(u.split('-')[0] == lang for u in used):
            # The cluster already has this language (e.g. the hub has en-US, en-GB...):
            # a bare "en" would make this page the default for every English speaker.
            codes = [x for x in codes if '-' in x]
        if not codes:
            # e.g. an English country guide joining the hub: use en-<partner's country>
            partner_codes = next(p['hreflang'] for p in c['pages'] if path_of(p['url']) == partner)
            region = next((x.split('-')[1] for x in partner_codes if '-' in x), None)
            cand = f'{new_codes[0].split("-")[0]}-{region}' if region else None
            if cand and cand not in used:
                codes = [cand]
        if not codes:
            return f'{new_path} could join {c["name"]} but its codes {new_codes} are all taken there'
        c['pages'].append({'url': SITE + new_path, 'hreflang': codes})
        if build_hreflang.check({'site': SITE, 'clusters': [c]}):
            c['pages'].pop()
            return f'{new_path} joining {c["name"]} with {codes} failed the checks'
        self.where[new_path] = c
        return 'added'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--sitemap')
    ap.add_argument('--sweep')
    ap.add_argument('--report', default='auto-pair-report.md')
    args = ap.parse_args()

    src = os.path.join(HERE, 'clusters.json')
    data = json.load(open(src, encoding='utf-8'))
    before = json.dumps(data, sort_keys=True)
    cl = Clusters(data)
    pages = site_pages(args.sitemap)
    now = time.time()

    ignore_file = os.path.join(HERE, 'hreflang-ignore.txt')
    ignored = set()
    if os.path.exists(ignore_file):
        ignored = {l.split('#')[0].strip() for l in open(ignore_file, encoding='utf-8')} - {''}

    if os.path.exists(args.state):
        state = json.load(open(args.state))
    else:
        state = None
    if state is None and not args.sweep:
        # First run: remember everything that exists today; only newer pages get opened.
        state = {'seen': sorted(pages), 'pending': {}}
        json.dump(state, open(args.state, 'w'))
        open(args.report, 'w').write(f'First run: remembered {len(pages):,} existing pages. New pages will be checked from the next run.\n')
        print(open(args.report).read())
        return 0
    state = state or {'seen': [], 'pending': {}}
    seen = set(state['seen'])
    pending = {p: t for p, t in state.get('pending', {}).items() if now - t < PENDING_DAYS * 86400}

    todo = sorted(p for p in pages if p not in seen and p not in cl.where and p not in ignored)
    todo = todo[:MAX_NEW_PER_RUN] + [p for p in pending if p not in todo]
    if args.sweep:
        todo += [path_of(l.strip()) for l in open(args.sweep) if l.strip()]
    todo = list(dict.fromkeys(todo))

    with cf.ThreadPoolExecutor(8) as ex:
        info = {i['path']: i for i in ex.map(fetch, todo)}

    added, review = [], []

    # 0. Entries in the site script's cluster list that clusters.json doesn't have yet.
    try:
        sc = script_clusters()
    except Exception as e:
        sc = None
        review.append(f'Could not read the cluster list from the site script ({str(e)[:80]})')
    for entry in sc or []:
        by_page = {}
        for code, q in entry['members']:
            by_page.setdefault(q, []).append(code)
        missing = [q for q in by_page if q not in cl.where and q not in ignored]
        if not missing:
            continue
        homes = {id(cl.where[q]): cl.where[q] for q in by_page if q in cl.where}
        if len(homes) > 1:
            review.append('Script cluster spans two clusters in clusters.json: ' + ', '.join(f'`{q}`' for q in by_page))
            continue
        for q in missing:
            if q not in info:
                info[q] = fetch(q)
        live = [q for q in missing if info[q].get('ok')]
        for q in missing:
            if q not in live:
                review.append(f'`{q}` is in the site script\'s cluster list but is not live or not canonical (status {info[q].get("status")})')
        def lang_ok(q):
            loc = info[q].get('locale')
            if loc and loc.split('-')[0].lower() != by_page[q][0].split('-')[0].lower():
                review.append(f'`{q}` is listed as {by_page[q][0]} in the site script but declares {loc}')
                return False
            return True
        live = [q for q in live if lang_ok(q)]
        if not live:
            continue
        if homes:
            home = next(iter(homes.values()))
            partner = next(q for q in by_page if q in cl.where)
            for q in live:
                res = cl.add_pair(partner, None, q, by_page[q], home['name'])
                if res == 'added':
                    codes = next(pp['hreflang'] for pp in home['pages'] if path_of(pp['url']) == q)
                    added.append(f'`{q}` ({",".join(codes)}) joined {home["name"]} (from the site script)')
                elif res:
                    review.append(res)
        else:
            pages_in = [q for q in by_page if q in live]
            if len(pages_in) < 2:
                continue
            xd = entry['x_default'] if entry['x_default'] in pages_in else pages_in[0]
            c = {'name': 'script:' + pages_in[0].rsplit('/', 1)[-1], 'x_default': SITE + xd,
                 'pages': [{'url': SITE + q, 'hreflang': by_page[q]} for q in pages_in]}
            errs = build_hreflang.check({'site': SITE, 'clusters': [c]})
            if errs:
                review.append('Script cluster not added: ' + '; '.join(errs[:3]))
                continue
            data['clusters'].append(c)
            for q in pages_in:
                cl.where[q] = c
            added.append('New cluster from the site script: ' + ', '.join(f'`{q}` ({",".join(by_page[q])})' for q in pages_in))

    # 1. Language switcher pairs.
    targets = {q for i in info.values() if i['ok'] for _, q in i['switchers'] if q not in info}
    with cf.ThreadPoolExecutor(8) as ex:
        for i in ex.map(fetch, sorted(targets)):
            info[i['path']] = i
    for p, i in sorted(info.items()):
        if not i.get('ok') or not i.get('switchers') or p in ignored:
            continue
        for code, q in i['switchers']:
            if q in ignored or q == p:
                continue
            j = info.get(q)
            if not j or not j.get('ok'):
                pending[p] = pending.get(p, now)
                review.append(f'`{p}` links to `{q}` ({code}) but that page is not live yet (status {j.get("status") if j else "?"}); retrying for {PENDING_DAYS} days')
                continue
            if not j['locale'] or j['locale'].split('-')[0].lower() != code.split('-')[0].lower():
                review.append(f'`{p}` says `{q}` is in {code}, but that page declares {j["locale"]}')
                continue
            if not i['locale']:
                review.append(f'`{p}` has a language switcher but declares no language of its own; not paired')
                continue
            a_codes, b_codes = codes_for(i['locale']), codes_for(j['locale'])
            if a_codes[0] == b_codes[0]:
                review.append(f'`{p}` and `{q}` are both {a_codes[0]}; not paired')
                continue
            res = cl.add_pair(p, a_codes, q, b_codes, 'auto:' + p.rsplit('/', 1)[-1])
            if res == 'added':
                added.append(f'`{p}` ({",".join(a_codes)}) + `{q}` ({",".join(b_codes)})')
                pending.pop(p, None)
            elif res:
                review.append(res)
            else:
                pending.pop(p, None)

    # 2. Christmas Eve pages across countries: national pages join the Christmas Eve
    #    hub, denomination pages pair by matching URL. New sections often take a while
    #    to show up in the Squarespace sitemap, so partners are also checked directly.
    def live(x):
        if x not in info:
            info[x] = fetch(x)
        return info[x].get('ok')

    hub = next((c for c in data['clusters'] if c['name'] == EVE_HUB_CLUSTER), None)
    for p in sorted(info):
        m = re.match(r'^/([a-z-]+)/([a-z-]+)$', p)
        if not m or m.group(1) not in EVE_SECTIONS or not info[p].get('ok') or p in cl.where:
            continue
        sec, slug = m.groups()
        if hub and EVE_HUBS.get(sec) == slug:
            codes = [x for x in EVE_SECTIONS[sec] if x not in cl.used_codes(hub)]
            if codes:
                hub['pages'].append({'url': SITE + p, 'hreflang': codes})
                cl.where[p] = hub
                added.append(f'`{p}` ({",".join(codes)}) joined {EVE_HUB_CLUSTER}')
            else:
                review.append(f'`{p}`: {EVE_SECTIONS[sec]} already used in {EVE_HUB_CLUSTER}')
            continue
        if not slug.endswith('-christmas-eve-services'):
            continue
        members = [f'/{s2}/{slug}' for s2 in EVE_ORDER if f'/{s2}/{slug}' == p or f'/{s2}/{slug}' in cl.where or live(f'/{s2}/{slug}')]
        if len(members) < 2:
            continue
        existing = next((cl.where[x] for x in members if x in cl.where), None)
        for x in members:
            if x in cl.where:
                continue
            codes = EVE_SECTIONS[x.split('/')[1]]
            if existing:
                free = [c2 for c2 in codes if c2 not in cl.used_codes(existing)]
                if not free:
                    review.append(f'`{x}`: {codes} already used in {existing["name"]}')
                    continue
                existing['pages'].append({'url': SITE + x, 'hreflang': free})
                cl.where[x] = existing
                added.append(f'`{x}` ({",".join(free)}) joined {existing["name"]}')
            else:
                other = next((y for y in members if y != x and y not in cl.where), None)
                if not other:
                    continue
                res = cl.add_pair(other, EVE_SECTIONS[other.split('/')[1]], x, codes, 'christmas-eve-services:' + slug)
                if res == 'added':
                    existing = cl.where[x]
                    first = min((path_of(pp['url']) for pp in existing['pages']), key=lambda u: EVE_ORDER.index(u.split('/')[1]))
                    existing['x_default'] = SITE + first
                    added.append(f'`{other}` + `{x}` (new {slug} cluster)')
                elif res:
                    review.append(res)

    # Every clustered page must be covered by a Worker route, or it won't be tagged.
    routes_file = os.path.join(HERE, 'worker-routes.txt')
    if os.path.exists(routes_file):
        pats = [l.strip().split('/', 1)[1] for l in open(routes_file) if l.strip() and not l.startswith('#')]
        def covered(path):
            rel = path.lstrip('/')
            return any(rel.startswith(pt[:-1]) if pt.endswith('*') else rel == pt for pt in pats)
        outside = sorted(path for path in cl.where if not covered(path))
        if outside:
            review.append(f'{len(outside)} clustered page(s) are outside the Worker routes in tools/worker-routes.txt, so they are not tagged on the site; add a route in Cloudflare and to that file. First: `{outside[0]}`')

    errors = build_hreflang.check(data)
    if errors:
        review.append('Not saved, clusters.json would fail its checks: ' + '; '.join(errors[:5]))
        data = json.loads(before)
    elif json.dumps(data, sort_keys=True) != before:
        json.dump(data, open(src, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        open(build_hreflang.OUT, 'w', encoding='utf-8').write(build_hreflang.build(data))

    seen |= {p for p, i in info.items() if p in pages and i.get('status') == 200}
    state = {'seen': sorted(seen), 'pending': pending}
    json.dump(state, open(args.state, 'w'))

    lines = [f'Checked {len(todo):,} new or retried pages (plus {len(targets):,} switcher targets).', '']
    if added:
        lines += [f'## Added ({len(added)})', ''] + [f'- {a}' for a in added] + ['']
    if review:
        lines += [f'## Needs a look ({len(review)})', ''] + [f'- {r}' for r in sorted(set(review))] + ['']
    if not added and not review:
        lines.append('Nothing new to pair.')
    open(args.report, 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    sys.exit(main())
