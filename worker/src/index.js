// hreflang Worker for www.rallytakesthetrain.com
//
// Driven by tools/clusters.json in the stridematt/sitemaps repo:
//   1. Pages in a cluster get <link rel="alternate" hreflang> tags for every page in
//      their cluster (plus x-default) and the right <html lang>. The site-wide
//      Squarespace script that used to add older hreflang tags in the browser has that
//      one part switched off on these pages (its links get a harmless rel), so Google
//      sees a single set.
//   2. /hreflang-sitemap.xml is served from the main domain, built from the same data.
//   3. Edge cache: anonymous GET requests are cached at Cloudflare for 5 minutes
//      (Tiered Cache), so visitors and crawlers worldwide get pages from a nearby
//      data center instead of waiting on Squarespace. Signed-in or cart visitors,
//      Squarespace special URLs and errors are never cached.
//   4. /llms.txt and /llms-full.txt are served from the repo (rebuilt every 3 hours).
// Pages not in a cluster are handed to Squarespace (through the cache) unread.
// If anything fails, the original Squarespace response is returned (fail open).
//
// Cost notes:
// - Routes only cover the international sections (see wrangler.toml), so favicon,
//   /s/ files, /api/ beacons, blog, shop etc. never start this Worker.
// - Pages not in a cluster are passed through without reading or rewriting the body.
// - Cluster data stays in memory per isolate and refreshes in the background every
//   5 minutes; requests never wait for a refresh after the first load. It is only
//   re-parsed when the file actually changed.

import { healHub, healCity, healGuide, refToday } from './heal.js';
import { isServicesPath, servicesHealerFor, runServicesHealer } from './services.js';

const SOURCES = [
  'https://raw.githubusercontent.com/stridematt/sitemaps/main/tools/clusters.json',
  'https://sitemaps.rallytakesthetrain.com/tools/clusters.json',
];
const SAVED_KEY = 'https://rtt-hreflang.internal/clusters.json';
const REFRESH_MS = 5 * 60 * 1000;
const SITEMAP_PATH = '/hreflang-sitemap.xml';

const state = { index: null, text: null, at: 0, refreshing: null };

// ---- Edge cache ---------------------------------------------------------------
// Squarespace marks every page no-cache and sets a CSRF "crumb" cookie; the page HTML
// itself is the same for every anonymous visitor (no tokens in it), and Squarespace's
// own background calls (/api/census etc.) hand out the crumb, so caching is safe.
const EDGE_TTL = {
  '200-299': 300, // 5 minutes
  '300-399': 300, // redirects
  '404': 60,
  '400-403': -1, // never store
  '405-599': -1,
};
// Cookies that mean the visitor is signed in, has a cart, or passed a password page.
const BYPASS_COOKIES = /(?:^|;\s*)(?:SiteUserInfo|SiteUserSecureAuthToken|siteUserCrumb|_acloggedin|hasCart|Locked|SQ_LANGUAGE_SESSION)=/i;
// Squarespace special URLs that must always go to Squarespace.
const BYPASS_PARAMS = new Set(['format', 'nochrome', 'preview', 'password', 'ss_preview', 'author']);
// Ad and email tracking parameters: they don't change the page, so they shouldn't
// create separate cache copies. They stay in the visitor's address bar for analytics.
const TRACKING_PARAM = /^(?:utm_[a-z]+|fbclid|gclid|gbraid|wbraid|dclid|msclkid|ttclid|twclid|igshid|li_fat_id|mc_cid|mc_eid|_ga|_gl|srsltid)$/i;

// How to fetch this request from Squarespace: null = no caching, else the URL to use.
export function cachePlan(request) {
  if (request.method !== 'GET' && request.method !== 'HEAD') return null;
  if (request.headers.has('authorization')) return null;
  if (BYPASS_COOKIES.test(request.headers.get('cookie') || '')) return null;
  const url = new URL(request.url);
  for (const k of url.searchParams.keys()) if (BYPASS_PARAMS.has(k.toLowerCase())) return null;
  let changed = false;
  for (const k of [...url.searchParams.keys()]) {
    if (TRACKING_PARAM.test(k)) {
      url.searchParams.delete(k);
      changed = true;
    }
  }
  return { url: changed ? url.toString() : request.url };
}

function originFetch(request) {
  const plan = cachePlan(request);
  if (!plan) return fetch(request);
  const req = plan.url === request.url ? request : new Request(plan.url, request);
  return fetch(req, { cf: { cacheEverything: true, cacheTtlByStatus: EDGE_TTL } });
}

// Browsers keep checking back (same as Squarespace's own no-cache); the edge does the caching.
function forBrowser(resp) {
  const r = new Response(resp.body, resp);
  r.headers.set('cache-control', 'no-cache');
  return r;
}

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

