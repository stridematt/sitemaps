// Self-healing numbers for the Christmas events pages.
//
// Pages are written once and then go stale: events pass, cities are added, counts drift
// between the title, the meta description, the body and the structured data. These
// functions recompute every count from the facts (the event cards themselves, or the
// registry built every 3 hours in tools/truth/live.json) and write the right number back
// into every place it appears. Each function returns null when it has nothing to change,
// and the caller then serves the original page untouched.

const num = (n) => Number(n).toLocaleString('en-US');
const plural = (n, one, many) => `${num(n)} ${n === 1 ? one : many}`;
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

export function dateLabel(iso, short) {
  const [y, m, d] = iso.split('-').map(Number);
  return short ? `${MONTHS[m - 1].slice(0, 3)} ${d}` : `${MONTHS[m - 1]} ${d}, ${y}`;
}

// Today for event expiry: an event stays listed until its last day is over everywhere (UTC-12).
export function refToday(now = Date.now()) {
  return new Date(now - 12 * 3600 * 1000).toISOString().slice(0, 10);
}

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// ---------------------------------------------------------------------------------- hub
// /christmas-events-for-kids: totals, country and state rows, the finder data, the A to Z.

// Language of a page from its address (for the finder's language chips)
const LANG_PREFIX = [['navidad-con-ninos-', 'es'], ['natal-com-criancas-', 'pt'], ['noel-avec-les-enfants-', 'fr'], ['activites-de-noel-pour-enfants-', 'fr'],
  ['weihnachten-mit-kindern-', 'de'], ['natale-con-i-bambini-', 'it'], ['kerst-met-kinderen-', 'nl'], ['kodomo-christmas-', 'ja']];
