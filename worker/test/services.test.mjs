// Unit tests for the Christmas Eve services healers. Run: node test/services.test.mjs
import assert from 'node:assert/strict';
import { healServicesHub, healServicesGuide, servicesHealerFor, isServicesPath, slugPath } from '../src/services.js';

let n = 0;
const t = (name, fn) => { fn(); n++; console.log('ok  ', name); };

const sv = {
  generated: '2026-11-21T06:00Z',
  total: { cities: 1822, churches: 20753, timed: 5012, cw: 1079 },
  cities: { '/christmas-eve-services/bridgeport-ct': [7, 2], '/christmas-eve-services-australia/adelaide-sa': [42, 5], '/christmas-eve-services/danbury-ct': [6, 0] },
  denoms: { '/christmas-eve-services-australia/sydney-nsw-anglican': [3, 2, '/christmas-eve-services-australia/sydney-nsw'] },
  guides: {
    '/christmas-eve-services/united-states': { cities: 740, churches: 9000, timed: 900, cw: 300 },
    '/christmas-eve-services/connecticut': { cities: 16, churches: 130, timed: 12, cw: 8 },
    '/christmas-eve-services-australia/australia': { cities: 33, churches: 431, timed: 42, cw: 18 },
    '/christmas-eve-services-australia/new-south-wales-anglican': { cities: 9, churches: 23, timed: 6, cw: 4, denom: 1,
      rows: { '/christmas-eve-services-australia/sydney-nsw-anglican': [9, 2], '/christmas-eve-services-australia/wollongong-nsw': [3, 2] } },
    '/gottesdienste-heiligabend-deutschland/brandenburg': { cities: 40, churches: 1234, timed: 190, cw: 34 },
  },
};

const xn = { c: [['US', 'United States', '', 'usa', 'en:united-states', 728, 245], ['AU', 'Australia', '', 'au', 'en:/christmas-eve-services-australia/australia', 30, 10]],
  r: { US: ['State', [['CT', 'Connecticut', 'connecticut', 43, 15, '']]] },
  p: [['Bridgeport', '', '', 0, 'CT', 3, 'en:bridgeport-ct', 41.1, -73.2], ['Adelaide', '', '', 1, 'SA', 7, 'en:/christmas-eve-services-australia/adelaide-sa', -34.9, 138.6]] };
const hub = `<p class="lede">Family services at 4,134 churches in 1,312 cities across 13 countries.</p>
<ul class="xn-stat"><li><b>1,312</b>cities</li><li><b>4,134</b>churches</li></ul>
<p>445 of our 1,312 cities already have churches with 2026 service times posted.</p>
<li><i></i>445 with 2026 service times posted so far</li>
<h2>1,312 Christmas Eve lights <em>in 13 countries</em></h2>
<a class="xn-row" href="/christmas-eve-services/connecticut"><span class="xn-row__n">Connecticut</span><span class="rtt-sr">, 15 cities, 43 churches</span></a></span><span class="xn-cta xn-cta--place" aria-hidden="true">15 cities<svg></svg></span>
<summary>Christmas Eve services in Connecticut<span>15 cities</span></summary><div class="xn-az__in"><p class="xn-az__st"><a href="/christmas-eve-services/connecticut">All of Connecticut</a>
<p>Yes. 120 churches in 20 cities in Australia are listed.</p>
<p>4,134 churches in 1,312 cities across 13 countries. 1,016 churches have posted their 2026 times.</p>
<script type="application/json" id="xn-data">${JSON.stringify(xn)}</script>
{"@type":"ListItem","position":445,"name":"Napa"}`;

t('routing: hub and guides only, every collection', () => {
  assert.equal(servicesHealerFor('/christmas-eve-services-near-me', sv), 'svhub');
  assert.equal(servicesHealerFor('/christmas-eve-services/connecticut', sv), 'svguide');
  assert.equal(servicesHealerFor('/christmas-eve-services/bridgeport-ct', sv), null);
  assert.ok(isServicesPath('/pasterka-wigilia-polska/krakow-pl'));
  assert.ok(!isServicesPath('/christmas-events/denver-co'));
  assert.equal(slugPath('en:/christmas-eve-services-uk/aberdeen-uk'), '/christmas-eve-services-uk/aberdeen-uk');
  assert.equal(slugPath('connecticut'), '/christmas-eve-services/connecticut');
});

