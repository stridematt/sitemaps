#!/usr/bin/env python3
"""Build hreflang-sitemap.xml from tools/clusters.json and check it.

A cluster is a set of pages that are the same guide for different languages or
countries. Every page in a cluster lists every other page in it (plus itself and
the x-default), so Google gets matching return links from every page.

Usage:
    python3 tools/build_hreflang.py            # check clusters.json, write hreflang-sitemap.xml
    python3 tools/build_hreflang.py --check    # check only, write nothing

To add pages: add a cluster (or a page to a cluster) in tools/clusters.json, run
this script, commit both files.
"""
import json
import os
import re
import sys
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, 'clusters.json')
OUT = os.path.join(ROOT, 'hreflang-sitemap.xml')

# ISO 639-1 language codes Google accepts, and ISO 3166-1 alpha-2 regions.
LANGS = set('aa ab af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu'.split())
REGIONS = set('AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW'.split())


def valid_code(code):
    if code == 'x-default':
        return True
    m = re.fullmatch(r'([a-z]{2})(?:-([A-Z]{2}))?', code)
    return bool(m) and m.group(1) in LANGS and (m.group(2) is None or m.group(2) in REGIONS)


def check(data):
    errors = []
    site = data['site'].rstrip('/')
    seen = {}
    for c in data['clusters']:
        name = c['name']
        urls = [p['url'] for p in c['pages']]
        if len(urls) < 2:
            errors.append(f'{name}: needs at least 2 pages')
        if c.get('x_default') not in urls:
            errors.append(f'{name}: x_default must be one of its pages')
        codes = {}
        for p in c['pages']:
            u = p['url']
            if not u.startswith(site + '/') and u != site:
                errors.append(f'{name}: {u} is not on {site}')
            if u != u.strip() or '?' in u or '#' in u:
                errors.append(f'{name}: {u} looks malformed')
            if u in seen:
                errors.append(f'{u} is in two clusters ({seen[u]} and {name}); a page can only be in one')
            seen[u] = name
            if not p['hreflang']:
                errors.append(f'{name}: {u} has no hreflang code')
            for code in p['hreflang']:
                if code == 'x-default':
                    errors.append(f'{name}: use x_default, not an x-default code on a page')
                elif not valid_code(code):
                    errors.append(f'{name}: {code} on {u} is not a valid hreflang code')
                if code in codes:
                    errors.append(f'{name}: {code} is used for both {codes[code]} and {u}')
                codes[code] = u
    return errors


def build(data):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for c in data['clusters']:
        alts = [(code, p['url']) for p in c['pages'] for code in p['hreflang']]
        alts.append(('x-default', c['x_default']))
        for p in c['pages']:
            lines.append('  <url>')
            lines.append(f'    <loc>{escape(p["url"])}</loc>')
            for code, url in alts:
                lines.append(f'    <xhtml:link rel="alternate" hreflang="{code}" href="{escape(url)}"/>')
            lines.append('  </url>')
    lines.append('</urlset>')
    return '\n'.join(lines) + '\n'


def main():
    data = json.load(open(SRC, encoding='utf-8'))
    errors = check(data)
    pages = sum(len(c['pages']) for c in data['clusters'])
    if errors:
        print(f'{len(errors)} problem(s) in clusters.json:')
        for e in errors:
            print('  -', e)
        sys.exit(1)
    print(f'OK: {len(data["clusters"])} clusters, {pages} pages')
    if '--check' not in sys.argv:
        xml = build(data)
        open(OUT, 'w', encoding='utf-8').write(xml)
        print(f'wrote {OUT} ({len(xml.encode()):,} bytes)')


if __name__ == '__main__':
    main()
