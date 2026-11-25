// Tests for the sitemap.xml fix. Run: node test/sitemap.test.mjs
import { applySitemapFix, fixSitemapIndex, newPagesSitemap, isSitemapPath } from '../src/index.js';
const NEW_PAGES_SITEMAP = '/sitemap-new-pages.xml';
import assert from 'node:assert/strict';
let n = 0;
const t = (name, fn) => { fn(); n++; console.log('ok  ', name); };
const url = (p, d) => `  <url>\n    <loc>https://www.rallytakesthetrain.com${p}</loc>\n    <changefreq>monthly</changefreq>\n    <priority>0.5</priority>\n    <lastmod>${d}</lastmod>\n  </url>\n`;
const xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
  url('/blog', '2026-11-10') + url('/christmas-events/white-kitte-tokyo-jp', '2026-11-01') + url('/christmas-events/denver-co', '2026-11-16') + '</urlset>\n';

t('404 URLs come out, missing pages go in, everything else is untouched', () => {
  const r = applySitemapFix(xml, { remove: ['/christmas-events/white-kitte-tokyo-jp'], add: [['/christmas-events/kerst-met-kinderen-delft', '2026-11-18'], ['/blog', '2026-11-18']] });
  assert.equal(r.removed, 1);
  assert.equal(r.added, 1, 'a page already listed is not added twice');
  assert.ok(!r.xml.includes('white-kitte'));
  assert.ok(r.xml.includes(url('/blog', '2026-11-10')) && r.xml.includes(url('/christmas-events/denver-co', '2026-11-16')));
  assert.ok(r.xml.includes('<loc>https://www.rallytakesthetrain.com/christmas-events/kerst-met-kinderen-delft</loc>'));
  assert.ok(r.xml.includes('<lastmod>2026-11-18</lastmod>'));
  assert.ok(r.xml.trimEnd().endsWith('</urlset>'));
  assert.equal((r.xml.match(/<url>/g) || []).length, 3);
});

t('characters that need escaping are escaped', () => {
  const r = applySitemapFix(xml, { remove: [], add: [['/a&b', '2026-11-18']] });
  assert.ok(r.xml.includes('/a&amp;b</loc>'));
});

t('no fix data or a broken sitemap means Squarespace is served as is', () => {
  assert.equal(applySitemapFix(xml, null), null);
  assert.equal(applySitemapFix('<html>oops</html>', { add: [], remove: [] }), null);
});

// Squarespace's index once the site passed 50,000 URLs (2026-11-25), files listed by relative name.
const index = '<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
  '  <sitemap>\n    <loc>sitemap0.xml</loc>\n    <lastmod>2026-11-25</lastmod>\n  </sitemap>\n' +
  '  <sitemap>\n    <loc>sitemap1.xml</loc>\n    <lastmod>2026-11-25</lastmod>\n  </sitemap>\n</sitemapindex>\n';

t('the index lists every file as a full URL, plus the new-pages file', () => {
  const r = fixSitemapIndex(index, { remove: [], add: [['/a', '2026-11-20'], ['/b', '2026-11-23'], ['/a', '2026-11-20']] });
  assert.equal(r.files, 2);
  assert.ok(r.xml.includes('<loc>https://www.rallytakesthetrain.com/sitemap0.xml</loc>'));
  assert.ok(r.xml.includes('<loc>https://www.rallytakesthetrain.com/sitemap1.xml</loc>'));
  assert.ok(!/<loc>sitemap/.test(r.xml), 'no relative file names left');
  assert.ok(r.xml.includes('<loc>https://www.rallytakesthetrain.com' + NEW_PAGES_SITEMAP + '</loc>\n    <lastmod>2026-11-23</lastmod>'));
  assert.equal((r.xml.match(/<sitemap>/g) || []).length, 3);
  assert.ok(r.xml.trimEnd().endsWith('</sitemapindex>'));
});

t('the index without fix data or additions still gets full URLs, and no new-pages file', () => {
  for (const fix of [null, { add: [], remove: [] }]) {
    const r = fixSitemapIndex(index, fix);
    assert.ok(r.xml.includes('<loc>https://www.rallytakesthetrain.com/sitemap1.xml</loc>'));
    assert.ok(!r.xml.includes(NEW_PAGES_SITEMAP));
  }
  const abs = fixSitemapIndex(index.replace('sitemap0.xml', 'http://rallytakesthetrain.com/sitemap0.xml'), null);
  assert.ok(abs.xml.includes('<loc>https://www.rallytakesthetrain.com/sitemap0.xml</loc>'), 'full URLs are normalised to https://www');
  assert.equal(fixSitemapIndex(xml, null), null, 'a plain urlset is not an index');
});

t('a split file loses dead URLs and takes no additions', () => {
  const r = applySitemapFix(xml, { remove: ['/christmas-events/white-kitte-tokyo-jp'], add: [] });
  assert.equal(r.removed, 1);
  assert.equal(r.added, 0);
  assert.equal((r.xml.match(/<url>/g) || []).length, 2);
});

t('the new-pages file is a valid urlset of the additions, empty when there are none', () => {
  const r = newPagesSitemap({ add: [['/x', '2026-11-22'], ['/x', '2026-11-22'], ['nope', '2026-11-22']], remove: [] });
  assert.equal(r.added, 1);
  assert.ok(r.xml.startsWith('<?xml') && r.xml.trimEnd().endsWith('</urlset>'));
  assert.ok(r.xml.includes('<loc>https://www.rallytakesthetrain.com/x</loc>'));
  const e = newPagesSitemap(null);
  assert.equal(e.added, 0);
  assert.ok(e.xml.includes('<urlset') && !e.xml.includes('<url>'));
});

t('only sitemap files go through the sitemap handler', () => {
  for (const p of ['/sitemap.xml', '/sitemap0.xml', '/sitemap12.xml', NEW_PAGES_SITEMAP]) assert.ok(isSitemapPath(p), p);
  for (const p of ['/sitemap', '/sitemaps', '/sitemap-guide', '/sitemap0.xml.gz', '/hreflang-sitemap.xml']) assert.ok(!isSitemapPath(p), p);
});

console.log(`\n${n} sitemap tests passed`);