// ---- Live counts (tools/truth/live.json, rebuilt every 3 hours) ------------------------
const LIVE_SOURCES = [
  'https://raw.githubusercontent.com/stridematt/sitemaps/main/tools/truth/live.json',
  'https://sitemaps.rallytakesthetrain.com/tools/truth/live.json',
];
const LIVE_SAVED = 'https://rtt-hreflang.internal/live.json';
const lstate = { data: null, text: null, at: 0, refreshing: null };

function refreshLive(ctx) {
  if (lstate.refreshing) return lstate.refreshing;
  lstate.refreshing = (async () => {
    try {
      let text = null, fresh = false;
      for (const src of LIVE_SOURCES) {
        try {
          const r = await fetch(src, { cf: { cacheTtl: 300, cacheEverything: true } });
          if (r.ok) { text = await r.text(); fresh = true; break; }
        } catch (e) {}
      }
      if (!text) {
        try { const r = await caches.default.match(LIVE_SAVED); if (r) text = await r.text(); } catch (e) {}
      }
      if (text && text !== lstate.text) {
        const d = JSON.parse(text);
        if (d && d.total && d.cities) {
          lstate.data = d;
          lstate.text = text;
          if (fresh) ctx.waitUntil(caches.default.put(LIVE_SAVED, new Response(text, { headers: { 'cache-control': 'public, max-age=2592000' } })).catch(() => {}));
        }
      }
    } catch (e) {
      // keep what we have
    } finally {
      lstate.at = Date.now();
      lstate.refreshing = null;
    }
  })();
  return lstate.refreshing;
}

async function getLive(ctx) {
  if (!lstate.data) await refreshLive(ctx);
  else if (Date.now() - lstate.at > REFRESH_MS) ctx.waitUntil(refreshLive(ctx));
  return lstate.data;
}

// ---- Christmas Eve services counts (tools/services/live_services.json, rebuilt hourly) ------
const SV_SOURCES = [
  'https://raw.githubusercontent.com/stridematt/sitemaps/main/tools/services/live_services.json',
  'https://sitemaps.rallytakesthetrain.com/tools/services/live_services.json',
];
const SV_SAVED = 'https://rtt-hreflang.internal/live_services.json';
const sstate = { data: null, text: null, at: 0, refreshing: null };

function refreshServices(ctx) {
  if (sstate.refreshing) return sstate.refreshing;
  sstate.refreshing = (async () => {
    try {
      let text = null, fresh = false;
      for (const src of SV_SOURCES) {
        try {
          const r = await fetch(src, { cf: { cacheTtl: 300, cacheEverything: true } });
          if (r.ok) { text = await r.text(); fresh = true; break; }
        } catch (e) {}
      }
      if (!text) {
        try { const r = await caches.default.match(SV_SAVED); if (r) text = await r.text(); } catch (e) {}
      }
      if (text && text !== sstate.text) {
        const d = JSON.parse(text);
        if (d && d.total && d.guides) {
          sstate.data = d;
          sstate.text = text;
          if (fresh) ctx.waitUntil(caches.default.put(SV_SAVED, new Response(text, { headers: { 'cache-control': 'public, max-age=2592000' } })).catch(() => {}));
        }
      }
    } catch (e) {
      // keep what we have
    } finally {
      sstate.at = Date.now();
      sstate.refreshing = null;
    }
  })();
  return sstate.refreshing;
}

async function getServices(ctx) {
  if (!sstate.data) await refreshServices(ctx);
  else if (Date.now() - sstate.at > REFRESH_MS) ctx.waitUntil(refreshServices(ctx));
  return sstate.data;
}

// Which healer a path gets, if any.
export function healerFor(path, live) {
  if (!live) return null;
  if (path === '/christmas-events-for-kids') return 'hub';
  if (!path.startsWith('/christmas-events/')) return null;
  if (live.guides && live.guides[path]) return 'guide';
  if (live.pages && live.pages[path]) return 'city';
  return null;
}

export function runHealer(kind, html, live, path, today) {
  if (kind === 'svhub' || kind === 'svguide') return runServicesHealer(kind, html, live, path);
  if (kind === 'hub') return healHub(html, live, { day: today });
  if (kind === 'guide') return healGuide(html, today, live, path);
  if (kind === 'city') return healCity(html, today, live.pages, path);
  return null;
}

