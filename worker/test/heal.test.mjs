// Unit tests for the self-healing counts, with fixed dates. Run: node test/heal.test.mjs
import { healHub, healCity, healGuide, rewriteCounts, refToday } from '../src/heal.js';
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const DYN = '/home/claude/dyn/';
const live = JSON.parse(readFileSync(new URL('../../tools/truth/live.json', import.meta.url), 'utf8'));
let n = 0;
const t = (name, fn) => { fn(); n++; console.log('ok  ', name); };

t('count phrases in several languages; dates, times and years are left alone', () => {
  assert.equal(rewriteCounts('Denver 2026: 39 Events, 13 Free', 36, 12), 'Denver 2026: 36 Events, 12 Free');
  assert.equal(rewriteCounts('13 of 39 are free. Starts Dec 13 at 13:00.', 36, 12), '12 of 36 are free. Starts Dec 13 at 13:00.');
  assert.equal(rewriteCounts('Yes. 13 of the 39 events on this page are free', 36, 12), 'Yes. 12 of the 36 events on this page are free');
  assert.equal(rewriteCounts('Advent mit Kindern in Graz: 28 geprüfte Tipps, 8 kostenlos.', 27, 7), 'Advent mit Kindern in Graz: 27 geprüfte Tipps, 7 kostenlos.');
  assert.equal(rewriteCounts('Kostenlos auf dieser Seite: 8 von 28 Veranstaltungen.', 27, 7), 'Kostenlos auf dieser Seite: 7 von 27 Veranstaltungen.');
  assert.equal(rewriteCounts('Voici 128 activités vérifiées dans 2 villes, dont 46 gratuites', 120, 40), 'Voici 120 activités vérifiées dans 2 villes, dont 40 gratuites');
  assert.equal(rewriteCounts('179の都市・地域で1534件（うち無料412件）', 1500, 400, null, { e: 1534, f: 412 }), '179の都市・地域で1500件（うち無料400件）');
  assert.equal(rewriteCounts('野田のクリスマスイベント20選｜0歳から行ける10件', 18, 5, null, { e: 20, f: 6 }), '野田のクリスマスイベント20選｜0歳から行ける10件', 'a subset count stays');
  assert.equal(rewriteCounts('For 1 of the 2 Christmas events for kids in Ann Arbor, yes: they sell tickets', 1, 0), 'For 1 of the 1 Christmas event for kids in Ann Arbor, yes: they sell tickets');
  assert.equal(rewriteCounts('2 family events across Ann Arbor and Dexter, 1 of them free', 1, 0), '1 family event across Ann Arbor and Dexter, none of them free');
  assert.equal(rewriteCounts('A 110-foot tree, 15 minutes, ages 3 to 5, $20, open 5 to 10 pm', 36, 12), 'A 110-foot tree, 15 minutes, ages 3 to 5, $20, open 5 to 10 pm');
  assert.equal(rewriteCounts('36 family events across Denver and 5 nearby towns, 13 of them free', 30, 9), '30 family events across Denver and 5 nearby towns, 9 of them free');
  assert.equal(rewriteCounts('We found 73 confirmed Christmas events for kids', 81, 10), 'We found 81 confirmed Christmas events for kids');
  assert.equal(rewriteCounts('Suomessa: 26 tapahtumaa, joista maksuttomia 3. Avoinna 3.12.', 652, 246), 'Suomessa: 652 tapahtumaa, joista maksuttomia 246. Avoinna 3.12.');
  assert.equal(rewriteCounts('olemme vahvistaneet 26 lasten joulutapahtumaa', 652, 246), 'olemme vahvistaneet 652 lasten joulutapahtumaa');
});

t('reference day is UTC-12', () => {
  assert.equal(refToday(Date.UTC(2026, 11, 2, 11, 0)), '2026-12-01');
  assert.equal(refToday(Date.UTC(2026, 11, 2, 13, 0)), '2026-12-02');
});

t('city page: nothing stale today, so nothing changes', () => {
  const html = readFileSync(DYN + 'christmas-events_denver-co.html', 'utf8');
  assert.equal(healCity(html, '2026-11-18', live.pages, '/christmas-events/denver-co'), null);
});

