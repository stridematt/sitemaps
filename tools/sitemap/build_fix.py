#!/usr/bin/env python3
"""Keep https://www.rallytakesthetrain.com/sitemap.xml complete and clean.

Squarespace's own sitemap lags behind new pages and keeps URLs that now return 404 or
redirect. This builds tools/sitemap/fix.json, which the Cloudflare Worker applies to the
sitemap as it is served:

  add:    live, indexable pages Squarespace's sitemap does not list yet
          (every Christmas events city and country/state guide, every Christmas Eve page)
  remove: URLs in Squarespace's sitemap that return 404/410 or redirect

Every URL in the sitemap is re-checked about every two days (a slice per run, plus every
URL that failed last time). Removals are refused if they would drop more than 3% of the
sitemap at once (that points to an outage, not real deletions).

Run: python3 tools/sitemap/build_fix.py --state .state/sitemap.json
"""
import argparse, concurrent.futures as cf, datetime, gzip, json, os, re, sys, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'llms'))
import build_llms as L  # collection(), EVE_SECTIONS

SITE = 'https://www.rallytakesthetrain.com'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 rtt-sitemap-check'
# Our own pipeline proves itself to Cloudflare with this header (GitHub secret RTT_BOT_KEY), so bot protection never challenges it.
HDR = {'User-Agent': UA, **({'x-rtt-key': os.environ['RTT_BOT_KEY']} if os.environ.get('RTT_BOT_KEY') else {})}
MAX_REMOVE_SHARE = 0.03


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


FINAL = (200, 301, 302, 307, 308, 404, 410)


def status(path):
    """(path, status, redirect target path) without following redirects; status 0 = no answer we trust."""
    for method in ('HEAD', 'GET'):
        try:
            r = OPENER.open(urllib.request.Request(SITE + path, method=method, headers={**HDR}), timeout=25)
            return path, r.status, None
        except urllib.error.HTTPError as e:
            if e.code == 405 and method == 'HEAD':
                continue
            loc = e.headers.get('Location') or ''
            loc = re.sub(r'^https?://www\.rallytakesthetrain\.com', '', loc) if loc else None
            return path, (e.code if e.code in FINAL else 0), (loc if loc and loc.startswith('/') else None)
        except Exception:
            return path, 0, None
    return path, 0, None


