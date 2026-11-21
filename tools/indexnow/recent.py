"""Send every page updated in the last N hours to IndexNow.

Squarespace's sitemap dates lag behind edits by days, so a page updated in place is not re-submitted by the
sitemap-based submitter (the rally-indexnow Worker) until much later. Squarespace only lists a post's real
update time in its collection lists, so this walks every collection (newest first, in parallel time slices),
takes the posts whose updatedOn falls in the window, and submits them in one request.

Usage: python3 tools/indexnow/recent.py [--hours 26] [--dry]
"""
import argparse, collections, concurrent.futures as cf, gzip, json, os, re, sys, time, urllib.request

SITE = os.environ.get('RTT_SITE', 'https://www.rallytakesthetrain.com')
PUBLIC = 'https://www.rallytakesthetrain.com'
UA = 'rtt-indexnow-recent/1.0'
HDR = {'User-Agent': UA, **({'x-rtt-key': os.environ['RTT_BOT_KEY']} if os.environ.get('RTT_BOT_KEY') else {})}
KEY = '769b49195b15aba74934cd930ea399db'   # public: the key file served on the site
ENDPOINTS = ['https://api.indexnow.org/indexnow', 'https://www.bing.com/indexnow', 'https://yandex.com/indexnow']


def get_json(path):
    for i in range(6):
        try:
            r = urllib.request.urlopen(urllib.request.Request(SITE + path + ('&' if '?' in path else '?') + 'format=json', headers={**HDR, 'Accept-Encoding': 'gzip'}), timeout=90)
            raw = r.read()
            return json.loads(gzip.decompress(raw) if r.headers.get('Content-Encoding') == 'gzip' else raw)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            time.sleep(6 * (i + 1) if e.code in (429, 503) else 3)
        except Exception:
            time.sleep(3)
    return None


def walk(coll, hi, lo, since):
    """Posts of one collection published in [lo, hi) whose updatedOn >= since: (url, updatedOn)."""
    out, cur, pages = [], hi, 0
    while cur > lo:
        j = get_json(f'/{coll}?offset={cur}')
        pages += 1
        items = (j or {}).get('items') or []
        if not items:
            break
        for it in items:
            p = it.get('publishOn') or 0
            if p < lo:
                return out, pages
            if (it.get('updatedOn') or 0) >= since and it.get('workflowState', 1) == 1 and it.get('fullUrl'):
                out.append((it['fullUrl'], it['updatedOn']))
        nxt = ((j.get('pagination') or {}).get('nextPageOffset')) or 0
        if not nxt or nxt >= cur:
            break
        cur = nxt
    return out, pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=float, default=26)
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--threads', type=int, default=6)
    a = ap.parse_args()
    now = int(time.time() * 1000)
    since = now - int(a.hours * 3600000)
    sm = urllib.request.urlopen(urllib.request.Request(SITE + '/sitemap.xml', headers=HDR), timeout=120).read().decode('utf-8', 'replace')
    n = collections.Counter(re.findall(r'<loc>https://www\.rallytakesthetrain\.com/([a-z0-9-]+)/[^<]+</loc>', sm))
    colls = sorted(c for c, k in n.items() if k >= 3)
    # time slices, newest first: six hours each for the last 50 days, then one for everything older
    step, slices = 6 * 3600000, []
    hi = now + 3600000
    while hi > now - 50 * 86400000:
        slices.append((hi, hi - step))
        hi -= step
    slices.append((hi, 0))
    jobs = [(c, h, l) for c in colls for (h, l) in (slices if n[c] > 400 else [(now + 3600000, 0)])]
    found, pages = {}, 0
    with cf.ThreadPoolExecutor(a.threads) as ex:
        for res, pg in ex.map(lambda j: walk(j[0], j[1], j[2], since), jobs):
            pages += pg
            for u, t in res:
                found[u] = max(t, found.get(u, 0))
    urls = [PUBLIC + u for u, _ in sorted(found.items(), key=lambda kv: -kv[1])]
    print(f'{len(colls)} collections, {pages} list pages read, {len(urls)} pages updated in the last {a.hours:g} hours', flush=True)
    for u in urls[:8]:
        print('  ', u)
    if a.dry or not urls:
        return
    sent = 0
    for i in range(0, len(urls), 2000):
        batch, ok = urls[i:i + 2000], False
        body = json.dumps({'host': 'www.rallytakesthetrain.com', 'key': KEY, 'keyLocation': f'{PUBLIC}/{KEY}.txt', 'urlList': batch}).encode()
        for ep in ENDPOINTS:
            try:
                r = urllib.request.urlopen(urllib.request.Request(ep, data=body, headers={'content-type': 'application/json; charset=utf-8'}), timeout=60)
                print(f'IndexNow {ep.split("/")[2]}: {len(batch)} pages, HTTP {r.status}', flush=True)
                ok = True
                break
            except urllib.error.HTTPError as e:
                print(f'IndexNow {ep.split("/")[2]}: HTTP {e.code}', flush=True)
            except Exception as e:
                print(f'IndexNow {ep.split("/")[2]}: {e}', flush=True)
        sent += len(batch) if ok else 0
        time.sleep(5)
    print(f'{sent} of {len(urls)} pages accepted')
    if sent < len(urls):
        sys.exit(1)


if __name__ == '__main__':
    main()
