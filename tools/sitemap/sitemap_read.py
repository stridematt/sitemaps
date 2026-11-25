"""Read the site's sitemap whether it is one file or an index.

Past 50,000 URLs Squarespace serves /sitemap.xml as an index of sitemap0.xml, sitemap1.xml, ...
(by relative name), and the rtt-hreflang Worker adds sitemap-new-pages.xml to it. Scripts that
pull URLs from the sitemap call expand() on what they fetched: an index comes back as the text
of every file in it, joined; anything else comes back unchanged.

    import sys; sys.path.insert(0, os.path.join(ROOT, 'tools', 'sitemap'))
    import sitemap_read as SR
    sm = SR.expand(sm, SITE + '/sitemap.xml', lambda u: fetch(u))

fetch(url) returns the file's text or bytes, or raises. Only sitemap files on the same host as
the index are read. A file that can't be read raises: half a sitemap would look like thousands
of pages gone.
"""
import html
import re
import urllib.parse

FILE = re.compile(r'/sitemap[\w-]*\.xml')
LOC = re.compile(r'<loc>\s*([^<\s]+)\s*</loc>')


def files(index_xml, base):
    """Full URLs of the sitemap files an index lists, on base's host, in order."""
    b = urllib.parse.urlsplit(base)
    out = []
    for loc in LOC.findall(index_xml):
        path = urllib.parse.urlsplit(urllib.parse.urljoin(base, html.unescape(loc))).path
        u = f'{b.scheme}://{b.netloc}{path}'
        if FILE.fullmatch(path) and u not in out:
            out.append(u)
    return out


def expand(xml, base, fetch, skip=()):
    """xml: what base returned (str or bytes). Returns the same type."""
    as_bytes = isinstance(xml, (bytes, bytearray))
    text = xml.decode('utf-8', 'replace') if as_bytes else xml
    if '<sitemapindex' not in text:
        return xml
    parts = []
    for u in files(text, base):
        if urllib.parse.urlsplit(u).path in skip:
            continue
        part = fetch(u)
        if part is None:
            raise RuntimeError(f'sitemap: could not read {u}')
        parts.append(part.decode('utf-8', 'replace') if isinstance(part, (bytes, bytearray)) else part)
    if not parts:
        raise RuntimeError('sitemap: the index lists no files')
    joined = '\n'.join(parts)
    return joined.encode('utf-8') if as_bytes else joined