def indexable(path):
    """True when a page is live, not noindex, and canonical to itself."""
    try:
        r = OPENER.open(urllib.request.Request(SITE + path, headers={**HDR}), timeout=30)
        if r.status != 200:
            return path, False
        head = r.read(120000).decode('utf-8', 'ignore')
        head = head[:head.find('</head>') + 7] if '</head>' in head else head
        if re.search(r'<meta[^>]+name="robots"[^>]+noindex', head, re.I):
            return path, False
        can = re.search(r'<link rel="canonical" href="([^"]+)"', head)
        if can and can.group(1).replace(SITE, '').rstrip('/') != path.rstrip('/'):
            return path, False
        return path, True
    except Exception:
        return path, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', default='.state/sitemap.json')
    ap.add_argument('--per-run', type=int, default=3000, help='sitemap URLs re-checked per run')
    args = ap.parse_args()
    today = datetime.date.today().isoformat()

    seed = os.path.join(HERE, 'seed.json.gz')
    if os.path.exists(args.state):
        state = json.load(open(args.state, encoding='utf-8'))
    elif os.path.exists(seed):
        state = json.load(gzip.open(seed, 'rt', encoding='utf-8'))
    else:
        state = {}
    checks = state.setdefault('checks', {})   # path -> [status, date checked]
    added = state.setdefault('added', {})      # path -> date first added (its lastmod)

    # Squarespace's own sitemap (the Worker passes it through untouched with this header)
    req = urllib.request.Request(SITE + '/sitemap.xml', headers={**HDR, 'x-rtt-raw': '1'})
    sm = urllib.request.urlopen(req, timeout=120).read().decode('utf-8')
    listed = re.findall(r'<loc>https://www\.rallytakesthetrain\.com([^<]*)</loc>', sm)
    listed_set = set(listed)
    if len(listed) < 1000:
        raise SystemExit(f'Squarespace sitemap looks broken ({len(listed)} URLs); not changing anything')
    log(f'Squarespace sitemap: {len(listed):,} URLs')

    # 1. Re-check a slice of the sitemap, plus everything that failed last time.
    failed_before = [p for p in listed if p in checks and checks[p][0] != 200]
    order = sorted((p for p in listed if p not in failed_before), key=lambda p: checks.get(p, [0, ''])[1])
    todo = failed_before + order[:args.per_run]
    targets = state.setdefault('targets', {})  # redirected URL -> where it goes now
    with cf.ThreadPoolExecutor(8) as ex:
        for p, st, loc in ex.map(status, todo):
            if st:  # rate-limited or unreachable: keep the last result
                checks[p] = [st, today]
                if loc:
                    targets[p] = loc
                else:
                    targets.pop(p, None)
    for p in list(checks):
        if p not in listed_set and p not in added:
            checks.pop(p)
    for p in list(targets):
        if p not in listed_set:
            targets.pop(p)
    remove = sorted(p for p in listed if checks.get(p, [200])[0] in (404, 410, 301, 302, 307, 308))
    log(f'checked {len(todo):,} URLs this run; {len(remove)} to remove: {remove[:8]}')
    if len(remove) > MAX_REMOVE_SHARE * len(listed):
        log(f'refusing: {len(remove)} removals is more than {MAX_REMOVE_SHARE:.0%} of the sitemap')
        prev = os.path.join(HERE, 'fix.json')
        remove = json.load(open(prev))['remove'] if os.path.exists(prev) else []

    # 2. Pages the site has that Squarespace's sitemap is missing.
    want = set()
    ids = os.path.join(ROOT, 'tools', 'sqsp', 'ids.json')
    if os.path.exists(ids):
        want.update(json.load(open(ids, encoding='utf-8')))
    live = os.path.join(ROOT, 'tools', 'truth', 'live.json')
    if os.path.exists(live):
        lj = json.load(open(live, encoding='utf-8'))
        want.update(lj.get('guides', {}))
        want.update(lj.get('pages', {}))
    for sec, *_ in L.EVE_SECTIONS:
        try:
            for slug, t, e in L.collection(sec):
                want.add(f'/{sec}/{slug}')
        except Exception as e:
            log(f'could not list {sec}: {e}')
    # where redirected URLs now point (a renamed page should be listed under its new address)
    want.update(t.split('?')[0].split('#')[0].rstrip('/') for t in targets.values() if t.startswith('/'))
    missing = sorted(p for p in want if p not in listed_set)
    fresh = [p for p in missing if p not in added or checks.get(p, [0, ''])[1] < today]
    with cf.ThreadPoolExecutor(8) as ex:
        for p, ok in ex.map(indexable, fresh):
            checks[p] = [200 if ok else 0, today]
            if ok:
                added.setdefault(p, today)
            else:
                added.pop(p, None)
    for p in list(added):
        if p in listed_set or p not in want:
            added.pop(p)  # Squarespace lists it now, or it is gone
    add = sorted([p, added[p]] for p in added if p not in listed_set)
    log(f'{len(missing)} pages missing from the Squarespace sitemap; adding {len(add)} that are live and indexable')

    out = {'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'listed': len(listed),
           'add': add, 'remove': remove}
    path = os.path.join(HERE, 'fix.json')
    prev = json.load(open(path)) if os.path.exists(path) else {}
    if prev.get('add') == add and prev.get('remove') == remove:
        out['generated'] = prev.get('generated', out['generated'])
        out['listed'] = prev.get('listed', out['listed'])
    json.dump(out, open(path, 'w', encoding='utf-8'), indent=0, separators=(',', ':'))
    os.makedirs(os.path.dirname(args.state) or '.', exist_ok=True)
    json.dump(state, open(args.state, 'w', encoding='utf-8'), separators=(',', ':'))
    log(f'sitemap fix: +{len(add)} pages, -{len(remove)} URLs')


if __name__ == '__main__':
    main()
