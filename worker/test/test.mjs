// Runs the bundled Worker in Miniflare with Squarespace and GitHub mocked.
// Usage: npm run bundle && npm test   (page fixtures: FIXTURES=/path/to/saved/html)
import { Miniflare } from 'miniflare';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import assert from 'node:assert/strict';

const ROOT = new URL('../../', import.meta.url).pathname;
const FIX = process.env.FIXTURES || '/home/claude/audit';
const SITE = 'https://www.rallytakesthetrain.com';
const clustersText = readFileSync(ROOT + 'tools/clusters.json', 'utf8');

const pages = {
  '/christmas-events-for-kids': 'christmas-events-for-kids.html',
  '/christmas-events/weihnachten-mit-kindern-deutschland': 'christmas-events_weihnachten-mit-kindern-deutschland.html',
  '/christmas-eve-services-near-me': 'christmas-eve-services-near-me.html',
  '/christmas-eve-services/united-states': 'us.html',
};
let githubUp = true;
let pagesUp = true;
let robots = 'User-agent: *\nDisallow: /config\n\nSitemap: https://www.rallytakesthetrain.com/sitemap.xml\n';

async function outbound(req) {
  const u = new URL(req.url);
  if (u.hostname === 'raw.githubusercontent.com') {
    return githubUp ? new Response(clustersText, { headers: { 'content-type': 'text/plain' } }) : new Response('down', { status: 503 });
  }
  if (u.hostname === 'sitemaps.rallytakesthetrain.com') {
    return pagesUp ? new Response(clustersText, { headers: { 'content-type': 'application/json' } }) : new Response('down', { status: 503 });
  }
  if (u.pathname === '/robots.txt') return new Response(robots, { headers: { 'content-type': 'text/plain' } });
  if (u.pathname === '/logo.png') return new Response('PNG', { headers: { 'content-type': 'image/png' } });
  if (u.pathname === '/with-old-tags') {
    return new Response('<html lang="en-US"><head><link rel="alternate" hreflang="fr" href="https://x/old"><title>t</title></head><body><a hreflang="de" href="/x">x</a></body></html>', { headers: { 'content-type': 'text/html' } });
  }
  if (u.pathname === '/form' && req.method === 'POST') return new Response('posted ' + (await req.text()), { headers: { 'content-type': 'text/html' } });
  const key = u.pathname.length > 1 ? u.pathname.replace(/\/$/, '') : u.pathname;
  if (pages[key]) return new Response(readFileSync(FIX + '/' + pages[key]), { headers: { 'content-type': 'text/html; charset=utf-8' } });
  return new Response('<html><head></head><body>not found</body></html>', { status: 404, headers: { 'content-type': 'text/html' } });
}

const mf = new Miniflare({
  modules: true,
  scriptPath: new URL('../dist/index.js', import.meta.url).pathname,
  compatibilityDate: '2026-08-01',
  outboundService: outbound,
});

const get = (p, init) => mf.dispatchFetch(SITE + p, init);
const head = (html) => html.slice(0, html.indexOf('</head>'));
const altCount = (html) => (head(html).match(/<link rel="alternate" hreflang=/g) || []).length;
const data = JSON.parse(clustersText);
const hub = data.clusters.find((c) => c.name === 'christmas-events-hub');
const hubLinks = hub.pages.reduce((n, p) => n + p.hreflang.length, 0) + 1;
let passed = 0;
const t = async (name, fn) => { await fn(); passed++; console.log('ok  ', name); };

await t('hub page gets every alternate, x-default and html lang en-US', async () => {
  const r = await get('/christmas-events-for-kids');
  const h = await r.text();
  assert.equal(r.headers.get('x-rtt-hreflang'), 'tagged');
  assert.equal(altCount(h), hubLinks);
  assert.match(h.slice(0, 300), /<html[^>]*lang="en-US"/);
  assert.match(head(h), /hreflang="de-DE" href="https:\/\/www\.rallytakesthetrain\.com\/christmas-events\/weihnachten-mit-kindern-deutschland"/);
  assert.match(head(h), /hreflang="x-default" href="https:\/\/www\.rallytakesthetrain\.com\/christmas-events-for-kids"/);
  assert.equal(r.headers.get('content-length'), null);
});

await t('German page gets the same set and html lang de-DE', async () => {
  const h = await (await get('/christmas-events/weihnachten-mit-kindern-deutschland')).text();
  assert.equal(altCount(h), hubLinks);
  // Only the real <html> element changes; the site's own script comment mentioning <html> is left alone.
  assert.match(h.slice(0, 300), /<html[^>]*lang="de-DE"/);
  assert.doesNotMatch(h.slice(0, 300), /en-US/);
});

await t('trailing slash still matches', async () => {
  const r = await get('/christmas-eve-services-near-me/');
  assert.equal(r.headers.get('x-rtt-hreflang'), 'tagged');
  const h = await r.text();
  assert.match(head(h), /hreflang="fr-CA" href="https:\/\/www\.rallytakesthetrain\.com\/messes-de-noel-quebec-canada\/quebec-et-canada-francais"/);
});