// Healed pages are kept for an hour per data version, day and code build, so the work runs rarely
// and a new deploy never serves pages healed by older code. BUILD is filled in by scripts/oneline.mjs.
let BUILD = 'dev';   // replaced by the bundler, or by the deployed version's id at run time (wrangler deploys)
async function healed(request, path, kind, live, ctx) {
  const today = refToday();
  const key = `https://rtt-heal.internal${path}?d=${today}&v=${encodeURIComponent(live.generated || '')}&b=${BUILD}`;
  try {
    const hit = await caches.default.match(key);
    if (hit) return { html: await hit.text(), status: 'hit' };
  } catch (e) {}
  const origin = await originFetch(request);
  if (origin.status !== 200 || !(origin.headers.get('content-type') || '').includes('text/html')) return { resp: origin };
  const html = await origin.text();
  let out = null;
  try {
    out = runHealer(kind, html, live, path, today);
  } catch (e) {
    out = null;
  }
  const body = out || html;
  ctx.waitUntil(caches.default.put(key, new Response(body, { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'public, max-age=3600' } })).catch(() => {}));
  return { html: body, status: out ? 'healed' : 'clean', headers: origin.headers };
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
  r.headers.set('cache-control', 'no-cache');
  r.headers.set('x-rtt-hreflang', 'tagged');
  return r;
}

// ---- llms.txt -------------------------------------------------------------------
// Built from the live site every 3 hours by GitHub Actions (tools/llms/build_llms.py)
// and served here, so it has no size limit and never needs pasting into Squarespace.
// Order: GitHub, then the GitHub Pages copy, then the last good copy saved in
// Cloudflare's cache, then Squarespace's own llms.txt.
const LLMS = {
  '/llms.txt': [
    'https://raw.githubusercontent.com/stridematt/sitemaps/main/llms.txt',
    'https://sitemaps.rallytakesthetrain.com/llms.txt',
  ],
  '/llms-full.txt': [
    'https://raw.githubusercontent.com/stridematt/sitemaps/main/llms-full.txt',
    'https://sitemaps.rallytakesthetrain.com/llms-full.txt',
  ],
};
const LLMS_HEADERS = { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'public, max-age=300' };

export function looksLikeLlms(text) {
  return typeof text === 'string' && text.startsWith('# Rally Takes the Train') && text.length > 10000;
}

async function serveLlms(path, request, ctx) {
  const savedKey = 'https://rtt-hreflang.internal' + path;
  let text = null;
  let from = 'github';
  for (const src of LLMS[path]) {
    try {
      const r = await fetch(src, { cf: { cacheTtl: 300, cacheEverything: true } });
      if (!r.ok) continue;
      const t = await r.text();
      if (!looksLikeLlms(t)) continue;
      text = t;
      if (r.headers.get('cf-cache-status') !== 'HIT') {
        // A fresh copy: keep it as the last good one.
        const saved = new Response(t, { headers: { ...LLMS_HEADERS, 'cache-control': 'public, max-age=2592000' } });
        ctx.waitUntil(caches.default.put(savedKey, saved).catch(() => {}));
      }
      break;
    } catch (e) {}
  }
  if (!text) {
    try {
      const r = await caches.default.match(savedKey);
      if (r) {
        text = await r.text();
        from = 'saved';
      }
    } catch (e) {}
  }
  if (!text) return originFetch(request); // Squarespace's own copy
  return new Response(request.method === 'HEAD' ? null : text, { headers: { ...LLMS_HEADERS, 'x-rtt-llms': from } });
}

// ---- sitemap.xml ------------------------------------------------------------------
// Squarespace's sitemap lags behind new pages and keeps URLs that now 404 or redirect.
// tools/sitemap/build_fix.py (every 3 hours) lists what to add and remove; it is applied
// here as the sitemap is served. A request with x-rtt-raw gets Squarespace's own copy.
const SITEMAP_FIX = [
  'https://raw.githubusercontent.com/stridematt/sitemaps/main/tools/sitemap/fix.json',
  'https://sitemaps.rallytakesthetrain.com/tools/sitemap/fix.json',
];
const MAX_SITEMAP_URLS = 50000;

export function applySitemapFix(xml, fix) {
  if (!fix || !xml.includes('</urlset>')) return null;
  const drop = new Set(fix.remove || []);
  const seen = new Set();
  let removed = 0;
  let out = xml.replace(/[ \t]*<url>\s*<loc>https:\/\/www\.rallytakesthetrain\.com([^<]*)<\/loc>[\s\S]*?<\/url>\s*/g, (block, p) => {
    if (drop.has(p)) { removed++; return ''; }
    seen.add(p);
    return block;
  });
  const add = (fix.add || []).filter(([p]) => p && p.startsWith('/') && !seen.has(p));
  if (seen.size + add.length > MAX_SITEMAP_URLS) return null; // over the protocol limit: leave Squarespace's as is
  const NL = '\n'; // kept as an escape so the deploy bundle stays on one line
  const entries = add.map(([p, d]) =>
    '  <url>' + NL + '    <loc>https://www.rallytakesthetrain.com' + escapeXml(p) + '</loc>' + NL + '    <changefreq>weekly</changefreq>' + NL +
    '    <priority>0.75</priority>' + NL + (/^\d{4}-\d\d-\d\d$/.test(d || '') ? '    <lastmod>' + d + '</lastmod>' + NL : '') + '  </url>' + NL).join('');
  out = out.replace(/<\/urlset>\s*$/, entries + '</urlset>' + NL);
  return { xml: out, added: add.length, removed };
}

