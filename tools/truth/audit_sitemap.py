#!/usr/bin/env python3
"""Audit the Christmas events counts against the sitemap.

Every /christmas-events/ URL in https://www.rallytakesthetrain.com/sitemap.xml is either a
city page or guide (counted in tools/truth/live.json) or an event page. This checks:

  1. every city page's live event cards match its count in live.json
  2. no page with event cards is missing from the count
  3. every upcoming event page is listed on a city page (if not, it is not counted anywhere)

Writes tools/truth/audit.json and prints a summary. Run: python3 tools/truth/audit_sitemap.py
"""
import collections, concurrent.futures as cf, datetime, html as H, json, os, re, sys, time, unicodedata, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from analyze import analyze

SITE = 'https://www.rallytakesthetrain.com'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 rtt-audit'
# Our own pipeline proves itself to Cloudflare with this header (GitHub secret RTT_BOT_KEY), so bot protection never challenges it.
HDR = {'User-Agent': UA, **({'x-rtt-key': os.environ['RTT_BOT_KEY']} if os.environ.get('RTT_BOT_KEY') else {})}


def norm_name(s):
    """Card or page name, compared loosely: tags and entities out, accents and punctuation ignored."""
    s = H.unescape(re.sub(r'<[^>]+>', ' ', s or '')).lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r'\s*[|:]\s*rally takes the train.*$', '', s)
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def body(path, tries=6):
    """A post's Squarespace JSON item. Backs off on 429/503 (Squarespace rate limiting after the counts
    crawl); returns None only when the page really could not be read, so callers can tell 'unreadable'
    apart from 'not listed'. 404/410 -> {} (gone)."""
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(SITE + path + '?format=json', headers={**HDR}), timeout=60)
            it = json.loads(r.read()).get('item') or {}
            return path, it
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return path, {}
            if e.code in (429, 503):
                try:
                    wait = int(e.headers.get('Retry-After') or 0)
                except ValueError:
                    wait = 0
                time.sleep(min(max(wait, 8 * (i + 1)), 120))
                continue
            time.sleep(3)
        except Exception:
            time.sleep(3)
    return path, None


def main():
    today = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=12)).date().isoformat()
    live = json.load(open(os.path.join(HERE, 'live.json'), encoding='utf-8'))
    sm = urllib.request.urlopen(urllib.request.Request(SITE + '/sitemap.xml', headers={**HDR}), timeout=120).read().decode()
    urls = sorted(set(re.findall(r'<loc>https://www\.rallytakesthetrain\.com(/christmas-events/[^<]+)</loc>', sm)))
    counted = set(live['pages']) | set(live['guides'])
    city_pages = sorted(p for p in counted if p in live['pages'])
    others = [p for p in urls if p not in counted]
    print(f'sitemap: {len(urls):,} Christmas events URLs; {len(city_pages):,} city pages counted, {len(others):,} other pages', file=sys.stderr)

    # 1. City pages: cards vs counts, and which event pages they list
    listed = {}           # event page path -> city page listing it
    mismatch = []
    card_names = {}       # city page -> normalised names of its event cards
    unread_city = []      # city pages that could not be read: their events are unknown, not "not listed"
    with cf.ThreadPoolExecutor(6) as ex:
        for p, it in ex.map(body, city_pages + sorted(live['guides'])):
            if not it:   # unreadable (None) or gone ({}): its events are unknown here
                if p in live['pages']:
                    unread_city.append(p)
                continue
            b = it.get('body') or ''
            if p in live['pages']:
                a = analyze('<html><head></head><body>' + b + '</body></html>', today)
                want = live['pages'][p][0]
                if a['events'] != want:
                    mismatch.append([p, want, a['events']])
            for m in re.finditer(r'<section class="rtt-pe-ride[" ]', b):
                seg = b[m.end():m.end() + 30000]   # verified cards run to ~15 KB
                nxt = re.search(r'<section class="rtt-pe-ride[" ]', seg)
                seg = seg[:nxt.start()] if nxt else seg
                for h in re.findall(r'href="(/christmas-events/[a-z0-9-]+)"', seg):
                    if h not in counted:
                        listed.setdefault(h, p)
                nm = re.search(r'<h3[^>]*>(.*?)</h3>', seg, re.S)
                if nm:
                    card_names.setdefault(p, set()).add(norm_name(nm.group(1)))

    # 2./3. Everything else in the sitemap that no city page lists
    unlisted = [p for p in others if p not in listed]
    uncounted_city, upcoming, past, other, link_missing = [], [], [], [], []
    with cf.ThreadPoolExecutor(6) as ex:
        for p, it in ex.map(body, unlisted):
            if it is None:
                other.append([p, 'unreachable'])
                continue
            b = it.get('body') or ''
            cards = len(re.findall(r'<section class="rtt-pe-ride[" ]', b))
            if cards:
                uncounted_city.append([p, cards])
                continue
            ends = re.findall(r'"endDate":\s*"(\d{4}-\d\d-\d\d)', b) or re.findall(r'"startDate":\s*"(\d{4}-\d\d-\d\d)', b)
            home = next((h for h in re.findall(r'href="(/christmas-events/[a-z0-9-]+)"', b) if h in live['pages']), '')
            if not it:
                other.append([p, 'gone'])
            elif not ends:
                other.append([p, 'no event dates'])
            elif max(ends) >= today and norm_name(it.get('title', '')) in card_names.get(home, ()):
                link_missing.append([p, home, it.get('title', '')])   # counted (its card is there) but the card doesn't link this page
            elif max(ends) >= today:
                upcoming.append([p, max(ends), home, it.get('title', '')])
            else:
                past.append([p, max(ends), home])

    def country(home):
        c = live['cities'].get(home)
        if c:
            return c[3]
        for q, c in live['cities'].items():
            if home in c[6]:
                return c[3]
        return '?'

    # An event whose own page points at a city page that could not be read is not known to be unlisted.
    unread = set(unread_city)
    unknown = [u for u in upcoming if u[2] in unread]
    upcoming = [u for u in upcoming if u[2] not in unread]
    by_country = collections.Counter(country(u[2]) for u in upcoming)
    out = {'today': today, 'sitemap_urls': len(urls), 'city_pages': len(city_pages), 'city_pages_unread': unread_city,
           'upcoming_unknown_city_unread': len(unknown), 'event_pages_listed': len(listed),
           'count_mismatch': mismatch, 'uncounted_city_pages': uncounted_city,
           'upcoming_not_listed': upcoming, 'upcoming_not_listed_by_country': dict(by_country.most_common()),
           'card_without_link': link_missing, 'past_not_listed': len(past), 'other': other}
    json.dump(out, open(os.path.join(HERE, 'audit.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in out.items()}, indent=1))


if __name__ == '__main__':
    main()