t('hub: totals, rows, A to Z, per-country FAQ and finder data; list positions untouched', () => {
  const o = healServicesHub(hub, sv);
  assert.match(o, /at 20,753 churches in 1,822 cities across 13 countries/);
  assert.match(o, /<b>1,822<\/b>cities<\/li><li><b>20,753<\/b>churches/);
  assert.match(o, /1,079 of our 1,822 cities/);
  assert.match(o, /1,079 with 2026 service times/);
  assert.match(o, /1,822 Christmas Eve lights/);
  assert.match(o, /, 16 cities, 130 churches<\/span>/);
  assert.match(o, /aria-hidden="true">16 cities<svg/);
  assert.match(o, /<span>16 cities<\/span><\/summary>/);
  assert.match(o, /Yes\. 431 churches in 33 cities in Australia are listed/);
  assert.match(o, /5,012 churches have posted/);
  assert.match(o, /"position":445/);
  const D = JSON.parse(o.match(/id="xn-data">([\s\S]*?)<\/script>/)[1]);
  assert.deepEqual(D.c[0].slice(5), [740, 300]);
  assert.deepEqual(D.r.US[1][0].slice(3, 5), [130, 16]);
  assert.equal(D.p[0][5], 7);
  assert.equal(D.p[1][5], 42);
});

t('guide: headline sentences, chips and timed count, in English and German', () => {
  const g = `<p>Connecticut: 122 churches listed in 15 cities. 11 have confirmed 2026 times.</p>
<a href="/christmas-eve-services/bridgeport-ct"><b>Bridgeport</b><span>5 churches</span></a>
<a href="/christmas-eve-services/danbury-ct"><b>Danbury</b><span>5 churches</span></a>
<script>var x = "12 churches in 3 cities";</script>`;
  const o = healServicesGuide(g, sv, '/christmas-eve-services/connecticut');
  assert.match(o, /130 churches listed in 16 cities\. 12 have confirmed 2026/);
  assert.match(o, /<b>Bridgeport<\/b><span>7 churches/);
  assert.match(o, /<b>Danbury<\/b><span>6 churches/);
  assert.match(o, /"12 churches in 3 cities"/);
  const de = healServicesGuide('<p>Bisher stehen 193 Kirchen in 34 Städten auf der Liste.</p>', sv, '/gottesdienste-heiligabend-deutschland/brandenburg');
  assert.match(de, /1\.234 Kirchen in 40 Städten/);
});

t('denomination guide: table rows use that tradition\'s numbers, not the whole city', () => {
  const g = `<p>23 Anglican churches listed in 9 cities.</p><table><tr><th scope="row"><a href="/christmas-eve-services-australia/sydney-nsw-anglican">Sydney</a></th><td>4</td><td>1</td></tr>
<tr><th scope="row"><a href="/christmas-eve-services-australia/wollongong-nsw#t-anglican">Wollongong</a></th><td>2</td><td>0</td></tr></table>`;
  const o = healServicesGuide(g, sv, '/christmas-eve-services-australia/new-south-wales-anglican') || g;
  assert.match(o, /Sydney<\/a><\/th><td>9<\/td><td>2<\/td>/);
  assert.match(o, /Wollongong<\/a><\/th><td>3<\/td><td>2<\/td>/);
  assert.match(o, /23 Anglican churches listed in 9 cities/);
});

t('no change means null (served as clean)', () => {
  assert.equal(healServicesGuide('<p>130 churches listed in 16 cities.</p>', sv, '/christmas-eve-services/connecticut'), null);
});

t('services lead when the truth file has them: title, description, headline, stat block, FAQ; twice is the same', () => {
  const sv2 = JSON.parse(JSON.stringify(sv)); sv2.total.services = 10687;
  sv2.guides['/christmas-eve-services/connecticut'].services = 30;
  const page = `<title>Christmas Eve Services Near Me 2026: Times by City</title><meta name="description" content="Christmas Eve 2026 service times by city, family first.">` + hub
    + `<details><summary>How many cities and churches are listed?</summary><p>4,134 churches in 1,312 cities across 13 countries.</p></details>`;
  const o = healServicesHub(page.replace('<p class="lede">Family services at', '<p class="lede">Family services, candlelight services and midnight Masses at'), sv2);
  assert.match(o, /<title>Christmas Eve Services Near Me 2026: 10,000\+ Services by City/);
  assert.match(o, /content="10,687 Christmas Eve services at 20,753 churches: Christmas Eve 2026 service times/);
  assert.match(o, /10,687 Christmas Eve services, from family services and candlelight services to midnight Masses, at 20,753 churches in 1,822 cities across 13 countries/);
  assert.match(o, /<li><b>10,687<\/b>Christmas Eve services<\/li><li><b>20,753<\/b>churches<\/li><li><b>1,822<\/b>cities/);
  assert.match(o, /How many services, churches and cities are listed\?<\/summary><p>10,687 Christmas Eve services at 20,753 churches in 1,822 cities/);
  assert.equal(healServicesHub(o, sv2), null);
  const g = healServicesGuide('<p>Connecticut: 122 churches listed in 15 cities.</p>', sv2, '/christmas-eve-services/connecticut');
  assert.match(g, /30 Christmas Eve services at 130 churches listed in 16 cities/);
  assert.equal(healServicesGuide(g, sv2, '/christmas-eve-services/connecticut'), null);
});

console.log(`${n} services tests passed`);
