// hreflang Worker for www.rallytakesthetrain.com
//
// What it does, all driven by tools/clusters.json in this repo:
//   1. Pages in a cluster get <link rel="alternate" hreflang> tags for every page
//      in their cluster (plus x-default) and the right <html lang>.
//   2. /hreflang-sitemap.xml is served from the main domain, built from the same data.
//   3. /robots.txt gets a Sitemap line for it.
// Every other request passes straight through to Squarespace untouched.
// If anything goes wrong, the original Squarespace response is returned (fail open).
//
// The cluster data is read from GitHub (cached for a few minutes) so a commit to
// clusters.json goes live without redeploying. A copy bundled at deploy time is the
// fallback if GitHub can't be reached.

import bundled from '../../tools/clusters.json';

const DATA_URL = 'https://raw.githubusercontent.com/stridematt/sitemaps/main/tools/clusters.json';
const DATA_TTL_MS = 5 * 60 * 1000;
const SITEMAP_PATH = '/hreflang-sitemap.xml';

let cache = { at: 0, index: null };

function escapeXml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function pathOf(url) {
  let p = new URL(url).pathname;
  if (p.length > 1 && p.endsWith('/')) p = p.slice(0, -1);
  return p;
}

// Turn clusters.json into a lookup: path -> { lang, links }
export function buildIndex(data) {
  const byPath = new Map();
  for (const c of data.clusters) {
    const alts = [];
    for (const p of c.pages) for (const code of p.hreflang) alts.push([code, p.url]);
    alts.push(['x-default', c.x_default]);
    const links = alts
      .map(([code, url]) => `<link rel="alternate" hreflang="${code}" href="${escapeXml(url)}">`)
      .join('');
    for (const p of c.pages) {
      // html lang: the most specific code (de-DE over de)
      const lang = p.hreflang.find((h) => h.includes('-')) || p.hreflang[0];
      byPath.set(pathOf(p.url), { lang, links });
    }
  }
  return { data, byPath };
}

async function getIndex(ctx) {
  const now = Date.now();
  if (cache.index && now - cache.at < DATA_TTL_MS) return cache.index;
  try {
    const r = await fetch(DATA_URL, { cf: { cacheTtl: 300, cacheEverything: true } });
    if (!r.ok) throw new Error('status ' + r.status);
    const data = await r.json();
    if (!Array.isArray(data.clusters) || data.clusters.length === 0) throw new Error('empty');
    cache = { at: now, index: buildIndex(data) };
  } catch (e) {
    // Keep serving whatever we had; fall back to the bundled copy on a cold start.
    if (!cache.index) cache = { at: now, index: buildIndex(bundled) };
    else cache.at = now;
  }
  return cache.index;
}

export function buildSitemap(data) {
  const out = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
  ];
  for (const c of data.clusters) {
    const alts = [];
    for (const p of c.pages) for (const code of p.hreflang) alts.push([code, p.url]);
    alts.push(['x-default', c.x_default]);
    for (const p of c.pages) {
      out.push('  <url>', `    <loc>${escapeXml(p.url)}</loc>`);
      for (const [code, url] of alts) {
        out.push(`    <xhtml:link rel="alternate" hreflang="${code}" href="${escapeXml(url)}"/>`);
      }
      out.push('  </url>');
    }
  }
  out.push('</urlset>');
  return out.join('\n') + '\n';
}

function withHeader(resp, value) {
  const r = new Response(resp.body, resp);
  r.headers.delete('content-length');
  r.headers.set('x-rtt-hreflang', value);
  return r;
}

async function handle(request, ctx) {
  const url = new URL(request.url);
  const path = url.pathname;

  if (path === SITEMAP_PATH && (request.method === 'GET' || request.method === 'HEAD')) {
    const { data } = await getIndex(ctx);
    return new Response(request.method === 'HEAD' ? null : buildSitemap(data), {
      headers: {
        'content-type': 'application/xml; charset=utf-8',
        'cache-control': 'public, max-age=3600',
        'x-rtt-hreflang': 'sitemap',
      },
    });
  }

  const origin = await fetch(request);

  if (path === '/robots.txt' && request.method === 'GET' && origin.ok) {
    const text = await origin.text();
    const line = `Sitemap: ${url.origin}${SITEMAP_PATH}`;
    const body = text.includes(line) ? text : text.replace(/\s*$/, '\n') + line + '\n';
    const r = new Response(body, origin);
    r.headers.delete('content-length');
    r.headers.set('x-rtt-hreflang', 'robots');
    return r;
  }

  if (request.method !== 'GET' || origin.status !== 200) return origin;
  const type = origin.headers.get('content-type') || '';
  if (!type.includes('text/html')) return origin;

  const { byPath } = await getIndex(ctx);
  const entry = byPath.get(path.length > 1 && path.endsWith('/') ? path.slice(0, -1) : path);
  if (!entry) return origin;

  const rewritten = new HTMLRewriter()
    .on('html', {
      element(el) {
        el.setAttribute('lang', entry.lang);
      },
    })
    // Remove any hreflang link tags already in the head so there is only one set.
    .on('head link[hreflang]', {
      element(el) {
        el.remove();
      },
    })
    .on('head', {
      element(el) {
        el.append(entry.links, { html: true });
      },
    })
    .transform(origin);
  return withHeader(rewritten, 'tagged');
}

export default {
  async fetch(request, env, ctx) {
    try {
      return await handle(request, ctx);
    } catch (e) {
      // Fail open: never break the site.
      return fetch(request);
    }
  },
};
