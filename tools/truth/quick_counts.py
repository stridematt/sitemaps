"""Quick count update for a few city pages, right after they are published (minutes, not the 45-minute full run).

Usage: python3 tools/truth/quick_counts.py /christmas-events/<city-page> [...]

Reads only the given city pages, then updates tools/truth/live.json in place:
  pages[p]                 the page's own upcoming events and free events
  cities[main]             the city (fuller language version, as build_truth.py counts it)
  countries / states / total, and the country and state guides, by the change in the city's count
A city page that live.json does not know yet (a new city) is added to its country when the page says which
country it is in. The full run (build_truth.py, every 3 hours) recomputes everything from scratch and
replaces these numbers; the quick update only keeps the site honest in between. Districts and regions are
left to the full run.
"""
import json, os, re, sys, urllib.request, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from analyze import analyze  # noqa: E402
from build_truth import HDR, SITE, own_country, ISO_NAME  # noqa: E402

LIVE = os.path.join(HERE, 'live.json')


def fetch(p):
    req = urllib.request.Request(SITE + p, headers={**HDR, 'x-rtt-raw': '1'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode('utf-8', 'replace')


def main(paths):
    live = json.load(open(LIVE, encoding='utf-8'))
    today = datetime.date.today().isoformat()
    cities, pages = live['cities'], live['pages']
    main_of = {}
    for m, c in cities.items():
        main_of[m] = m
        for a in c[6] or []:
            main_of[a] = m
    changed = []
    for p in paths:
        p = p if p.startswith('/christmas-events/') else '/christmas-events/' + p.strip('/')
        try:
            h = fetch(p)
        except Exception as e:
            print('skip', p, e)
            continue
        if '<section class="rtt-pe-ride' not in h:
            print('skip', p, 'no event cards')
            continue
        r = analyze(h, today)
        old = pages.get(p, [0, 0])
        pages[p] = [r['events'], r['free']]
        m = main_of.get(p)
        if not m:
            cc = own_country(h)
            country = ISO_NAME.get(cc) if cc else None
            if not country or country not in live['countries']:
                print('skip', p, 'new city, country unknown:', cc)
                continue
            name = re.sub(r'\s*\(\d{4}\)$', '', (re.search(r'<title>([^<]*)</title>', h) or [None, p])[1]).strip()
            cities[p] = [0, 0, name, country, '', 0, []]
            main_of[p] = m = p
            live['countries'][country]['cities'] = live['countries'][country].get('cities', 0) + 1
            live['total']['cities'] += 1
        c = cities[m]
        twins = [m] + list(c[6] or [])
        prev = {q: (old if q == p else (pages.get(q) or [0, 0])) for q in twins}
        old_best = max(twins, key=lambda q: prev[q][0])
        best = max(twins, key=lambda q: (pages.get(q) or [0, 0])[0])
        be, bf = pages.get(best, [0, 0])
        # a city with district pages counts more than its fuller page: keep that surplus
        extra_e = max(0, c[0] - prev[old_best][0])
        extra_f = max(0, c[1] - prev[old_best][1])
        ne, nf = be + extra_e, bf + extra_f
        de, df = ne - c[0], nf - c[1]
        dw = (1 if ne and not c[0] else 0) - (1 if c[0] and not ne else 0)
        c[0], c[1] = ne, nf
        if de or df or dw:
            co = live['countries'].get(c[3])
            for agg in [live['total'], co] + ([live['states'].get(c[4])] if c[4] else []):
                if not agg:
                    continue
                agg['events'] += de
                agg['free'] += df
                agg['cities_with_events'] += dw
            for g in live['guides'].values():
                if (g['kind'] == 'country' and g['name'] == c[3]) or (g['kind'] == 'state' and c[4] and g['name'] == (live['states'].get(c[4]) or {}).get('name')):
                    g['e'] += de
                    g['f'] += df
                    g['cw'] = g.get('cw', 0) + dw
        changed.append((p, old, pages[p], m, c[0], c[1]))
        print(f'{p}: page {old[0]}/{old[1]} -> {pages[p][0]}/{pages[p][1]}; city {m} -> {c[0]}/{c[1]} ({de:+d})')
    if changed:
        live['generated'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
        json.dump(live, open(LIVE, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'{len(changed)} page(s) updated; total {live["total"]["events"]:,} events')


if __name__ == '__main__':
    main([a for a in sys.argv[1:] if a.strip()])
