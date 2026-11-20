#!/usr/bin/env python3
"""Find translated or country pages on the live site that aren't in clusters.json yet,
and cluster pages that no longer exist. Prints a Markdown report; exit code 1 if
anything needs attention.

Usage: python3 tools/find_unpaired.py [path-to-site-sitemap.xml]
(without a path it downloads https://www.rallytakesthetrain.com/sitemap.xml)

It suggests pairs; it never edits clusters.json. Check each suggestion (a French
"Laval" page can be Laval, France while the English one is Laval, Quebec) and add
the right ones to clusters.json. Put rejected suggestions in tools/hreflang-ignore.txt.
"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = 'https://www.rallytakesthetrain.com'
CE = '/christmas-events/'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
# Our own pipeline proves itself to Cloudflare with this header (GitHub secret RTT_BOT_KEY), so bot protection never challenges it.
HDR = {'User-Agent': UA, **({'x-rtt-key': os.environ['RTT_BOT_KEY']} if os.environ.get('RTT_BOT_KEY') else {})}

# Local-language city guide prefixes in /christmas-events/
LOCAL_PREFIXES = {
    'weihnachten-mit-kindern-': 'de', 'noel-avec-les-enfants-': 'fr', 'kerst-met-kinderen-': 'nl',
    'natale-con-i-bambini-': 'it', 'navidad-con-ninos-': 'es', 'natal-com-criancas-': 'pt',
    'kodomo-christmas-': 'ja', 'activites-de-noel-pour-enfants-': 'fr',
}
EVE_SECTIONS = ['christmas-eve-services', 'christmas-eve-services-canada', 'christmas-eve-services-uk', 'messes-de-noel-quebec-canada']


def site_pages(path=None):
    if path:
        xml = open(path, encoding='utf-8').read()
    else:
        req = urllib.request.Request(SITE + '/sitemap.xml', headers={**HDR})
        xml = urllib.request.urlopen(req, timeout=120).read().decode('utf-8')
    locs = re.findall(r'<loc>([^<]+)</loc>', xml)
    return {l.replace(SITE, '', 1).rstrip('/') or '/' for l in locs if l.startswith(SITE) and not re.search(r'\.(jpe?g|png|gif|webp)$', l, re.I)}


def main():
    data = json.load(open(os.path.join(HERE, 'clusters.json'), encoding='utf-8'))
    clustered = {p['url'].replace(SITE, '', 1) for c in data['clusters'] for p in c['pages']}
    pages = site_pages(sys.argv[1] if len(sys.argv) > 1 else None)
    ce = {p[len(CE):] for p in pages if p.startswith(CE)}
    findings = []

    # 1. Cluster pages that no longer exist on the site.
    gone = sorted(p for p in clustered if p not in pages)
    if gone:
        findings.append(('Pages in clusters.json that are no longer in the site sitemap (remove them)', gone))

    # 2. Local city guides whose English twin exists, where either isn't clustered yet.
    pairs = []
    for slug in sorted(ce):
        for prefix in LOCAL_PREFIXES:
            if slug.startswith(prefix):
                city = slug[len(prefix):]
                for twin in (f'christmas-in-{city}-with-kids', f'{city}-lu', f'{city}-qc', f'{city}-be', f'{city}-ch'):
                    if twin in ce and (CE + slug not in clustered or CE + twin not in clustered):
                        pairs.append(f'{CE}{twin}  <->  {CE}{slug}')
    if pairs:
        findings.append(('Possible city pairs not in clusters.json (check they are the same place)', pairs))

    # 3. English city guides with no partner at all may have a local version under another name.
    lonely = sorted(CE + s for s in ce if s.startswith('christmas-in-') and s.endswith('-with-kids') and CE + s not in clustered)
    if lonely:
        findings.append(('English city or country guides not in any cluster (add a pair if a local version exists)', lonely))

    # 4. Christmas Eve denomination pages that exist in 2+ countries but aren't clustered.
    eve = []
    dens = {p.rsplit('/', 1)[-1] for p in pages if re.match(r'^/(%s)/[a-z-]+-christmas-eve-services$' % '|'.join(EVE_SECTIONS), p)}
    for d in sorted(dens):
        members = [f'/{s}/{d}' for s in EVE_SECTIONS if f'/{s}/{d}' in pages]
        missing = [m for m in members if m not in clustered]
        if len(members) >= 2 and missing:
            eve.append(', '.join(missing))
    if eve:
        findings.append(('Christmas Eve denomination pages in 2+ countries not in clusters.json', eve))

    # 5. New country sections that look like an existing network.
    known = set(EVE_SECTIONS) | {'christmas-events', 'christmas-events-for-kids'}
    tops = {p.split('/')[1] for p in pages if p.count('/') >= 1 and p != '/'}
    new_secs = sorted(t for t in tops if (t.startswith('christmas-eve-services') or t.startswith('messes-de-noel') or t.startswith('christmas-events')) and t not in known and '/' + t not in clustered)
    if new_secs:
        findings.append(('New sections that may need hreflang clusters', ['/' + t for t in new_secs]))

    # Suggestions already reviewed and rejected live in tools/hreflang-ignore.txt.
    ignore_file = os.path.join(HERE, 'hreflang-ignore.txt')
    ignored = set()
    if os.path.exists(ignore_file):
        ignored = {l.split('#')[0].strip() for l in open(ignore_file, encoding='utf-8')} - {''}
    findings = [(t, [i for i in items if not any(x in ignored for x in re.findall(r'/[^\s`,]+', i))]) for t, items in findings]
    findings = [(t, items) for t, items in findings if items]

    if not findings:
        print('Nothing to add: every translated or country page found is in clusters.json.')
        return 0
    print('# hreflang pages to review\n')
    print(f'Checked {len(pages):,} pages against {len(clustered)} clustered pages.\n')
    for title, items in findings:
        print(f'## {title} ({len(items)})\n')
        for i in items[:300]:
            print(f'- `{i}`')
        if len(items) > 300:
            print(f'- ...and {len(items) - 300} more')
        print()
    print('To fix: edit tools/clusters.json, run `python3 tools/build_hreflang.py`, commit both files.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