t('city page on Dec 1: past events removed and every count follows', () => {
  const html = readFileSync(DYN + 'christmas-events_denver-co.html', 'utf8');
  const out = healCity(html, '2026-12-01', live.pages, '/christmas-events/denver-co');
  const cards = (out.match(/<section class="rtt-pe-ride"/g) || []).length;
  const free = [...out.matchAll(/<section class="rtt-pe-ride"[^>]*data-xf-fl="([^"]*)"/g)].filter((m) => m[1].split(' ').includes('free')).length;
  assert.ok(cards < 39);
  assert.match(out, new RegExp(`<title>Denver Christmas Events for Kids 2026: ${cards} Events, ${free} Free</title>`));
  assert.ok(out.includes(`${free} of ${cards} are free.`));
  assert.ok(out.includes(`data-xf-total="${cards}"`));
  assert.ok(!out.includes('id="ev-denver-grand-illumination-at-denver-union"'), 'a Nov 27 event is gone');
  for (const m of out.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)) JSON.parse(m[1]);
  assert.ok(out.includes('Friday, November 20, 2026 to Wednesday, December 23, 2026'), 'dates untouched');
});

t('state guide: each city section and link says that city’s own counts', () => {
  const html = readFileSync(DYN + 'christmas-events_colorado.html', 'utf8');
  const out = healGuide(html, '2026-11-18', live, '/christmas-events/colorado');
  const den = live.pages['/christmas-events/denver-co'][0];
  assert.ok(out.includes(`See all ${den} events in Denver`));
  assert.ok(out.includes(`${den} Christmas events in and around Denver`));
  assert.ok(out.includes(`${live.guides['/christmas-events/colorado'].e} Christmas events for kids in Colorado`));
});

t('hub: finder data, rows, A to Z and headline all from live.json', () => {
  const html = readFileSync(DYN + 'christmas-events-for-kids.html', 'utf8');
  const out = healHub(html, live, { day: '2026-11-18' });
  const T = live.total;
  assert.ok(out.includes(`<title>Christmas Events for Kids Near Me 2026: ${(Math.floor(T.events / 1000) * 1000).toLocaleString('en-US')}+ Events</title>`));
  const notInHub = Object.entries(live.cities).find(([, c]) => !c[5]);
  if (notInHub) assert.ok(out.includes(`href="${notInHub[0]}"`), 'a city missing from the A to Z is listed');
  const n = (x) => x.toLocaleString('en-US');
  assert.ok(out.includes(`<h2 class="xn-map__h" id="xn-map-h">${n(T.events)} Christmas events for kids <em>around the world</em></h2>`), 'map heading leads with events');
  assert.ok(out.includes(`${n(T.events)} Christmas events in ${n(T.cities_with_events)} cities</li>`), 'gold legend: events and cities');
  assert.ok(out.includes(`${n(T.cities - T.cities_with_events)} cities we&rsquo;re actively adding</li>`), 'gray legend: cities being added');
  assert.ok(out.includes(`<p class="rtt-lp__lede">${n(T.events)} Christmas events for kids in ${n(T.cities)} cities across ${T.countries} countries:`), 'hero line');
  assert.ok(out.includes("rgba(170,176,186,.62)") && !out.includes("rgba(214,226,246,.55)"), 'cities being added are gray on the map');
  assert.ok(out.includes('Last updated November 18, 2026'));
  const text = out.replace(/<script[\s\S]*?<\/script>/g, '').replace(/a light for each of the [\d,]+ cities/g, '');
  const leftover = (text.match(/\b3,2(42|64)\b[^<]{0,20}(cities|city guides)/) || [null])[0];
  assert.equal(leftover, null, 'no old city total left');
  const D = JSON.parse(out.match(/id="xn-data">([\s\S]*?)<\/script>/)[1]);
  const us = D.c.find((c) => c[0] === 'US');
  assert.equal(us[7], live.countries['United States'].events);
});
console.log(`\n${n} heal tests passed`);