const pageRef = (p) => {
  const s = String(p).replace(/^\/christmas-events\//, '');
  return `${(LANG_PREFIX.find(([pre]) => s.startsWith(pre)) || [0, 'en'])[1]}:${s}`;
};
const escText = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const escAttr = (s) => escText(s).replace(/"/g, '&quot;');
// Region of the hub's "by country" list for countries added after the hub was built
const GROUP = {};
for (const n of ['Argentina', 'Bolivia', 'Brazil', 'Chile', 'Colombia', 'Ecuador', 'Paraguay', 'Peru', 'Uruguay', 'Venezuela', 'Mexico', 'Canada', 'United States', 'Dominican Republic', 'Puerto Rico', 'Cuba', 'Jamaica', 'Trinidad and Tobago']) GROUP[n] = 'The Americas';
for (const n of ['Belize', 'Costa Rica', 'El Salvador', 'Guatemala', 'Honduras', 'Nicaragua', 'Panama']) GROUP[n] = 'Central America';
for (const n of ['South Africa', 'Kenya', 'Nigeria', 'Ghana', 'Egypt', 'Morocco', 'Ethiopia', 'Madagascar', 'Tanzania', 'Uganda', 'Israel', 'Lebanon', 'Jordan', 'United Arab Emirates', 'Qatar', 'Saudi Arabia', 'Bahrain', 'Kuwait', 'Oman']) GROUP[n] = 'Africa and the Middle East';
for (const n of ['Australia', 'New Zealand', 'Japan', 'South Korea', 'Philippines', 'Singapore', 'Hong Kong', 'India', 'Indonesia', 'Malaysia', 'Thailand', 'Vietnam', 'Taiwan', 'China', 'Fiji']) GROUP[n] = 'Asia and the Pacific';
for (const n of ['Albania', 'Andorra', 'Austria', 'Belgium', 'Bosnia and Herzegovina', 'Bulgaria', 'Croatia', 'Cyprus', 'Czech Republic', 'Denmark', 'Estonia', 'Finland', 'France', 'Germany', 'Greece', 'Hungary', 'Iceland', 'Ireland', 'Italy', 'Latvia', 'Liechtenstein', 'Lithuania', 'Luxembourg', 'Malta', 'Monaco', 'Montenegro', 'Netherlands', 'North Macedonia', 'Norway', 'Poland', 'Portugal', 'Romania', 'Serbia', 'Slovakia', 'Slovenia', 'Spain', 'Sweden', 'Switzerland', 'Ukraine', 'United Kingdom']) GROUP[n] = 'Europe';

for (const n of ['The Bahamas', 'Bahamas', 'Barbados', 'Bermuda', 'Cayman Islands', 'Guyana', 'Grenada', 'Saint Lucia', 'Saint Kitts and Nevis', 'Saint Vincent and the Grenadines', 'Antigua and Barbuda', 'Turks and Caicos Islands', 'US Virgin Islands', 'British Virgin Islands', 'Republica Dominicana', 'Haiti', 'Suriname', 'Dominica', 'Aruba', 'Curacao', 'Anguilla', 'Montserrat', 'Sint Maarten', 'Greenland']) GROUP[n] = 'The Americas';
for (const n of ['The Gambia', 'Gambia', 'Sierra Leone', 'Liberia', 'Mauritius', 'Rwanda', 'Zambia', 'Zimbabwe', 'Namibia', 'Botswana', 'Malawi', 'Senegal', 'Cameroon', 'Angola', 'Mozambique', 'Seychelles', 'Cape Verde', 'Equatorial Guinea', 'Tunisia', 'Algeria', 'Ivory Coast', 'Lesotho', 'Eswatini', 'South Sudan', 'Turkey', 'Palestine', 'Iraq', 'Syria']) GROUP[n] = 'Africa and the Middle East';
for (const n of ['Cambodia', 'Bangladesh', 'Sri Lanka', 'Pakistan', 'Guam', 'Vanuatu', 'Samoa', 'Tonga', 'Papua New Guinea', 'Solomon Islands', 'Nepal', 'Mongolia', 'Laos', 'Myanmar', 'Brunei', 'Macau', 'Kazakhstan', 'Uzbekistan', 'Kyrgyzstan', 'Northern Mariana Islands', 'New Caledonia', 'French Polynesia']) GROUP[n] = 'Asia and the Pacific';
for (const n of ['Gibraltar', 'Guernsey', 'Jersey', 'Isle of Man', 'Czechia', 'Armenia', 'Georgia', 'Moldova', 'Belarus', 'San Marino', 'Faroe Islands', 'Kosovo', 'Russia']) GROUP[n] = 'Europe';

export function healHub(html, live, opts = {}) {
  if (!live || !live.total || !html.includes('id="xn-data"')) return null;
  const T = live.total;
  const day = opts.day || live.today;
  let out = html;
  const rep = (re, fn) => {
    out = out.replace(re, fn);
  };
  const rounded = `${num(Math.floor(T.events / 1000) * 1000)}+`;

  // 1. Finder data: live event counts per city, cities and events per country and state.
  const dataRe = /(<script type="application\/json" id="xn-data">)([\s\S]*?)(<\/script>)/;
  const m = out.match(dataRe);
  let mapped = 0;
  let onMap = 0;
  if (m) {
    let D;
    try {
      D = JSON.parse(m[2]);
    } catch (e) {
      D = null;
    }
    if (D && Array.isArray(D.c) && Array.isArray(D.p)) {
      const byPath = new Map();
      for (const [p, c] of Object.entries(live.cities || {})) {
        byPath.set(p, c);
        for (const a of c[6] || []) byPath.set(a, c);
      }
      for (const a of D.p) {
        const slugs = String(a[6] || '').split(',').map((x) => x.slice(x.indexOf(':') + 1));
        const c = slugs.map((s) => byPath.get('/christmas-events/' + s)).find(Boolean);
        if (c) {
          a[5] = c[0];
          mapped++;
        }
        if (a[7] != null) onMap++;
      }
      for (const c of D.c) {
        const g = (live.countries || {})[c[1]];
        if (!g) continue;
        c[5] = g.cities;
        c[6] = g.cities_with_events;
        c[7] = g.events;
      }
      // countries live on the site that the hub data does not list yet, and city guides it is missing
      const cIdx = new Map(D.c.map((c, i) => [c[1], i]));
      for (const [name, g] of Object.entries(live.countries || {})) {
        if (cIdx.has(name) || !g.guide || !/^[A-Z]{2}$/.test(g.cc || '')) continue;
        D.c.push([g.cc, name, '', '', pageRef(g.guide), g.cities, g.cities_with_events, g.events]);
        cIdx.set(name, D.c.length - 1);
      }
      const known = new Set();
      for (const a of D.p) for (const x of String(a[6] || '').split(',')) known.add('/christmas-events/' + x.slice(x.indexOf(':') + 1));
      for (const [p, c] of Object.entries(live.cities || {})) {
        if (c[3] === 'United States' || c[3] === 'Canada' || !cIdx.has(c[3])) continue;
        if (known.has(p) || (c[6] || []).some((q) => known.has(q))) continue;
        D.p.push([c[2], '', '', cIdx.get(c[3]), '', c[0], [p].concat(c[6] || []).map(pageRef).join(','), null, null, 0]);
      }
      for (const cc of Object.keys(D.r || {})) {
        for (const r of D.r[cc][1] || []) {
          const g = (live.regions || {})[`${cc}-${r[0]}`];
          if (!g) continue;
          r[3] = g.events;
          r[4] = g.cities;
        }
      }
      const json = JSON.stringify(D).replace(/</g, '\\u003c');
      out = out.replace(dataRe, (_, a, __, b) => a + json + b);
    }
  }
  if (!mapped) return null; // the data block changed shape: leave the page alone

  // 2. Country and state rows lead with events (the finder script builds these rows).
  out = out.replace(
    "cities: a[5], live: a[6], regs: [], list: []}",
    "cities: a[5], live: a[6], events: a[7] || 0, regs: [], list: []}",
  );
  out = out.replace(
    "sub || (x.t === 'r' && q ? x.c.name : ''), plural(n, 'city', 'cities'), 'xn-cta--place');",
    "sub || (x.t === 'r' && q ? x.c.name : ''), (x.events > 0 ? plural(x.events, 'event', 'events') : plural(n, 'city', 'cities')), 'xn-cta--place');",
  );

  // 3. The same rows as served before the script runs (and as crawlers see them).
  const cc2name = {};
  if (m) {
    try {
      for (const c of JSON.parse(m[2]).c) cc2name[c[0]] = c[1];
    } catch (e) {}
  }
  rep(/(<a class="xn-row" href="[^"]*" data-xn-cc="([A-Z]{2})"[^>]*>[\s\S]*?<span class="rtt-sr">, )([\d,]+ cit(?:y|ies))(<\/span><\/a><\/span><span class="xn-cta xn-cta--place" aria-hidden="true">)([\d,]+ cit(?:y|ies))/g,
    (all, a, cc, _s, b) => {
      const g = (live.countries || {})[cc2name[cc]];
      if (!g) return all;
      const cities = plural(g.cities, 'city', 'cities');
      if (!(g.events > 0)) return `${a}${cities}${b}${cities}`;
      const label = plural(g.events, 'event', 'events');
      return `${a}${label} in ${cities}${b}${label}`;
    });

  // 3b. Countries live on the site that the "by country" list does not show yet, in their region,
  // alphabetically, with the region's country count kept right.
  const svg = (out.match(/<span class="xn-cta xn-cta--place" aria-hidden="true">[^<]*(<svg class="xn-cta__ic"[\s\S]*?<\/svg>)/) || [])[1] || '';
  const listed = new Set([...out.matchAll(/<a class="xn-row" href="[^"]*" data-xn-cc="[A-Z]{2}"[^>]*><span class="xn-row__n">([^<]+?)\s*(?:<|<\/span>)/g)].map((x) => x[1].trim()));
  const extra = {};
  for (const [name, g] of Object.entries(live.countries || {})) {
    if (listed.has(name) || !g.guide || !GROUP[name] || !/^[A-Z]{2}$/.test(g.cc || '')) continue;
    const cities = plural(g.cities, 'city', 'cities');
    const label = g.events > 0 ? plural(g.events, 'event', 'events') : cities;
    const sr = g.events > 0 ? `${label} in ${cities}` : cities;
    (extra[GROUP[name]] = extra[GROUP[name]] || []).push([name,
      `<li class="xn-item xn-item--place"><span class="xn-row__t"><a class="xn-row" href="${escAttr(g.guide)}" data-xn-cc="${g.cc}"><span class="xn-row__n">${escText(name)}</span><span class="rtt-sr">, ${sr}</span></a></span><span class="xn-cta xn-cta--place" aria-hidden="true">${label}${svg}</span></li>`]);
  }
  rep(/(<h3 class="xn-grp">)([^<]+?)(\s*<span class="xn-grp__n">\()\d+( countr(?:y|ies)\)<\/span><\/h3><ul class="xn-list" role="list">)([\s\S]*?)(<\/ul>)/g, (all, a, grp, b, c, body, d) => {
    let rows = [...body.matchAll(/<li class="xn-item xn-item--place">[\s\S]*?<\/li>(?=<li class="xn-item|$)/g)].map((x) => x[0]);
    if (!rows.length) return all;
    const name = (r) => ((r.match(/<span class="xn-row__n">([^<]+)/) || [])[1] || '').trim();
    const add = extra[grp.trim()] || [];
    if (add.length) rows = rows.concat(add.map((x) => x[1])).sort((x, y) => name(x).localeCompare(name(y)));
    const n = rows.length;
    return `${a}${grp}${b}${n}${c.replace(/countr(?:y|ies)/, n === 1 ? 'country' : 'countries')}${rows.join('')}${d}`;
  });

  // 3c. The results line the finder script writes on load (it counted its own, older data)
  rep(/setHead\('Christmas around the world', [^;]*?\);/, () =>
    `setHead('Christmas around the world', ${JSON.stringify(`${num(T.events)} Christmas events in ${num(T.cities)} cities across ${T.countries} countries. Type your city above, start near you, or browse every country below.`)});`);
  // The FAQ's list of countries (visible answer and its structured data) includes every country on the site
  const listNames = (txt) => txt.split(/, | and /).map((x) => x.trim()).filter(Boolean);
  const joinNames = (a) => (a.length > 1 ? `${a.slice(0, -1).join(', ')} and ${a[a.length - 1]}` : a.join(''));
  const allCountries = Object.keys(live.countries || {});
  rep(/((?:<summary>|"name":")Which countries have Christmas events for kids in the guide\?(?:<\/summary><p>|","acceptedAnswer":\{"@type":"Answer","text":"))([^<"]+?)(\. Choose any country)/g, (all, a, list, b) => {
    const names = new Set(listNames(list));
    if (!names.size) return all;
    for (const n of allCountries) names.add(n);
    return a + joinNames([...names].sort((x, y) => x.localeCompare(y))) + b;
  });
  // Merry Christmas language guides
  if (T.languages > 0) rep(/(Merry Christmas in )\d+( languages)/g, (_, a, b) => `${a}${T.languages}${b}`);

  // 4. A to Z: events and cities per country, and every city guide the list was missing.
  const names = Object.keys(live.countries || {});
  rep(/(<summary>Christmas events for kids in (?:the )?([^<]+)<span>)([\d,]+ cit(?:y|ies))(<\/span><\/summary>)/g, (all, a, name, _c, b) => {
    const g = (live.countries || {})[name];
    if (!g) return all;
    return `${a}${g.events > 0 ? plural(g.events, 'event', 'events') + ' · ' : ''}${plural(g.cities, 'city', 'cities')}${b}`;
  });
  const missing = {};
  for (const [p, c] of Object.entries(live.cities || {})) {
    if (c[5]) continue;
    const key = c[3] === 'United States' ? 'st:' + c[4] : 'co:' + c[3];
    (missing[key] = missing[key] || []).push([c[2], p]);
  }
  const addLis = (ul, list) => {
    const items = ul.match(/<li>[\s\S]*?<\/li>/g) || [];
    const all = items.map((li) => [((li.match(/>([^<]+)<\/a>/) || [])[1] || '').toLowerCase(), li]);
    for (const [n, p] of list) {
      if (ul.includes(`href="${p}"`)) continue;
      all.push([n.toLowerCase(), `<li><a href="${p}">${esc(n)}</a></li>`]);
    }
    all.sort((x, y) => x[0].localeCompare(y[0]));
    return all.map((x) => x[1]).join('');
  };
  // US: city lists sit under each state heading
  rep(/(<h4 class="xn-az__st" id="st-[a-z]+"><a href="([^"]+)">[^<]*<\/a><\/h4><ul class="xn-az__l" role="list">)([\s\S]*?)(<\/ul>)/g, (all, a, statePath, ul, b) => {
    const list = missing['st:' + statePath];
    return list ? a + addLis(ul, list) + b : all;
  });
  // Other countries: one list per country
  rep(/(<details class="xn-az__c" id="az-[a-z]+"><summary>Christmas events for kids in (?:the )?([^<]+)<span>[\s\S]*?<\/summary>[\s\S]*?<ul class="xn-az__l" role="list">)([\s\S]*?)(<\/ul><\/div><\/details>)/g, (all, a, name, ul, b) => {
    const list = missing['co:' + name];
    return list && name !== 'United States' ? a + addLis(ul, list) + b : all;
  });

  // 5. Headline numbers
  rep(/<ul class="xn-stat" id="xn-stat" role="list">[\s\S]*?<\/ul>/,
    () => `<ul class="xn-stat" id="xn-stat" role="list"><li><b>${num(T.events)}</b>Christmas events</li><li><b>${num(T.cities)}</b>cities</li><li><b>${num(T.countries)}</b>countries</li></ul>`);
  // Events lead everywhere: "N Christmas events in M cities across K countries".
  const adding = Math.max(0, T.cities - T.cities_with_events);
  const evLine = `${num(T.events)} Christmas events for kids in ${num(T.cities)} cities across ${T.countries} countries`;
  rep(/(<p class="rtt-lp__lede">)[\s\S]*?(<\/p>)/, (_, a, b) =>
    `${a}${evLine}: Santa visits, story times, tree lightings, markets and holiday shows. Every guide has dates, times, costs and a link straight to the host.${b}`);
  rep(/(<p class="xn-res__sub" id="xn-sub">)[\s\S]*?(<\/p>)/, (_, a, b) =>
    `${a}${num(T.events)} Christmas events in ${num(T.cities)} cities across ${T.countries} countries. Type your city above, start near you, or browse every country below.${b}`);
  // The map: gold lights are cities with confirmed events (bigger where there are more), gray lights are cities being added
  rep(/(<h2 class="xn-map__h" id="xn-map-h">)[\s\S]*?(<\/h2>)/, (_, a, b) => `${a}${num(T.events)} Christmas events for kids <em>around the world</em>${b}`);
  rep(/(<p class="xn-map__p">)[\s\S]*?(<\/p>)/, (_, a, b) =>
    `${a}Every gold light is a city with confirmed Christmas events for kids, and the bigger the light, the more events it has. Gray lights are cities we are actively adding as hosts post their dates. Tap any part of the map to see the guides closest to that spot.${b}`);
  rep(/(<canvas class="xn-map__c" id="xn-map-c" role="img" aria-label=")[^"]*(")/, (_, a, b) =>
    `${a}World map of ${num(T.events)} Christmas events for kids: gold lights for the ${num(T.cities_with_events)} cities with confirmed events, gray lights for ${num(adding)} cities we are adding. Use the search box or the Find guides near me button to reach the same guides.${b}`);
  rep(/(<ul class="xn-map__legend" role="list"><li><i aria-hidden="true"><\/i>)[^<]*(<\/li><li><i aria-hidden="true"><\/i>)[^<]*(<\/li>)/, (_, a, b, c) =>
    `${a}${num(T.events)} Christmas events in ${plural(T.cities_with_events, 'city', 'cities')}${b}${plural(adding, 'city', 'cities')} we&rsquo;re actively adding${c}`);
  // gray (not blue-white) for the cities being added, on the map and in the legend
  rep(/fillStyle = dim \? 'rgba\(214,226,246,\.14\)' : 'rgba\(214,226,246,\.55\)'/, () => "fillStyle = dim ? 'rgba(170,176,186,.16)' : 'rgba(170,176,186,.62)'");
  rep(/(\.xn-map__legend li\+li i\{width:8px;height:8px;background:)rgba\(214,226,246,\.7\)/, (_, a) => a + 'rgba(170,176,186,.85)');
  rep(/(Choose a country to see every city we cover there\. )[\d,]+( cities already have confirmed 2026 events)/, (_, a, b) => a + num(T.cities_with_events) + b);
  rep(/(Christmas 2026 in )\d+( countries)/g, (_, a, b) => a + T.countries + b);
  rep(/The guide covers [\d,]+ cities in \d+ countries/g, () => `The guide covers ${num(T.cities)} cities in ${T.countries} countries`);
  rep(/[\d,]+ of those cities already have confirmed 2026 events, and together the guides answer [\d,]+ questions/g,
    () => `${num(T.cities_with_events)} of those cities already have confirmed 2026 events (${num(T.events)} events in all), and together the guides answer ${num(T.faq)} questions`);
  rep(/\b[\d,]+( cities across )\d+( countries)/g, (_, a, b) => num(T.cities) + a + T.countries + b);
  rep(/\b[\d,]+( city guides in )\d+( countries)/g, (_, a, b) => num(T.cities) + a + T.countries + b);
  rep(/(All )[\d,]+( cities in one place)/g, (_, a, b) => a + num(T.cities) + b);
  rep(/Christmas events for kids in [\d,]+ cities and \d+ countries/g, () => `Christmas events for kids in ${num(T.cities)} cities and ${T.countries} countries`);
  rep(/(Last updated )[A-Z][a-z]+ \d{1,2}, \d{4}/, (_, a) => a + dateLabel(day));
  // Title, description and social cards
  rep(/(Christmas Events for Kids Near Me 2026: )[\d,]+\+( Events)/g, (_, a, b) => a + rounded + b);
  rep(/Updated [A-Z][a-z]{2} \d{1,2}: [\d,]+\+ Christmas events for kids, ([^"]*?) in [\d,]+ cities across \d+ countries\./g,
    (_, mid) => `Updated ${dateLabel(day, true)}: ${rounded} Christmas events for kids, ${mid} in ${num(T.cities)} cities across ${T.countries} countries.`);
  // Structured data: one entry per country with its city and event counts
  rep(/("name":"Christmas events for kids in (?:the )?([^"]+)","about":\{"@id":"#c-[a-z]+"\},"description":")[\d,]+ city guides?, [\d,]+ with confirmed 2026 events"/g, (all, a, name) => {
    const g = (live.countries || {})[name];
    return g ? `${a}${plural(g.cities, 'city guide', 'city guides')}, ${num(g.cities_with_events)} with confirmed 2026 events, ${plural(g.events, 'event', 'events')}"` : all;
  });
  // The hub's own structured data carries today's date (Matt, 2026-11-21: the hub is republished
  // with new counts every day, so its CollectionPage is dated the counts' day).
  if (day) {
    out = out.replace(/(<script type="application\/ld\+json">)([\s\S]*?)(<\/script>)/g, (all, o, js, c) => {
      if (!js.includes('CollectionPage')) return all;
      let J;
      try { J = JSON.parse(js); } catch (e) { return all; }
      let hit = false;
      for (const n of J['@graph'] || [J]) {
        if (n && n['@type'] === 'CollectionPage') { n.datePublished = day; n.dateModified = day; hit = true; }
      }
      return hit ? o + JSON.stringify(J).replace(/<\//g, '<\\/') + c : all;
    });
  }
  return out === html ? null : out;
}

// --------------------------------------------------------------------------- count words
// A number is an event count only when an event word follows it (a free count when a free
// word follows or leads it). Dates, times, ages, prices and years never match.
const EVENT_WORDS = [
  'events?', 'Events?', 'Christmas events?', 'family events?', 'kids events?', 'kids Christmas events?', 'confirmed events?',
  'activités?', 'sorties', 'Veranstaltungen', 'Tipps', 'geprüfte Tipps', 'Ausflugstipps', 'Termine', 'uitjes', 'uitstappen',
  'activiteiten', 'planes', 'eventos', 'actividades', 'eventi', 'programas', 'programmi', 'atividades', 'juleaktiviteter',
  'aktiviteter', 'julevenemang', 'evenemang', 'arrangementer', 'joulutapahtumaa', 'tapahtumaa', 'karácsonyi programot?',
  'programot?', 'programok', 'wydarzeń', 'wydarzenia', 'imprez', 'evenimente', 'події', 'подій', 'події', 'εκδηλώσεις',
  'εκδήλωση', 'Weihnachtsveranstaltungen', 'Weihnachtsaktivitäten', 'Aktivitäten', 'idées', 'ideas', 'Ideas', 'Ideen', 'Weihnachtsangebote', 'Advent- und Weihnachtsangebote', 'Angebote', 'idee', 'idéias', 'ideias', 'događanja', 'sündmust', 'pasākumi', 'renginių', 'renginiai', 'podujatí', 'prireditev', 'viðburðir', 'viðburði',
  'akcí', 'akce', 'akci', 'událostí', 'فعالية', 'فعاليات',
];
const FREE_AFTER = ['free', 'Free', 'sont gratuites?', 'sont gratuits', 'son gratuitos', 'son gratuitas', 'sono gratuiti', 'são gratuitos', 'são gratuitas', 'zijn gratis', 'sind kostenlos', 'er gratis', 'är gratis', 'kostenlos', 'gratis', 'gratuites?', 'gratuits?', 'gratuitos', 'gratuitas',
  'gratuiti', 'gratuite', 'ingyenes', 'maksuttomia', 'bezpłatnych', 'bezpłatne', 'darmowych', 'безкоштовних', 'безкоштовні',
  'δωρεάν', 'besplatnih', 'tasuta', 'bezmaksas', 'nemokamų', 'zadarmo', 'brezplačnih', 'ókeypis', 'free events?', 'zdarma', 'مجانية', 'مجانًا', 'مجانا'];
const SP = '[\\s\\u00a0\\u202f]+';
const NUM = '(\\d{1,3}(?:[,.\\u00a0\\u202f]\\d{3})+|\\d+)';
const ADJ = `(?:(?:confirmed|verified|family|Christmas|holiday|festive|kids|geprüfte|bestätigte|weihnachtliche|lasten|vahvistettua|barnens|gyerek|bekreftede|bekräftade|bekræftede|bevestigde|confirmados|confirmadas|confirmées|confermati|vánočních|adventních|ověřených)${SP}){0,2}`;
const E_RE = new RegExp(`(^|[^\\d.,:/-])${NUM}(?=${SP}${ADJ}(?:${EVENT_WORDS.join('|')})(?![\\w-]))`, 'g');
const F_RE = new RegExp(`(^|[^\\d.,:/-])${NUM}(?=${SP}(?:${FREE_AFTER.join('|')})(?![\\w-]))`, 'g');
// "joista maksuttomia 3", "davon kostenlos: 3" (the free word comes first)
const FREE_BEFORE = ['joista maksuttomia', 'joista ilmaisia', 'varav gratis', 'hvorav gratis', 'heraf gratis', 'davon kostenlos', 'davon gratis',
  'w tym bezpłatnych', 'ebből ingyenes', 'of which free', 'dont gratuites'];
const FB_RE = new RegExp(`((?:${FREE_BEFORE.join('|')}):?${SP})${NUM}(?![\\d]|[.,]\\d)`, 'g');
// "13 of 39 are free", "13 of the 39 events"
const FOUND_RE = /(\b(?:We|we) found )(\d[\d,]*)( for kids)/g;
const ARE_FREE_RE = /(^|[^\d.,:\/-])(\d+)(?= (?:are|is) free)/g;
const THEM_RE = /(^|[^\d.,:\/-])(\d+)(?= of them (?:are |is )?free)/g;
const OF_WORDS = '(?:of(?: the)?|von|de|sur|van|van de|di|av|af|z|din|από|od|iš|из|з|af|af de)';
const OF_RE = new RegExp(`(^|[^\\d.,:/-])(\\d+)(${SP}${OF_WORDS}${SP})(\\d+)(?=${SP}(?:are free|is free|${EVENT_WORDS.join('|')})(?![\\w-]))`, 'g');
// Japanese and Korean counters: "1534件（うち無料412件）", "행사 12개, 무료 3개"
const JA_RE = /(\d+)件/g;
const JA_FREE_RE = /(無料|무료\s?)(\d+)(件|개)/g;
const KO_RE = /(행사\s?)(\d+)(개)/g;

function fmtLike(old, n) {
  // keep the page's own thousands separator
  const sep = (old.match(/[,.  ]/) || [''])[0];
  const s = String(n);
  return sep && n >= 1000 ? s.replace(/\B(?=(\d{3})+(?!\d))/g, sep) : s;
}
const toInt = (s) => parseInt(String(s).replace(/[^\d]/g, ''), 10);

// Rewrite event, free and paid counts in a piece of text. `only` limits changes to numbers
// that equal one of the given old values (used in page bodies, where it is safest). `base`
// holds the counts the page was built with; counters that are often used for subsets
// (Japanese 件, Korean 개) only change when they equal those.
const PAID_RE = /(^|[^\d.,:\/-])(\d+)(?= (?:are|is) (?:ticketed|paid))/g;
const FREE_HINT = /\b(?:free|kostenlos|gratis|gratuit|gratuites?|gratuitos?|gratuiti|ingyenes|maksuttom|bezpłatn|δωρεάν|tasuta|bezmaksas|nemokam|zadarmo|brezplačn|ókeypis)/i;
const PAID_HINT = /\b(?:tickets?|ticketed|paid|sign up ahead|book ahead|kostenpflichtig|payant|payantes?|de pago|a pagamento|pagos)/i;
export function rewriteCounts(text, N, F, only, base) {
  if (!text || !/\d/.test(text)) return text;
  const P = N - F;
  const ok = (v, kind) => !only || only[kind].has(v);
  let t = text.replace(OF_RE, (all, pre, a, mid, b, off, str) => {
    const va = toInt(a), vb = toInt(b);
    if (!ok(vb, 'e')) return all;
    const rest = str.slice(off + all.length, off + all.length + 160).split(/[.!?。]/)[0];
    const lead = str.slice(Math.max(0, off - 60), off);
    let x = a;
    const paid = PAID_HINT.test(rest) || (!FREE_HINT.test(rest) && PAID_HINT.test(lead));
    const free = !paid && (FREE_HINT.test(rest) || FREE_HINT.test(lead));
    if (paid) x = only && !only.p.has(va) ? a : fmtLike(a, P);
    else if (free) x = ok(va, 'f') ? fmtLike(a, F) : a;
    return pre + x + mid + fmtLike(b, N);
  });
  t = t.replace(PAID_RE, (all, pre, n) => (!only || only.p.has(toInt(n)) ? pre + fmtLike(n, P) : all));
  t = t.replace(F_RE, (all, pre, n) => (ok(toInt(n), 'f') ? pre + fmtLike(n, F) : all));
  t = t.replace(FB_RE, (all, pre, n) => (ok(toInt(n), 'f') ? pre + fmtLike(n, F) : all));
  t = t.replace(THEM_RE, (all, pre, n) => (ok(toInt(n), 'f') ? pre + fmtLike(n, F) : all));
  t = t.replace(FOUND_RE, (all, a, n, b) => (ok(toInt(n), 'e') ? a + fmtLike(n, N) + b : all));
  t = t.replace(ARE_FREE_RE, (all, pre, n, off, str) => {
    if (/\b(?:of|von|de|sur|van|di) (?:the )?$/.test(str.slice(Math.max(0, off - 8), off + pre.length))) return all;
    return ok(toInt(n), 'f') ? pre + fmtLike(n, F) : all;
  });
  t = t.replace(E_RE, (all, pre, n) => (ok(toInt(n), 'e') ? pre + fmtLike(n, N) : all));
  if (base) {
    t = t.replace(JA_FREE_RE, (all, a, n, b) => (toInt(n) === base.f ? a + F + b : all));
    t = t.replace(/(\d+)(件が無料)/g, (all, n, b) => (toInt(n) === base.f ? F + b : all));
    t = t.replace(KO_RE, (all, a, n, b) => (toInt(n) === base.e ? a + N + b : all));
    t = t.replace(JA_RE, (all, n, off, str) => (str.slice(Math.max(0, off - 3), off).includes('無料') || toInt(n) !== base.e ? all : N + '件'));
  }
  return t === text ? t : englishGrammar(t);
}

// After a count changes, keep English sentences grammatical ("1 event", "none of them free").
function englishGrammar(t) {
  return t
    .replace(/\b1 ((?:(?:confirmed|verified|family|Christmas|holiday|kids|free) )*)events\b/g, '1 $1event')
    .replace(/\b1 ((?:(?:Christmas|Holiday) )*)Events\b/g, '1 $1Event')
    .replace(/\b1 of them are free\b/g, '1 of them is free')
    .replace(/\b([2-9]|\d{2,}) of them is free\b/g, '$1 of them are free')
    .replace(/, 0 of them free\b/g, ', none of them free')
    .replace(/\band 0 of them (?:are|is) free\b/g, 'and none of them are free')
    .replace(/\b0 free events?\b/g, 'no free events')
    .replace(/\bAll 1 events\b/g, '1 event')
    .replace(/(^|[.!?] )0 of the (\d+)/g, '$1None of the $2')
    // singular in the other main languages
    .replace(/\b1 planes\b/g, '1 plan').replace(/\b1 activités\b/g, '1 activité').replace(/\b1 sorties\b/g, '1 sortie')
    .replace(/\b1 Ausflugstipps\b/g, '1 Ausflugstipp').replace(/\b1 Tipps\b/g, '1 Tipp').replace(/\b1 Veranstaltungen\b/g, '1 Veranstaltung')
    .replace(/\b1 geprüfte Tipps\b/g, '1 geprüfter Tipp').replace(/\b1 uitjes\b/g, '1 uitje').replace(/\b1 uitstappen\b/g, '1 uitstap')
    .replace(/\b1 eventi\b/g, '1 evento').replace(/\b1 programas\b/g, '1 programa').replace(/\b1 atividades\b/g, '1 atividade')
    .replace(/\b1 eventos\b/g, '1 evento').replace(/\b1 gratuitos\b/g, '1 gratuito').replace(/\b1 gratuitas\b/g, '1 gratuita').replace(/\b1 gratuites\b/g, '1 gratuite').replace(/\b1 gratuiti\b/g, '1 gratuito').replace(/\b1 actividades\b/g, '1 actividad');
}

// Numbers a text claims as event and free counts (for finding stale values).
export function claimedCounts(text) {
  const e = new Set(), f = new Set();
  if (!text) return { e, f };
  for (const m of text.matchAll(OF_RE)) e.add(toInt(m[4]));
  for (const m of text.matchAll(F_RE)) f.add(toInt(m[2]));
  for (const m of text.matchAll(FB_RE)) f.add(toInt(m[2]));
  for (const m of text.matchAll(ARE_FREE_RE)) {
    if (/\b(?:of|von|de|sur|van|di) (?:the )?$/.test(text.slice(Math.max(0, m.index - 8), m.index + m[1].length))) continue;
    f.add(toInt(m[2]));
  }
  for (const m of text.matchAll(THEM_RE)) f.add(toInt(m[2]));
  for (const m of text.matchAll(FOUND_RE)) e.add(toInt(m[2]));
  for (const m of text.matchAll(E_RE)) e.add(toInt(m[2]));
  return { e, f };
}

// Links to another city's page carry that city's own counts ("Aurora, CO · 26 events").
function healCityLinks(html, pages, self, mask) {
  return html.replace(/<a href="(\/christmas-events\/[a-z0-9-]+)"([^>]*)>([\s\S]*?)<\/a>/g, (all, p, attrs, inner) => {
    if (p === self || !/\d/.test(inner)) return all;
    const c = pages && pages[p];
    return mask(c && c[0] ? `<a href="${p}"${attrs}>${rewriteCounts(inner, c[0], c[1])}</a>` : all);
  });
}

// ---------------------------------------------------------------------------- city pages
const CARD_RE = /<section class="rtt-pe-ride(?: [^"]*)?"([^>]*)>/g;
function lastDay(tag) {
  const m = tag.match(/data-cal="([^"]*)"/);
  if (!m) return '';
  try {
    const c = JSON.parse(m[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&'));
    let best = '';
    for (const r of c.d || []) {
      const x = r[3] || r[0] || '';
      if (x > best) best = x;
    }
    return best;
  } catch (e) {
    return '';
  }
}
function attrOf(tag, name) {
  const m = tag.match(new RegExp(`\\b${name}="([^"]*)"`));
  return m ? m[1] : '';
}
// End of the <section> that starts at i (cards contain no nested sections, but count anyway).
function sectionEnd(html, i) {
  const re = /<section\b|<\/section>/g;
  re.lastIndex = i + 1;
  let depth = 1, m;
  while ((m = re.exec(html))) {
    depth += m[0] === '</section>' ? -1 : 1;
    if (!depth) return m.index + 10;
  }
  return -1;
}

export function healCity(html, today, pages, self) {
  if (!html.includes('class="rtt-pe-ride')) return null;
  const cards = [];
  for (const m of html.matchAll(CARD_RE)) {
    const tag = m[1];
    cards.push({ start: m.index, id: attrOf(tag, 'id'), last: lastDay(tag), fl: attrOf(tag, 'data-xf-fl').split(' '), ty: attrOf(tag, 'data-xf-ty').split(' ') });
  }
  if (!cards.length) return null;
  const N0 = cards.length, F0 = cards.filter((c) => c.fl.includes('free')).length;
  const past = cards.filter((c) => c.last && c.last < today);
  const live = cards.filter((c) => !(c.last && c.last < today));
  const N = live.length, F = live.filter((c) => c.fl.includes('free')).length;
  if (!N) return null; // everything has happened: the page's own script shows the end-of-season note

  const head = html.slice(0, html.indexOf('</head>') + 1);
  const claimed = claimedCounts(
    [...head.matchAll(/<title>([^<]*)<\/title>|<meta (?:name|property|itemprop)="(?:description|og:title|og:description|twitter:title|twitter:description|name)" content="([^"]*)"/g)]
      .map((m) => m[1] || m[2]).join(' | '),
  );
  const headStale = [...claimed.e].some((v) => v !== N) || [...claimed.f].some((v) => v !== F);
  let linksStale = false;
  if (pages) {
    for (const m of html.matchAll(/<a href="(\/christmas-events\/[a-z0-9-]+)"[^>]*>(?:(?!<\/a>)[\s\S]){0,300}?(\d+) events?</g)) {
      const c = pages[m[1]];
      if (m[1] !== self && c && c[0] && c[0] !== toInt(m[2])) { linksStale = true; break; }
    }
  }
  if (!past.length && N === N0 && F === F0 && !headStale && !linksStale) return null;

  // Old values the text may carry: what the cards said when the page was built, and what the head claims.
  const only = { e: new Set([N0, ...claimed.e]), f: new Set([F0, ...claimed.f]), p: new Set([N0 - F0]) };
  const base = { e: N0, f: F0 };
  let out = html;

  // 1. Remove events that have passed (back to front so indexes stay valid).
  const gone = new Set(past.map((c) => c.id));
  for (const c of [...past].sort((a, b) => b.start - a.start)) {
    const end = sectionEnd(out, c.start);
    if (end > 0) out = out.slice(0, c.start) + out.slice(end);
  }
  if (gone.size) {
    // links to removed cards in "top picks" and plan lists
    out = out.replace(/<li\b[^>]*>(?:(?!<\/?li\b)[\s\S]){0,1500}?href="#([^"]+)"[\s\S]{0,1500}?<\/li>/g, (li, id) => (gone.has(id) && !/<li\b/.test(li.slice(3)) ? '' : li));
  }

  // 2. Head: title, description and social cards say the live counts.
  out = out.replace(/<title>([^<]*)<\/title>/, (all, t) => `<title>${rewriteCounts(t, N, F, null, base)}</title>`);
  out = out.replace(/(<meta (?:name|property|itemprop)="(?:description|og:title|og:description|twitter:title|twitter:description|name)" content=")([^"]*)(")/g,
    (all, a, t, b) => a + rewriteCounts(t, N, F, null, base) + b);

  // 3. Structured data: drop past events, fix list sizes and count sentences.
  out = out.replace(/(<script type="application\/ld\+json">)([\s\S]*?)(<\/script>)/g, (all, a, body, b) => {
    let j;
    try { j = JSON.parse(body); } catch (e) { return all; }
    let g = j['@graph'] || [j];
    const drop = new Set();
    g = g.filter((x) => {
      if (x['@type'] !== 'Event') return true;
      const id = String(x['@id'] || ''), u = String(x.url || '');
      const key = 'ev-' + (id.split('#event-')[1] || '');
      const end = String(x.endDate || x.startDate || '').slice(0, 10);
      if (gone.has(key) || gone.has(u.split('#')[1]) || (end && end < today)) { drop.add(id); return false; }
      return true;
    });
    const fix = (o) => {
      if (Array.isArray(o)) return o.forEach(fix);
      if (!o || typeof o !== 'object') return;
      if (o['@type'] === 'ItemList' && Array.isArray(o.itemListElement)) {
        o.itemListElement = o.itemListElement.filter((e) => !(e.item && drop.has(e.item['@id'])));
        o.itemListElement.forEach((e, i) => { e.position = i + 1; });
        if ('numberOfItems' in o && o.numberOfItems === N0) o.numberOfItems = N;
        else if ('numberOfItems' in o) o.numberOfItems = o.itemListElement.length;
      }
      for (const k of ['name', 'description', 'headline', 'text']) if (typeof o[k] === 'string') o[k] = rewriteCounts(o[k], N, F, only, base);
      for (const v of Object.values(o)) if (v && typeof v === 'object') fix(v);
    };
    if (j['@graph']) { j['@graph'] = g; fix(j['@graph']); } else if (!g.length) return ''; else fix(j);
    return a + JSON.stringify(j).replace(/</g, '\\u003c') + b;
  });

  // 4. Filter bar, section headings and "more events" lines
  const has = (attr, v) => live.filter((c) => !v || c[attr].includes(v)).length;
  out = out.replace(/data-xf-total="\d+"/g, `data-xf-total="${N}"`);
  out = out.replace(/(<p class="rtt-xf__count"[^>]*>)([^<]*?)(\d+)([^<]*<\/p>)/g, (all, a, x, n, b) => englishGrammar(a + x + N + b));
  out = out.replace(/(<button[^>]*data-xf-type="([^"]*)"[^>]*>(?:(?!<\/button>)[\s\S])*?<b>)(\d+)(<\/b>)/g, (all, a, v, n, b) => a + has('ty', v) + b);
  out = out.replace(/(<(?:button|a)[^>]*data-xf-flag="([^"]*)"[^>]*>(?:(?!<\/(?:button|a)>)[\s\S])*?<b>)(\d+)(<\/b>)/g, (all, a, v, n, b) => a + has('fl', v) + b);
  out = out.replace(/(<h2[^>]*\bdata-n=")(\d+)("[^>]*>)/g, (all, a, n, b, off) => {
    // count the cards up to the next h2
    const rest = out.slice(off + all.length);
    const nxt = rest.search(/<h2\b[^>]*\bdata-n=/);
    const seg = nxt < 0 ? rest : rest.slice(0, nxt);
    return a + (seg.match(/<section class="rtt-pe-ride[" ]/g) || []).length + b;
  });
  const delta = N0 - N;
  if (delta > 0) {
    out = out.replace(/(<span class="rtt-ul__more"[^>]*>\+)(\d+)/g, (all, a, n) => a + Math.max(0, toInt(n) - delta));
    out = out.replace(/(<span class="rtt-ul__one"[^>]*>)(\d+)/g, (all, a, n) => a + Math.max(0, toInt(n) - delta));
  }

  // 5. Links to nearby cities carry their own counts; body sentences state this page's counts.
  const masks = [];
  if (pages) out = healCityLinks(out, pages, self, (x) => `\u0000${masks.push(x) - 1}\u0000`);
  const bodyAt = out.indexOf('</head>');
  const olds = [...new Set([...only.e, ...only.f, ...only.p])].map(String);
  const parts = out.slice(bodyAt).split(/(<script\b[\s\S]*?<\/script>|<style\b[\s\S]*?<\/style>)/);
  for (let i = 0; i < parts.length; i += 2) {
    if (!olds.some((v) => parts[i].includes(v))) continue;
    parts[i] = parts[i].replace(/>([^<>]*\d[^<>]*)</g, (all, t) => (olds.some((v) => t.includes(v)) ? '>' + rewriteCounts(t, N, F, only, base) + '<' : all));
  }
  out = out.slice(0, bodyAt) + parts.join('');
  out = out.replace(/\u0000(\d+)\u0000/g, (m0, i) => masks[+i]);
  return out === html ? null : out;
}

// ------------------------------------------------------------------ country and state guides
const CITY_WORDS = ['cities', 'Canadian cities', 'cities across', 'villes', 'Städten', 'Städte', 'ciudades', 'città', 'cidades', 'steden',
  'byer', 'städer', 'kaupungissa', 'kaupunkia', 'városban', 'városban', 'miastach', 'orașe', 'містах', 'πόλεις', 'gradova', 'linnas',
  'pilsētās', 'miestuose', 'mestách', 'mestih', 'bæjum', 'stöðum', 'towns and cities'];
const C_RE = new RegExp(`(^|[^\\d.,:/-])${NUM}(?=${SP}(?:${CITY_WORDS.join('|')})(?![\\w-]))`, 'g');
const JA_CITY_RE = /(\d+)(の都市)/g;

// Drop list items for events whose last day has passed (state pages list events this way).
function dropPastItems(html, today) {
  return html.replace(/<li\b([^>]*\bdata-cal="[^"]*"[^>]*)>[\s\S]*?<\/li>/g, (li, attrs) => {
    const last = lastDay(attrs);
    return last && last < today ? '' : li;
  });
}

export function healGuide(html, today, live, path) {
  const g = live && live.guides && live.guides[path];
  if (!g || !g.e) return null;
  const pages = live.pages || {};
  let out = dropPastItems(html, today);
  const items = (out.match(/\bdata-xf-ty="/g) || []).length; // events the page's filter shows
  const masks = [];
  const mask = (s) => `\u0000${masks.push(s) - 1}\u0000`;

  // 1. City sections (state pages: an h2 per city, then its next events) say that city's counts.
  out = out.replace(/<h2 id="city-[^"]*"[^>]*>[\s\S]*?(?=<h2\b|<\/article>|$)/g, (sec) => {
    const m = sec.match(/href="(\/christmas-events\/[a-z0-9-]+)(?:#[^"]*)?"/);
    const c = m && pages[m[1]];
    if (!c || !c[0]) return sec;
    return mask(healCityLinks(rewriteCounts(sec, c[0], c[1]), pages, path, (x) => x));
  });
  // Each city card says that city's own counts.
  out = out.replace(/<li class="rtt-rc">[\s\S]*?<\/li>/g, (li) => {
    const m = li.match(/href="(\/christmas-events\/[a-z0-9-]+)"/);
    const c = m && pages[m[1]];
    return mask(c && c[0] ? rewriteCounts(li, c[0], c[1]) : li);
  });
  out = healCityLinks(out, pages, path, mask);
  // 2. Structured data: city entries get city counts, the page gets the guide totals.
  out = out.replace(/(<script type="application\/ld\+json">)([\s\S]*?)(<\/script>)/g, (all, a, body, b) => {
    let j;
    try { j = JSON.parse(body); } catch (e) { return mask(all); }
    const walk = (o, E, F) => {
      if (Array.isArray(o)) return o.forEach((x) => walk(x, E, F));
      if (!o || typeof o !== 'object') return;
      const u = String(o.url || o['@id'] || '');
      const p = u.replace('https://www.rallytakesthetrain.com', '').split('#')[0];
      const c = pages[p];
      const [e, f] = c && c[0] && p !== path ? c : [E, F];
      for (const k of ['name', 'description', 'headline', 'text']) {
        if (typeof o[k] !== 'string') continue;
        let s = rewriteCounts(o[k], e, f);
        if (p === path || !c) s = s.replace(C_RE, (m0, pre, n) => pre + fmtLike(n, g.c));
        // "Christmas events for kids in Denver (36 events)"
        s = s.replace(/\((\d+) events?\)/, (m0, n) => `(${e} ${e === 1 ? 'event' : 'events'})`);
        o[k] = s;
      }
      for (const v of Object.values(o)) if (v && typeof v === 'object') walk(v, e, f);
    };
    const before = JSON.stringify(j);
    walk(j, g.e, g.f);
    const after = JSON.stringify(j);
    return mask(after === before ? all : a + after.replace(/</g, '\\u003c') + b);
  });
  // The filter's own line counts the events the filter shows on this page.
  if (items) {
    out = out.replace(/data-xf-total="\d+"/g, `data-xf-total="${items}"`);
    out = out.replace(/(<p class="rtt-xf__count"[^>]*>)([^<]*?)(\d+)([^<]*<\/p>)/g, (all, a, x, n, b) => mask(a + x + items + b));
  }
  // Scripts and styles are never touched.
  out = out.replace(/<script\b[\s\S]*?<\/script>|<style\b[\s\S]*?<\/style>/g, mask);

  // 3. Everything else on the page quotes the guide's totals.
  const fixText = (t) => rewriteCounts(t, g.e, g.f).replace(C_RE, (m0, pre, n) => pre + fmtLike(n, g.c)).replace(JA_CITY_RE, (m0, n, b) => g.c + b);
  out = out.replace(/<title>([^<]*)<\/title>/, (all, t) => `<title>${fixText(t)}</title>`);
  out = out.replace(/(<meta (?:name|property|itemprop)="(?:description|og:title|og:description|twitter:title|twitter:description|name)" content=")([^"]*)(")/g,
    (all, a, t, b) => a + fixText(t) + b);
  const bodyAt = out.indexOf('</head>');
  out = out.slice(0, bodyAt) + out.slice(bodyAt).replace(/>([^<>]*\d[^<>]*)</g, (all, t) => '>' + fixText(t) + '<');
  out = out.replace(/\u0000(\d+)\u0000/g, (m0, i) => masks[+i]);
  return out === html ? null : out;
}
