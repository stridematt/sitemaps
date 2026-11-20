// Runs the bundled Worker in Miniflare with Squarespace and GitHub mocked.
// Usage: npm run bundle && npm test   (page fixtures: FIXTURES=/path/to/saved/html)
import { Miniflare } from 'miniflare';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const ROOT = new URL('../../', import.meta.url).pathname;
const FIX = process.env.FIXTURES || '/home/claude/audit';
const SITE = 'https://www.rallytakesthetrain.com';
const clustersText = readFileSync(ROOT + 'tools/clusters.json', 'utf8');

const DYN = '/home/claude/dyn/';
const pages = {
  '/christmas-events-for-kids': 'christmas-events-for-kids.html',
  '/christmas-events/denver-co': DYN + 'christmas-events_denver-co.html',
  '/christmas-events/colorado': DYN + 'christmas-events_colorado.html',
  '/christmas-events/weihnachten-mit-kindern-deutschland': 'christmas-events_weihnachten-mit-kindern-deutschland.html',
  '/christmas-eve-services-near-me': 'christmas-eve-services-near-me.html',
  '/christmas-eve-services/united-states': 'us.html',
};
let githubUp = true;
let liveUp = true;
const liveText = readFileSync(ROOT + 'tools/truth/live.json', 'utf8');
let llmsGithub = true;
let llmsPages = true;
const llmsBody = 'x'.repeat(20000);
const seen = []; // URLs the Worker requested from Squarespace
let pagesUp = true;
let robots = 'User-agent: *\nDisallow: /config\n\nSitemap: https://www.rallytakesthetrain.com/sitemap.xml\n';

