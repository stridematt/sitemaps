// Tests for the sitemap.xml fix. Run: node test/sitemap.test.mjs
import { applySitemapFix } from '../src/index.js';
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

console.log(`\n${n} sitemap tests passed`);
