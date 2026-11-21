"""Temporary: how fast can this runner read city pages? (rate, latency, throttling, by host and parallelism)"""
import collections, concurrent.futures as cf, gzip, json, os, time, urllib.request
d = json.load(open('tools/truth/live.json'))
ps = list(d['cities'])
HDR = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36', 'Accept-Encoding': 'gzip',
       **({'x-rtt-key': os.environ['RTT_BOT_KEY']} if os.environ.get('RTT_BOT_KEY') else {})}
def f(u):
    t = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=HDR), timeout=60)
        t1 = time.time(); b = r.read(); t2 = time.time()
        n = len(gzip.decompress(b)) if r.headers.get('Content-Encoding') == 'gzip' else len(b)
        return 200, t1 - t, t2 - t1, time.time() - t2, len(b), n
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t, 0, 0, 0, 0
    except Exception as e:
        return 0, time.time() - t, 0, 0, 0, 0
import sys
T0 = time.time()
for n, k in ((8, 1500), (12, 1200)):
    sl = ps[:k] if n == 8 else ps[1500:1500 + k]
    t = time.time(); done = 0; first429 = None; per = collections.Counter()
    with cf.ThreadPoolExecutor(n) as ex:
        for r in ex.map(f, [f'https://rally-takes-the-train-site.squarespace.com{p}' for p in sl]):
            done += 1
            per[(int((time.time() - t) // 20), r[0])] += 1
            if r[0] == 429 and first429 is None:
                first429 = (done, round(time.time() - t, 1))
    el = time.time() - t
    print(f'x{n}: {k} pages in {el:.0f}s = {k / el:.1f}/s; first 429 at (page, seconds) {first429}; per 20s window (window, status): {sorted(per.items())}', flush=True)
    time.sleep(60)