async function outbound(req) {
  const u = new URL(req.url);
  if (u.hostname === 'www.rallytakesthetrain.com') seen.push(req.url);
  if (/\/llms(-full)?\.txt$/.test(u.pathname) && u.hostname !== 'www.rallytakesthetrain.com') {
    const up = u.hostname === 'raw.githubusercontent.com' ? llmsGithub : llmsPages;
    if (up === 'bad') return new Response('<html>rate limited</html>', { headers: { 'content-type': 'text/html' } });
    return up ? new Response('# Rally Takes the Train\n' + (u.hostname === 'raw.githubusercontent.com' ? 'GH ' : 'PAGES ') + u.pathname + '\n' + llmsBody, { headers: { 'content-type': 'text/plain' } }) : new Response('down', { status: 503 });
  }
  if (u.pathname.endsWith('/tools/truth/live.json')) return liveUp ? new Response(liveText, { headers: { 'content-type': 'text/plain' } }) : new Response('down', { status: 503 });
  if (u.pathname === '/llms.txt') return new Response('squarespace llms', { headers: { 'content-type': 'text/plain' } });
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
  if (pages[key]) return new Response(readFileSync(pages[key].startsWith('/') ? pages[key] : FIX + '/' + pages[key]), { headers: { 'content-type': 'text/html; charset=utf-8' } });
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

const inlineScripts = (html) => [...html.matchAll(/<script(?![^>]*\ssrc=)([^>]*)>([\s\S]*?)<\/script>/g)].map((m) => [m[1], m[2]]);

await t('page not in any cluster passes through byte for byte, no header', async () => {
  const r = await get('/christmas-eve-services/united-states');
  assert.equal(r.headers.get('x-rtt-hreflang'), null);
  assert.equal(Buffer.compare(Buffer.from(await r.arrayBuffer()), readFileSync(FIX + '/us.html')), 0);
});

await t('tagged pages: every inline script still compiles; only the planned lines differ', async () => {
  const HUBFIX = [["cities: a[5], live: a[6], regs: [], list: []}", "cities: a[5], live: a[6], events: a[7] || 0, regs: [], list: []}"],
    ["plural(n, 'city', 'cities'), 'xn-cta--place');", "(x.events > 0 ? plural(x.events, 'event', 'events') : plural(n, 'city', 'cities')), 'xn-cta--place');"],
    ["fillStyle = dim ? 'rgba(214,226,246,.14)' : 'rgba(214,226,246,.55)'", "fillStyle = dim ? 'rgba(170,176,186,.16)' : 'rgba(170,176,186,.62)'"]];
  // the results line the finder writes on load uses the live totals
  const sh = /setHead\('Christmas around the world', [^;]*?\);/;
  for (const [path, file] of Object.entries(pages)) {
    const r = await get(path);
    const out = await r.text();
    const before = inlineScripts(readFileSync(file.startsWith('/') ? file : FIX + '/' + file, 'utf8'));
    const after = inlineScripts(out);
    assert.equal(after.length, before.length, path);
    let changed = 0;
    after.forEach(([attrs, code], i) => {
      if (/json/i.test(attrs)) { if (code.trim()) JSON.parse(code); return; } // data blocks may be healed; they must still parse
      if (code !== before[i][1]) {
        changed++;
        let want = before[i][1].replace("l.rel='alternate'", "l.rel='x-rtt-hreflang-off'");
        if (code !== want) for (const [a, b] of HUBFIX) want = want.replace(a, b);
        if (code !== want && sh.test(code)) want = want.replace(sh, code.match(sh)[0]);
        if (code !== want) want = want.replace("l.rel='x-rtt-hreflang-off'", "l.rel='alternate'");
        assert.equal(code, want, path);
      }
      new vm.Script(code); // throws on a syntax error
    });
    assert.ok(changed <= (r.headers.get('x-rtt-hreflang') === 'tagged' ? 2 : 1), path + ' changed ' + changed);
  }
});

await t('HEAD on a clustered page passes through', async () => {
  const r = await get('/christmas-events-for-kids', { method: 'HEAD' });
  assert.equal(r.headers.get('x-rtt-hreflang'), null);
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

await t('robots.txt passes through untouched (it has its own route to rally-indexnow)', async () => {
  const r = await get('/robots.txt');
  assert.equal(await r.text(), robots);
  assert.equal(r.headers.get('x-rtt-hreflang'), null);
});

await t('sitemap is built once and reused', async () => {
  const a = await (await get('/hreflang-sitemap.xml')).text();
  const b = await (await get('/hreflang-sitemap.xml')).text();
  assert.equal(a, b);
});

await t('images, POSTs and 404s pass through', async () => {
  const img = await get('/logo.png');
  assert.equal(img.headers.get('content-type'), 'image/png');
  assert.equal(await img.text(), 'PNG');
  assert.equal(img.headers.get('x-rtt-hreflang'), null);
  const post = await get('/form', { method: 'POST', body: 'a=1' });
  assert.equal(await post.text(), 'posted a=1');
  assert.equal(post.headers.get('x-rtt-hreflang'), null);
  const nf = await get('/nope');
  assert.equal(nf.status, 404);
  assert.equal(nf.headers.get('x-rtt-hreflang'), null);
});

await t('cache rules: who is cached and who bypasses', async () => {
  const { cachePlan } = await import(new URL('../src/index.js', import.meta.url));
  const R = (url, init = {}) => new Request(url, init);
  const P = SITE + '/christmas-events/houston-tx';
  assert.deepEqual(cachePlan(R(P)), { url: P });
  assert.deepEqual(cachePlan(R(P + '?utm_source=fb&utm_medium=cpc&fbclid=abc')), { url: P });
  assert.deepEqual(cachePlan(R(P + '?offset=12&utm_campaign=x')), { url: P + '?offset=12' });
  assert.deepEqual(cachePlan(R(P, { headers: { cookie: 'crumb=abc; ss_cvr=1; _ga=GA1.1; _fbp=x' } })), { url: P });
  for (const c of ['SiteUserInfo=x', 'SiteUserSecureAuthToken=y', 'a=1; hasCart=true', 'Locked=1', '_acloggedin=1', 'siteUserCrumb=z']) {
    assert.equal(cachePlan(R(P, { headers: { cookie: c } })), null, c);
  }
  for (const q of ['?format=json', '?nochrome=true', '?password=1', '?preview=1']) assert.equal(cachePlan(R(P + q)), null, q);
  assert.equal(cachePlan(R(P, { method: 'POST', body: 'x' })), null);
  assert.equal(cachePlan(R(P, { headers: { authorization: 'Basic x' } })), null);
});

await t('tracking parameters are stripped before Squarespace; signed-in visitors keep the full URL', async () => {
  seen.length = 0;
  await (await get('/christmas-eve-services/united-states?utm_source=news&gclid=1')).arrayBuffer();
  assert.equal(seen.at(-1), SITE + '/christmas-eve-services/united-states');
  await (await get('/christmas-eve-services/united-states?utm_source=news', { headers: { cookie: 'SiteUserInfo=me' } })).arrayBuffer();
  assert.equal(seen.at(-1), SITE + '/christmas-eve-services/united-states?utm_source=news');
});

await t('HTML responses tell browsers to recheck (no-cache); files are left alone', async () => {
  const a = await get('/christmas-eve-services/united-states');
  assert.equal(a.headers.get('cache-control'), 'no-cache');
  await a.arrayBuffer();
  const b = await get('/christmas-events-for-kids');
  assert.equal(b.headers.get('cache-control'), 'no-cache');
  await b.arrayBuffer();
  const img = await get('/logo.png');
  assert.equal(img.headers.get('cache-control'), null);
  await img.arrayBuffer();
});

await t('llms.txt and llms-full.txt are served from GitHub as plain text', async () => {
  const r = await get('/llms.txt');
  const b = await r.text();
  assert.equal(r.status, 200);
  assert.equal(r.headers.get('content-type'), 'text/plain; charset=utf-8');
  assert.equal(r.headers.get('x-rtt-llms'), 'github');
  assert.ok(b.startsWith('# Rally Takes the Train\nGH /stridematt/sitemaps/main/llms.txt'));
  const f = await (await get('/llms-full.txt')).text();
  assert.ok(f.includes('GH /stridematt/sitemaps/main/llms-full.txt'));
  const h = await get('/llms.txt', { method: 'HEAD' });
  assert.equal(h.status, 200);
  assert.equal((await h.text()).length, 0);
});

await t('llms.txt: a bad GitHub answer is skipped for the GitHub Pages copy', async () => {
  llmsGithub = 'bad';
  const r = await get('/llms.txt');
  assert.ok((await r.text()).includes('PAGES /llms.txt'));
  llmsGithub = true;
});

await t('llms.txt: both sources down, the last good copy is served', async () => {
  llmsGithub = false; llmsPages = false;
  const r = await get('/llms.txt');
  assert.equal(r.headers.get('x-rtt-llms'), 'saved');
  assert.ok((await r.text()).startsWith('# Rally Takes the Train'));
  llmsGithub = true; llmsPages = true;
});


await t('hub: counts healed from live.json, hreflang still tagged', async () => {
  const r = await get('/christmas-events-for-kids');
  const h = await r.text();
  assert.equal(r.headers.get('x-rtt-hreflang'), 'tagged');
  assert.ok(['healed', 'hit'].includes(r.headers.get('x-rtt-counts')), r.headers.get('x-rtt-counts'));
  const live = JSON.parse(liveText);
  assert.ok(h.includes(`<li><b>${live.total.events.toLocaleString('en-US')}</b>Christmas events</li>`));
  assert.match(h, /events: a\[7\] \|\| 0/);
  assert.equal(altCount(h), hubLinks);
  const r2 = await get('/christmas-events-for-kids');
  assert.equal(r2.headers.get('x-rtt-counts'), 'hit');
  await r2.arrayBuffer();
});

await t('city page with nothing stale is served as is; state guide is healed', async () => {
  const r = await get('/christmas-events/denver-co');
  const h = await r.text();
  assert.equal(h, readFileSync(DYN + 'christmas-events_denver-co.html', 'utf8'));
  const g = await get('/christmas-events/colorado');
  const gh = await g.text();
  assert.ok(['healed', 'hit'].includes(g.headers.get('x-rtt-counts')));
  assert.match(gh, /See all \d+ events in Denver/);
});

await t('signed-in visitors and unknown pages are never healed', async () => {
  const r = await get('/christmas-events-for-kids', { headers: { cookie: 'SiteUserInfo=me' } });
  assert.equal(r.headers.get('x-rtt-counts'), null);
  await r.arrayBuffer();
  const e = await get('/christmas-events/some-event-page-co');
  assert.equal(e.headers.get('x-rtt-counts'), null);
  await e.arrayBuffer();
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
