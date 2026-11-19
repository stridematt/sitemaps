// Tests for the Squarespace sync planner. Run: node test/sqsp.test.mjs
import { planItem, describe, htmlBlocks } from '../src/sqsp.js';
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const DYN = '/home/claude/dyn/';
const live = JSON.parse(readFileSync(new URL('../../tools/truth/live.json', import.meta.url), 'utf8'));
let n = 0;
const t = (name, fn) => { fn(); n++; console.log('ok  ', name); };

// A stored post the way the Squarespace API returns it, built from a rendered page:
// SEO fields from the head, the page body split into two code blocks.
function itemFrom(file, path, extra = {}) {
  const html = readFileSync(DYN + file, 'utf8');
  const title = (html.match(/<title>([^<]*)<\/title>/) || [])[1] || '';
  const desc = (html.match(/<meta name="description" content="([^"]*)"/) || [])[1] || '';
  const un = (s) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
  const body = html.slice(html.indexOf('<body'), html.lastIndexOf('</body>'));
  const cut = body.indexOf('<section class="rtt-pe-ride"');
  const a = body.slice(0, cut), b = body.slice(cut);
  return {
    id: 'x1', fullUrl: path, title: 'Post title (2026)', workflowState: 1, updatedOn: 1,
    seoData: { seoTitle: un(title), seoDescription: un(desc), seoHidden: false, seoImageId: null },
    excerpt: { html: '<p>' + un(desc) + '</p>', raw: false },
    body: { raw: false, layout: { columns: 12, rows: [{ columns: [{ span: 12, blocks: [
      { id: 'b1', type: 1337, value: { html: a, wysiwyg: {} } },
      { id: 'b2', type: 1337, value: { html: b, wysiwyg: {} } },
    ] }] }] } },
    ...extra,
  };
}

t('a post that is already right needs no write', () => {
  const it = itemFrom('christmas-events_denver-co.html', '/christmas-events/denver-co');
  assert.equal(planItem(it, live, '2026-11-18'), null);
});

t('city post on Dec 1: SEO fields, excerpt and code follow the live counts', () => {
  const it = itemFrom('christmas-events_denver-co.html', '/christmas-events/denver-co');
  const p = planItem(it, live, '2026-12-01');
  assert.ok(p && !p.error, p && p.error);
  assert.ok(p.removedCards > 0, 'past events come out of the stored code');
  const after = htmlBlocks(p.item.body.layout).map((b) => b.value.html).join('');
  const cards = (after.match(/<section class="rtt-pe-ride"/g) || []).length;
  assert.ok(p.item.seoData.seoDescription.includes(String(cards)) || p.item.seoData.seoTitle.includes(String(cards)), 'SEO text says the new count');
  assert.ok(p.item.excerpt.html.includes(String(cards)), 'excerpt says the new count');
  assert.equal(p.item.title, 'Post title (2026)', 'the year is not a count');
  assert.equal(p.item.id, 'x1');
  assert.equal(p.item.seoData.seoHidden, false, 'other fields are kept');
  assert.equal(it.seoData.seoTitle === p.item.seoData.seoTitle && it.excerpt.html === p.item.excerpt.html, false);
  // the original object is untouched (it is the backup)
  assert.ok(it.body.layout.rows[0].columns[0].blocks[1].value.html.length > htmlBlocks(p.item.body.layout)[1].value.html.length);
  assert.ok(describe(p).some((l) => l.startsWith('seo')));
  // a second pass over the result changes nothing
  assert.equal(planItem(p.item, live, '2026-12-01'), null);
});

t('guide post: stale stored text is corrected to the guide totals', () => {
  const g = live.guides['/christmas-events/noel-avec-les-enfants-suisse'];
  const it = {
    id: 'g1', fullUrl: '/christmas-events/noel-avec-les-enfants-suisse', title: 'Que faire à Noël avec les enfants en Suisse ? (2026)', workflowState: 1, updatedOn: 1,
    seoData: { seoTitle: 'Noël avec les enfants en Suisse 2026', seoDescription: 'Que faire à Noël avec les enfants en Suisse ? Voici 128 activités vérifiées dans 2 villes, dont 46 gratuites : saint Nicolas.' },
    excerpt: { html: '<p>Nous avons vérifié 128 activités de Noël pour enfants dans 2 villes en Suisse pour 2026 : rencontres.</p>', raw: false },
    body: { raw: false, layout: { rows: [{ columns: [{ blocks: [{ id: 'b1', type: 1337, value: { html: '<p>Voici 128 activités, dont 46 gratuites.</p>' } }] }] }] } },
  };
  const p = planItem(it, live, '2026-11-18');
  assert.ok(p && !p.error);
  assert.equal(p.item.seoData.seoDescription, `Que faire à Noël avec les enfants en Suisse ? Voici ${g.e} activités vérifiées dans 2 villes, dont ${g.f} gratuites : saint Nicolas.`);
  assert.equal(p.item.excerpt.html, `<p>Nous avons vérifié ${g.e} activités de Noël pour enfants dans 2 villes en Suisse pour 2026 : rencontres.</p>`);
  assert.equal(p.item.title, it.title);
  assert.equal(htmlBlocks(p.item.body.layout)[0].value.html, `<p>Voici ${g.e} activités, dont ${g.f} gratuites.</p>`);
});

t('posts outside the Christmas events pages are never planned', () => {
  assert.equal(planItem({ fullUrl: '/blog/hello', seoData: {}, body: {} }, live), null);
  assert.equal(planItem({ fullUrl: '/christmas-events/not-a-known-page', seoData: {}, body: {} }, live), null);
});

t('quotes and ampersands in SEO text survive the round trip', () => {
  const it = itemFrom('christmas-events_denver-co.html', '/christmas-events/denver-co');
  it.seoData.seoTitle = 'Denver "Kids" & Families: ' + it.seoData.seoTitle;
  const p = planItem(it, live, '2026-12-01');
  assert.ok(p.item.seoData.seoTitle.startsWith('Denver "Kids" & Families: '));
});

t('a count the healer cannot read is flagged, so that post is not written', () => {
  const it = { id: 'f', fullUrl: '/christmas-events/finland', title: 'Joulu', workflowState: 1,
    seoData: { seoTitle: 'x', seoDescription: 'Suomessa: 26 tapahtumaa, joista maksuttomia 3.' },
    excerpt: { html: '<p>Vuodelle 2026 meillä on 26 juttua lapsille.</p>' }, body: { layout: { rows: [] } } };
  const p = planItem(it, live, '2026-11-18');
  assert.ok(p && !p.error, p && p.error);
  assert.deepEqual(p.warnings, ['excerpt still says 26']);
});

t('dates are not mistaken for leftover counts', () => {
  const base = { id: 'u', fullUrl: '/christmas-events/utah', title: 'Utah', workflowState: 1, body: { layout: { rows: [] } },
    seoData: { seoTitle: 'x', seoDescription: 'Utah: 60 Christmas events for kids, 20 free.' } };
  const a = planItem({ ...base, excerpt: { html: '<p>Lights run to December 20 and 20. Dezember.</p>' } }, live, '2026-11-18');
  assert.deepEqual(a.warnings, []);
  const b = planItem({ ...base, excerpt: { html: '<p>Lights run to December 20, with 20 more to come.</p>' } }, live, '2026-11-18');
  assert.deepEqual(b.warnings, ['excerpt still says 20']);
});

console.log(`\n${n} sqsp tests passed`);
