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
i = 0
for host, n, k in (('rally-takes-the-train-site.squarespace.com', 6, 150), ('rally-takes-the-train-site.squarespace.com', 16, 300), ('rally-takes-the-train-site.squarespace.com', 40, 500),
                   ('www.rallytakesthetrain.com', 16, 300), ('www.rallytakesthetrain.com', 40, 500)):
    sl = ps[i:i + k]; i += k
    t = time.time()
    with cf.ThreadPoolExecutor(n) as ex:
        rs = list(ex.map(f, [f'https://{host}{p}' for p in sl]))
    el = time.time() - t
    ok = [r for r in rs if r[0] == 200] or [(0, 0, 0, 0, 0, 0)]
    m = lambda j: round(sum(r[j] for r in ok) / len(ok), 3)
    print(f'{host[:6]} x{n}: {len(sl) / el:.1f} pages/s, statuses {dict(collections.Counter(r[0] for r in rs))}, to headers {m(1)}s, body {m(2)}s, gunzip {m(3)}s, {m(4) / 1e6:.2f} MB on the wire, {m(5) / 1e6:.2f} MB page', flush=True)
print('cpus', os.cpu_count())
