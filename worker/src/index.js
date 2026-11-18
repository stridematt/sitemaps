// hreflang Worker for www.rallytakesthetrain.com
//
// Driven by tools/clusters.json in the stridematt/sitemaps repo:
//   1. Pages in a cluster get <link rel="alternate" hreflang> tags for every page in
//      their cluster (plus x-default) and the right <html lang>. The site-wide
//      Squarespace script that used to add older hreflang tags in the browser has that
//      one part switched off on these pages (its links get a harmless rel), so Google
//      sees a single set.
//   2. /hreflang-sitemap.xml is served from the main domain, built from the same data.
// Every other request is handed straight to Squarespace with no processing.
// If anything fails, the original Squarespace response is returned (fail open).
//
// Cost notes:
// - Routes only cover the international sections (see wrangler.toml), so favicon,
//   /s/ files, /api/ beacons, blog, shop etc. never start this Worker.
// - Pages not in a cluster are passed through without reading or rewriting the body.
// - Cluster data stays in memory per isolate and refreshes in the background every
//   5 minutes; requests never wait for a refresh after the first load. It is only
//   re-parsed when the file actually changed.

const SOURCES = [
  'https://raw.githubusercontent.com/stridematt/sitemaps/main/tools/clusters.json',
  'https://sitemaps.rallytakesthetrain.com/tools/clusters.json',
];
const SAVED_KEY = 'https://rtt-hreflang.internal/clusters.json';
const REFRESH_MS = 5 * 60 * 1000;
const SITEMAP_PATH = '/hreflang-sitemap.xml';

const state = { index: null, text: null, at: 0, refreshing: null };

function escapeXml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function normPath(p) {
  return p.length > 1 && p.endsWith('/') ? p.slice(0, -1) : p;
}

function valid(data) {
  return data && Array.isArray(data.clusters) && data.clusters.length > 0;
}

// clusters.json -> { data, byPath: Map(path -> { lang, links }), sitemap (built on first use) }
export function buildIndex(data) {
  const byPath = new Map();
  for (const c of data.clusters) {
    let links = '';
    for (const p of c.pages) {
      for (const code of p.hreflang) links += `<link rel="alternate" hreflang="${code}" href="${escapeXml(p.url)}">`;
    }
    links += `<link rel="alternate" hreflang="x-default" href="${escapeXml(c.x_default)}">`;
    for (const p of c.pages) {
      const lang = p.hreflang.find((h) => h.includes('-')) || p.hreflang[0];
      byPath.set(normPath(new URL(p.url).pathname), { lang, links });
    }
  }
  return { data, byPath, sitemap: null };
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

// Latest clusters.json text: GitHub, then the GitHub Pages copy, then the last good copy
// saved in Cloudflare's cache.
async function loadText() {
  for (const src of SOURCES) {
    try {
      const r = await fetch(src, { cf: { cacheTtl: 300, cacheEverything: true } });
      if (r.ok) return { text: await r.text(), fresh: true };
    } catch (e) {}
  }
  try {
    const r = await caches.default.match(SAVED_KEY);
    if (r) return { text: await r.text(), fresh: false };
  } catch (e) {}
  return null;
}

function refresh(ctx) {
  if (state.refreshing) return state.refreshing;
  state.refreshing = (async () => {
    try {
      const got = await loadText();
      if (got && got.text !== state.text) {
        const data = JSON.parse(got.text);
        if (valid(data)) {
          state.index = buildIndex(data);
          state.text = got.text;
          if (got.fresh) {
            const saved = new Response(got.text, { headers: { 'cache-control': 'public, max-age=2592000', 'content-type': 'application/json' } });
            ctx.waitUntil(caches.default.put(SAVED_KEY, saved).catch(() => {}));
          }
        }
      }
    } catch (e) {
      // keep the index we have
    } finally {
      state.at = Date.now();
      state.refreshing = null;
    }
  })();
  return state.refreshing;
}

async function getIndex(ctx) {
  if (!state.index) {
    await refresh(ctx);
  } else if (Date.now() - state.at > REFRESH_MS) {
    ctx.waitUntil(refresh(ctx)); // refresh in the background, answer with what we have
  }
  return state.index;
}

// Switch off client-side hreflang link creation in inline scripts.
const REL_PROP = /(\.rel\s*=\s*)(['"])alternate\2/g;
const REL_ATTR = /(setAttribute\(\s*(['"])rel\2\s*,\s*)(['"])alternate\3/g;
export function disableScriptHreflang(code) {
  if (!code.includes('hreflang')) return code;
  return code.replace(REL_PROP, '$1$2x-rtt-hreflang-off$2').replace(REL_ATTR, '$1$3x-rtt-hreflang-off$3');
}

function scriptCleaner() {
  let buf = null;
  return {
    element(el) {
      const type = (el.getAttribute('type') || '').toLowerCase();
      buf = el.getAttribute('src') || type.includes('json') ? null : '';
    },
    text(t) {
      if (buf === null) return;
      buf += t.text;
      if (t.lastInTextNode) {
        const out = disableScriptHreflang(buf);
        buf = null;
        t.replace(out, { html: true });
      } else {
        t.remove();
      }
    },
  };
}

function tag(origin, entry) {
  const out = new HTMLRewriter()
    .on('html', {
      element(el) {
        el.setAttribute('lang', entry.lang);
      },
    })
    .on('head script', scriptCleaner())
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
  const r = new Response(out.body, out);
  r.headers.delete('content-length');
  r.headers.set('x-rtt-hreflang', 'tagged');
  return r;
}

async function handle(request, ctx) {
  const method = request.method;
  if (method !== 'GET' && method !== 'HEAD') return fetch(request);
  const path = normPath(new URL(request.url).pathname);
  const index = await getIndex(ctx);
  if (!index) return fetch(request);

  if (path === SITEMAP_PATH) {
    if (!index.sitemap) index.sitemap = buildSitemap(index.data);
    return new Response(method === 'HEAD' ? null : index.sitemap, {
      headers: {
        'content-type': 'application/xml; charset=utf-8',
        'cache-control': 'public, max-age=3600',
        'x-rtt-hreflang': 'sitemap',
      },
    });
  }

  const entry = method === 'GET' ? index.byPath.get(path) : null;
  if (!entry) return fetch(request); // not a clustered page: straight through, body untouched

  const origin = await fetch(request);
  if (origin.status !== 200 || !(origin.headers.get('content-type') || '').includes('text/html')) return origin;
  return tag(origin, entry);
}

export default {
  async fetch(request, env, ctx) {
    try {
      return await handle(request, ctx);
    } catch (e) {
      return fetch(request); // fail open: never break the site
    }
  },
};