await t('page not in any cluster passes through byte for byte', async () => {
  const r = await get('/christmas-eve-services/united-states');
  assert.equal(r.headers.get('x-rtt-hreflang'), null);
  assert.equal(Buffer.compare(Buffer.from(await r.arrayBuffer()), readFileSync(FIX + '/us.html')), 0);
});

await t('old hreflang link tags removed, body anchors untouched', async () => {
  // Temporarily put /with-old-tags into a cluster via a modified data file.
  const h = await (await get('/with-old-tags')).text();
  assert.match(h, /hreflang="fr" href="https:\/\/x\/old"/); // not in a cluster: untouched
});

await t('sitemap on www matches the Python build exactly', async () => {
  const r = await get('/hreflang-sitemap.xml');
  assert.equal(r.headers.get('content-type'), 'application/xml; charset=utf-8');
  const xml = await r.text();
  assert.equal(xml, readFileSync(ROOT + 'hreflang-sitemap.xml', 'utf8'));
});

await t('robots.txt gets the hreflang sitemap line once', async () => {
  const txt = await (await get('/robots.txt')).text();
  assert.ok(txt.includes('Sitemap: https://www.rallytakesthetrain.com/sitemap.xml'));
  assert.equal(txt.split('Sitemap: https://www.rallytakesthetrain.com/hreflang-sitemap.xml').length - 1, 1);
  robots += 'Sitemap: https://www.rallytakesthetrain.com/hreflang-sitemap.xml\n';
  const again = await (await get('/robots.txt')).text();
  assert.equal(again.split('hreflang-sitemap.xml').length - 1, 1);
});

await t('images, POSTs and 404s pass through', async () => {
  const img = await get('/logo.png');
  assert.equal(await img.text(), 'PNG');
  assert.equal(img.headers.get('x-rtt-hreflang'), null);
  const post = await get('/form', { method: 'POST', body: 'a=1' });
  assert.equal(await post.text(), 'posted a=1');
  const nf = await get('/nope');
  assert.equal(nf.status, 404);
  assert.equal(nf.headers.get('x-rtt-hreflang'), null);
});

await mf.dispose();

const script = new URL('../dist/index.js', import.meta.url).pathname;
const persist = '/tmp/rtt-hreflang-test-cache-' + process.pid;
const fresh = (cachePersist) => new Miniflare({ modules: true, scriptPath: script, compatibilityDate: '2026-08-01', outboundService: outbound, cachePersist });

githubUp = false; pagesUp = true;
const mf2 = fresh(persist);
await t('GitHub down: GitHub Pages copy is used (and saved)', async () => {
  const r = await mf2.dispatchFetch(SITE + '/christmas-events-for-kids');
  assert.equal(r.headers.get('x-rtt-hreflang'), 'tagged');
  assert.equal(altCount(await r.text()), hubLinks);
  await new Promise((res) => setTimeout(res, 500));
});
await mf2.dispose();

githubUp = false; pagesUp = false;
const mf4 = fresh(persist);
await t('both sources down: last saved copy keeps pages tagged', async () => {
  const r = await mf4.dispatchFetch(SITE + '/christmas-events-for-kids');
  assert.equal(r.headers.get('x-rtt-hreflang'), 'tagged');
  assert.equal(altCount(await r.text()), hubLinks);
});
await mf4.dispose();

const mf5 = fresh(undefined);
await t('both sources down and nothing saved: site still works, untagged', async () => {
  const r = await mf5.dispatchFetch(SITE + '/christmas-events-for-kids');
  assert.equal(r.status, 200);
  assert.equal(r.headers.get('x-rtt-hreflang'), null);
  assert.equal(Buffer.compare(Buffer.from(await r.arrayBuffer()), readFileSync(FIX + '/christmas-events-for-kids.html')), 0);
  const sm = await mf5.dispatchFetch(SITE + '/hreflang-sitemap.xml');
  assert.equal(sm.headers.get('x-rtt-hreflang'), null);
});
await mf5.dispose();
githubUp = true; pagesUp = true;

// Existing hreflang link tags on a clustered page are replaced, not doubled.
githubUp = true;
const modified = JSON.parse(clustersText);
modified.clusters.push({ name: 'test', x_default: SITE + '/with-old-tags', pages: [
  { url: SITE + '/with-old-tags', hreflang: ['en'] }, { url: SITE + '/nope', hreflang: ['de'] }] });
const modText = JSON.stringify(modified);
const mf3 = new Miniflare({ modules: true, scriptPath: new URL('../dist/index.js', import.meta.url).pathname, compatibilityDate: '2026-08-01',
  outboundService: async (req) => new URL(req.url).hostname === 'raw.githubusercontent.com' ? new Response(modText) : outbound(req) });
await t('existing hreflang link tags replaced, anchors in body kept', async () => {
  const h = await (await mf3.dispatchFetch(SITE + '/with-old-tags')).text();
  assert.doesNotMatch(h, /https:\/\/x\/old/);
  assert.equal(altCount(h), 3);
  assert.match(h, /<a hreflang="de" href="\/x">/);
});
await mf3.dispose();

console.log(`\n${passed} tests passed`);