async function loadSitemapFix(ctx) {
  const saved = 'https://rtt-hreflang.internal/sitemap-fix.json';
  for (const src of SITEMAP_FIX) {
    try {
      const r = await fetch(src, { cf: { cacheTtl: 300, cacheEverything: true } });
      if (!r.ok) continue;
      const t = await r.text();
      const j = JSON.parse(t);
      if (!Array.isArray(j.add) || !Array.isArray(j.remove)) continue;
      ctx.waitUntil(caches.default.put(saved, new Response(t, { headers: { 'cache-control': 'public, max-age=2592000' } })).catch(() => {}));
      return j;
    } catch (e) {}
  }
  try {
    const r = await caches.default.match(saved);
    if (r) return JSON.parse(await r.text());
  } catch (e) {}
  return null;
}

async function serveSitemapXml(request, ctx) {
  if (request.headers.has('x-rtt-raw')) return fetch(request);
  const origin = await fetch(new Request(request.url, { method: 'GET', headers: request.headers }), { cf: { cacheTtl: 600, cacheEverything: true } });
  if (origin.status !== 200 || !(origin.headers.get('content-type') || '').includes('xml')) return origin;
  const fix = await loadSitemapFix(ctx);
  if (!fix) return forBrowser(origin);
  const tagv = origin.headers.get('etag') || origin.headers.get('last-modified') || origin.headers.get('content-length') || '';
  const key = `https://rtt-hreflang.internal/sitemap.xml?f=${encodeURIComponent(fix.generated || '')}&o=${encodeURIComponent(tagv)}&b=${BUILD}`;
  const headers = { 'content-type': 'application/xml; charset=utf-8', 'cache-control': 'no-cache' };
  try {
    const hit = await caches.default.match(key);
    if (hit) return new Response(request.method === 'HEAD' ? null : hit.body, { headers: { ...headers, 'x-rtt-sitemap': hit.headers.get('x-rtt-sitemap') || 'fixed' } });
  } catch (e) {}
  const res = applySitemapFix(await origin.text(), fix);
  if (!res) return fetch(request);
  const note = `fixed +${res.added} -${res.removed}`;
  ctx.waitUntil(caches.default.put(key, new Response(res.xml, { headers: { 'cache-control': 'public, max-age=600', 'x-rtt-sitemap': note } })).catch(() => {}));
  return new Response(request.method === 'HEAD' ? null : res.xml, { headers: { ...headers, 'x-rtt-sitemap': note } });
}

async function handle(request, ctx) {
  const method = request.method;
  if (method !== 'GET' && method !== 'HEAD') return fetch(request);
  const path = normPath(new URL(request.url).pathname);
  if (LLMS[path]) return serveLlms(path, request, ctx);
  if (path === '/sitemap.xml') return serveSitemapXml(request, ctx);
  const index = await getIndex(ctx);
  if (!index) return originFetch(request);

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

  // Self-healing counts (anonymous GET only; signed-in editors see Squarespace as stored).
  if (method === 'GET' && cachePlan(request)) {
    let live, kind;
    if (isServicesPath(path)) {
      live = await getServices(ctx);
      kind = servicesHealerFor(path, live);
    } else {
      live = await getLive(ctx);
      kind = healerFor(path, live);
    }
    if (kind) {
      const h = await healed(request, path, kind, live, ctx);
      if (h.resp) return forBrowser(h.resp);
      const resp = new Response(h.html, { status: 200, headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-cache', 'x-rtt-counts': h.status } });
      return entry ? tag(resp, entry) : resp;
    }
  }

  if (!entry) {
    // Not a clustered page: through the edge cache, body untouched.
    const resp = await originFetch(request);
    return (resp.headers.get('content-type') || '').includes('text/html') ? forBrowser(resp) : resp;
  }

  const origin = await originFetch(request);
  if (origin.status !== 200 || !(origin.headers.get('content-type') || '').includes('text/html')) return forBrowser(origin);
  return tag(origin, entry);
}

export default {
  async fetch(request, env, ctx) {
    try {
      const vm = env && env.CF_VERSION_METADATA;
      if (vm && vm.id && BUILD === 'dev') BUILD = String(vm.id).slice(0, 10);
      return await handle(request, ctx);
    } catch (e) {
      return fetch(request); // fail open: never break the site
    }
  },
};
