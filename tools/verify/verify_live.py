"""Check that the live site shows what the counts files say. Exits 1 with a list of problems.

Runs hourly (workflow verify-live). A failure emails the repo owner through GitHub, so a broken sync is
noticed within the hour instead of when someone spots a wrong number. What it checks:
  events hub      totals, every counted country in the finder data and in the by-country list, map lights
  services hub    services, churches and cities totals, map heading
  samples         a few city and guide pages carry the counts header
"""
import gzip, json, os, re, sys, time, urllib.request

SITE = 'https://www.rallytakesthetrain.com'
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
HDR = {'User-Agent': 'rtt-verify/1.0', 'Accept-Encoding': 'gzip', **({'x-rtt-key': os.environ['RTT_BOT_KEY']} if os.environ.get('RTT_BOT_KEY') else {})}
problems, notes = [], []


def get(path):
    for i in range(4):
        try:
            r = urllib.request.urlopen(urllib.request.Request(SITE + path, headers=HDR), timeout=90)
            b = r.read()
            return r.status, (gzip.decompress(b) if r.headers.get('Content-Encoding') == 'gzip' else b).decode('utf-8', 'ignore'), r.headers
        except Exception as e:
            err = e
            time.sleep(5 * (i + 1))
    return 0, '', {}


def num(s):
    return int(re.sub(r'\D', '', s) or 0)


def age_minutes(stamp):
    try:
        t = time.mktime(time.strptime(stamp, '%Y-%m-%dT%H:%MZ')) - time.timezone
        return (time.time() - t) / 60
    except Exception:
        return 1e9


def main():
    live = json.load(open(os.path.join(ROOT, 'tools/truth/live.json'), encoding='utf-8'))
    sv = json.load(open(os.path.join(ROOT, 'tools/services/live_services.json'), encoding='utf-8'))
    fresh = age_minutes(live.get('generated', '')) < 25   # the Worker picks new files up within about 10 minutes

    # ---- events hub ----
    st, h, hd = get('/christmas-events-for-kids')
    if st != 200 or 'id="xn-data"' not in h:
        problems.append(f'events hub: HTTP {st} or no finder data')
    else:
        T = live['total']
        m = re.search(r'<ul class="xn-stat"[^>]*>(.*?)</ul>', h, re.S)
        shown = [num(x) for x in re.findall(r'<b>([\d,.]+)</b>', m.group(1))] if m else []
        want = [T['events'], T['cities'], T['countries']]
        if shown[:3] != want:
            (notes if fresh else problems).append(f'events hub totals show {shown[:3]}, counts say {want}')
        D = json.loads(re.search(r'id="xn-data">(.*?)</script>', h, re.S).group(1))
        names = {c[1] for c in D.get('c', [])}
        rows = {x.strip() for x in re.findall(r'data-xn-cc="[A-Z]{2}"[^>]*><span class="xn-row__n">([^<]+)', h)}
        counted = set(live['countries'])
        miss_c = sorted(counted - names)
        miss_r = sorted(counted - rows)
        if miss_c:
            (notes if fresh else problems).append(f'{len(miss_c)} counted countries are not in the hub search: {miss_c[:12]}')
        if miss_r:
            (notes if fresh else problems).append(f'{len(miss_r)} counted countries have no row in the by-country list: {miss_r[:12]}')
        nog = sorted(n for n, v in live['countries'].items() if not v.get('guide') and not v.get('hub', 1) == 1 and n not in names)
        dark = [p[0] for p in D.get('p', []) if p[7] is None or p[8] is None]
        if len(dark) > 40:
            problems.append(f'{len(dark)} cities have no light on the hub map: {dark[:10]}')
        elif dark:
            notes.append(f'{len(dark)} cities without a map light yet: {dark[:10]}')
        notes.append(f'events hub: {shown[:3]} shown, {len(names)} countries in search, {len(rows)} rows, {len(D.get("p", []))} cities, header {hd.get("x-rtt-counts")}')

    # ---- services hub ----
    st, h, hd = get('/christmas-eve-services-near-me')
    if st != 200:
        problems.append(f'services hub: HTTP {st}')
    else:
        T = sv['total']
        m = re.search(r'<ul class="xn-stat"[^>]*>(.*?)</ul>', h, re.S)
        shown = [num(x) for x in re.findall(r'<b>([\d,.]+)</b>', m.group(1))] if m else []
        want = [T.get('services', 0), T['churches'], T['cities']]
        if shown[:3] != want:
            (notes if age_minutes(sv.get('generated', '')) < 25 else problems).append(f'services hub totals show {shown[:3]}, counts say {want}')
        mh = re.search(r'id="xn-map-h">([\d,]+) Christmas Eve services', h)
        if not mh:
            problems.append('services hub map heading does not lead with services')
        notes.append(f'services hub: {shown[:3]} shown, header {hd.get("x-rtt-counts")}')

    # ---- samples: the Worker is on these routes ----
    for p in ['/christmas-events/christmas-in-paris-with-kids', '/christmas-eve-services/connecticut', '/gottesdienste-heiligabend-deutschland/deutschland']:
        st, _, hd = get(p)
        if st != 200 or not hd.get('x-rtt-counts'):
            problems.append(f'{p}: HTTP {st}, counts header {hd.get("x-rtt-counts")!r} (Worker route missing or failing)')

    # ---- the counts files themselves ----
    if age_minutes(live.get('generated', '')) > 60 * 30:
        problems.append(f"events counts are {age_minutes(live['generated']) / 60:.0f} hours old (the hreflang workflow is not publishing)")
    if age_minutes(sv.get('generated', '')) > 60 * 30:
        problems.append(f"services counts are {age_minutes(sv['generated']) / 60:.0f} hours old (the services-counts workflow is not publishing)")
    nog = sorted(n for n, v in live['countries'].items() if not v.get('guide') and v.get('hub') == 0)
    if nog:
        problems.append(f'{len(nog)} new countries have no guide page on record: {nog[:12]}')

    for n in notes:
        print('note:', n)
    for p in problems:
        print('PROBLEM:', p)
    print(f'{len(problems)} problems')
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
