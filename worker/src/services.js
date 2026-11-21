// Christmas Eve services counts (tools/services/live_services.json, rebuilt every 3 hours by
// tools/services/build_services.py from the live pages themselves).
//
// The hub (/christmas-eve-services-near-me) and the country, state, region and denomination
// guides carry church and city counts that were written when each page was built. City pages
// keep being added and filled by the builders, so those numbers fall behind. These healers put
// the current numbers into the served HTML: the hub's totals, its finder data (xn-data), its
// region rows, and each guide's headline sentences and per-city chips. City pages count their
// own cards when they are built, so they are left alone.

export const SERVICES_HUB = '/christmas-eve-services-near-me';
export const SERVICE_COLLECTIONS = [
  'christmas-eve-services', 'christmas-eve-services-canada', 'christmas-eve-services-uk', 'christmas-eve-services-australia',
  'christmas-eve-services-in-ireland', 'christmas-eve-reihai-japan', 'gottesdienste-heiligabend-deutschland',
  'misa-de-nochebuena-mexico', 'pasterka-wigilia-polska', 'slujbe-de-craciun-romania', 'misa-del-gallo-espana',
  'messes-de-noel-france', 'missa-do-galo-brasil', 'messes-de-noel-quebec-canada', 'messe-vigilia-di-natale-italia',
];

export function isServicesPath(path) {
  if (path === SERVICES_HUB) return true;
  const c = path.split('/')[1];
  return SERVICE_COLLECTIONS.includes(c);
}

export function servicesHealerFor(path, sv) {
  if (!sv || !sv.total) return null;
  if (path === SERVICES_HUB) return 'svhub';
  if (sv.guides && sv.guides[path]) return 'svguide';
  return null;
}

const toInt = (s) => parseInt(String(s).replace(/[^\d]/g, ''), 10);
// thousands separator: the page's own when the old number shows one, else the collection's language
const DOT = /^\/(?:gottesdienste|misa-|pasterka|slujbe|missa-|messe-vigilia)/;
const SPACE = /^\/messes-de-noel/;
let SEP = ',';
export function sepFor(path) { return DOT.test(path || '') ? '.' : SPACE.test(path || '') ? '\u202f' : ','; }
function fmtLike(old, n) {
  const s = String(n);
  if (n < 1000) return s;
  const sep = (String(old).match(/[,.  ]/) || [''])[0] || SEP;
  return s.replace(/\B(?=(\d{3})+(?!\d))/g, sep);
}
const N = '(\\d{1,3}(?:[,.  ]\\d{3})+|\\d+)';

// "en:bridgeport-ct" / "en:/christmas-eve-services-uk/aberdeen-uk" / "/x/y" / "alabama" -> site path
export function slugPath(s) {
  s = String(s || '').trim();
  if (!s) return '';
  s = s.includes(':') && !s.startsWith('/') ? s.slice(s.indexOf(':') + 1) : s;
  return s.startsWith('/') ? s.replace(/\/$/, '') : '/christmas-eve-services/' + s;
}

function hubCountries(html) {
  const m = html.match(/<script type="application\/json" id="xn-data">([\s\S]*?)<\/script>/);
  try { return (JSON.parse(m[1]).c || []).map((c) => ({ name: c[1], guide: c[4] })); } catch (e) { return []; }
}

// ---- hub -------------------------------------------------------------------------------
export function healServicesHub(html, sv) {
  SEP = ',';
  const T = sv.total, G = sv.guides || {}, C = sv.cities || {};
  let out = html;

  // 1) finder data
  out = out.replace(/(<script type="application\/json" id="xn-data">)([\s\S]*?)(<\/script>)/, (all, a, body, b) => {
    let D;
    try { D = JSON.parse(body); } catch (e) { return all; }
    for (const c of D.c || []) {
      const g = G[slugPath(c[4])];
      if (g) { c[5] = g.cities; c[6] = g.cw; }
    }
    for (const cc of Object.keys(D.r || {})) {
      for (const row of (D.r[cc] || [])[1] || []) {
        const g = G[slugPath(row[2])];
        if (g) { row[3] = g.churches; row[4] = g.cities; }
      }
    }
    for (const p of D.p || []) {
      let best = -1;
      for (const s of String(p[6] || '').split(',')) {
        const x = C[slugPath(s)];
        if (x && x[0] > best) best = x[0];
      }
      if (best >= 0) p[5] = best;
    }
    return a + JSON.stringify(D).replace(/</g, '\\u003c') + b;
  });

  // keep the finder data out of the text edits below
  const m = out.match(/<script type="application\/json" id="xn-data">[\s\S]*?<\/script>/);
  const keep = m ? m[0] : '';
  let t = m ? out.replace(keep, '\u0000XN\u0000') : out;

  // 2) region / country rows: <a class="xn-row" href="GUIDE">…, 15 cities, 43 churches</span></a></span><span …>15 cities<svg
  t = t.replace(new RegExp('(<a class="xn-row" href="([^"]+)"[^>]*>[\\s\\S]{0,400}?<span class="rtt-sr">, )' + N + '( cit(?:y|ies), )' + N + '( churche?s?</span>[\\s\\S]{0,200}?aria-hidden="true">)' + N + '( cit(?:y|ies))', 'g'),
    (all, a, href, c1, b, ch, d, c2, e) => {
      const g = G[href.replace(/\/$/, '')];
      if (!g) return all;
      return a + fmtLike(c1, g.cities) + b.replace(/cit(?:y|ies)/, g.cities === 1 ? 'city' : 'cities') + fmtLike(ch, g.churches) + d.replace(/churche?s?/, g.churches === 1 ? 'church' : 'churches') + fmtLike(c2, g.cities) + e.replace(/cit(?:y|ies)/, g.cities === 1 ? 'city' : 'cities');
    });
  // A-to-Z: <summary>… in Connecticut<span>15 cities</span></summary><div class="xn-az__in"><p class="xn-az__st"><a href="GUIDE">
  t = t.replace(new RegExp('(<summary>[^<]*<span>)' + N + '( cit(?:y|ies)</span></summary><div class="xn-az__in"><p class="xn-az__st"><a href="([^"]+)")', 'g'),
    (all, a, n, b, href) => { const g = G[href.replace(/\/$/, '')]; return g ? a + fmtLike(n, g.cities) + b.replace(/cit(?:y|ies)/, g.cities === 1 ? 'city' : 'cities') : all; });

  // 3) totals in prose, stat block, map, FAQ and LD description
  const ch = T.churches, ci = T.cities, cw = T.cw, tm = T.timed;
  const rep = (re, f) => { t = t.replace(re, f); };
  // per country: "Yes. 431 churches in 33 cities in Australia are listed"
  const byName = {};
  for (const c of hubCountries(out)) byName[c.name] = G[slugPath(c.guide)];
  rep(new RegExp(N + '( churches in )' + N + '( cities in )([A-Z][^<.,;]*?)( are listed)', 'g'), (all, a, b, c, d, name, e) => {
    const g = byName[name];
    return g ? fmtLike(a, g.churches) + b + fmtLike(c, g.cities) + d + name + e : all;
  });
  // site-wide: "4,134 churches in 1,312 cities across 13 countries" and the description "… cities in the United States, …"
  rep(new RegExp(N + '( churches in )' + N + '( cities(?: across| in the United States))', 'g'), (all, a, b, c, d) => fmtLike(a, ch) + b + fmtLike(c, ci) + d);
  rep(new RegExp('(<b>)' + N + '(</b>\\s*cities)', 'g'), (all, a, n, b) => a + fmtLike(n, ci) + b);
  rep(new RegExp('(<b>)' + N + '(</b>\\s*churches)', 'g'), (all, a, n, b) => a + fmtLike(n, ch) + b);
  rep(new RegExp(N + '( cities in \\d+ countries)', 'g'), (all, n, b) => fmtLike(n, ci) + b);
  rep(new RegExp(N + '( Christmas Eve lights)', 'g'), (all, n, b) => fmtLike(n, ci) + b);
  rep(new RegExp('(each of the )' + N + '( cities)', 'g'), (all, a, n, b) => a + fmtLike(n, ci) + b);
  rep(new RegExp(N + '( cities with Christmas Eve services listed)', 'g'), (all, n, b) => fmtLike(n, ci) + b);
  rep(new RegExp('(All )' + N + '( cities)', 'g'), (all, a, n, b) => a + fmtLike(n, ci) + b);
  rep(new RegExp(N + '( with 2026 service times)', 'g'), (all, n, b) => fmtLike(n, cw) + b);
  rep(new RegExp(N + '( of our )' + N + '( cities)', 'g'), (all, a, b, c, d) => fmtLike(a, cw) + b + fmtLike(c, ci) + d);
  rep(new RegExp(N + '( churches have posted)', 'g'), (all, n, b) => fmtLike(n, tm) + b);

  out = m ? t.replace('\u0000XN\u0000', () => keep) : t;
  return out === html ? null : out;
}

// ---- guides ----------------------------------------------------------------------------
const CHURCH = '(?:churches|church|Kirchen|Kirche|églises|église|iglesias|iglesia|igrejas|igreja|chiese|chiesa|kościołów|kościoły|kościół|kościele|parafii|parafie|biserici|biserică|教会)';
const CITY = '(?:cities|city|towns|Städten|Stadt|Orten|Ort|villes|ville|ciudades|ciudad|cidades|cidade|città|miastach|miast|miasta|mieście|orașe|oraș|localități|都市|市区町村)';
const QUAL = '(?:\\s+[A-Za-zÀ-ÿĀ-žА-я\'-]+){0,2}';
const PAIR = new RegExp(N + '(' + QUAL + '\\s*' + CHURCH + '[^<>.。\\d]{0,40}?)' + N + '(\\s*' + CITY + ')(?![A-Za-zÀ-ÿ])', 'g');
const TIMED = new RegExp(N + '((?: of them)? (?:have|has) (?:confirmed|posted) (?:their )?2026)', 'g');
const ROW = new RegExp('(<a href="([^"]+)"[^>]*>)([^<]*</a>\\s*</th>\\s*<td>)' + N + '(</td>\\s*<td>)' + N + '(</td>)', 'g');
const CHIP = new RegExp('(<a href="([^"]+)"[^>]*><b>[^<]*</b><span>)' + N + '(\\s*' + CHURCH + ')(</span>)', 'g');

const SING = { churches: 'church', Kirchen: 'Kirche', 'églises': 'église', iglesias: 'iglesia', igrejas: 'igreja', chiese: 'chiesa', biserici: 'biserică' };
const PLUR = Object.fromEntries(Object.entries(SING).map(([a, b]) => [b, a]));
function agree(n, w) {   // " churches" after the new number
  return w.replace(/[A-Za-zÀ-ÿăâîșțĂÂÎȘȚ]+$/, (word) => (n === 1 ? SING[word] || word : PLUR[word] || word));
}

export function healServicesGuide(html, sv, path) {
  const g = sv.guides[path];
  if (!g) return null;
  SEP = sepFor(path);
  const C = sv.cities || {}, D = sv.denoms || {};
  const isDenom = !!g.denom;
  // split off scripts that are not JSON-LD so their numbers are never touched
  const parts = html.split(/(<script(?![^>]*ld\+json)[^>]*>[\s\S]*?<\/script>|<style[^>]*>[\s\S]*?<\/style>)/);
  for (let i = 0; i < parts.length; i += 2) {
    let t = parts[i];
    if (!/\d/.test(t)) continue;
    // per-city chips first (their "N churches" must not be read as the total)
    const rowOf = (href) => {
      const u = href.replace(/^https?:\/\/[^/]+/, '');
      const p = u.split('#')[0].replace(/\/$/, '');
      const frag = (u.split('#')[1] || '').replace(/^t-/, '');
      if (frag) {   // "#t-anglican": that tradition's churches in the city
        const x = C[p] && C[p][2] && C[p][2][frag];
        if (x) return x;
        return isDenom ? (g.rows || {})[p] || null : null;
      }
      if (isDenom) return (g.rows || {})[p] || null;
      if (D[p]) return D[p];
      return C[p] || null;
    };
    t = t.replace(CHIP, (all, a, href, n, w, b) => {
      const v = rowOf(href);
      return v ? a + fmtLike(n, v[0]) + agree(v[0], w) + b : all;
    });
    // city-by-city table: <a href="CITY#t-x">City</a></th><td>churches</td><td>with 2026 times</td>
    t = t.replace(ROW, (all, a, href, mid, n, b, m, c) => {
      const v = rowOf(href);
      return v ? a + mid + fmtLike(n, v[0]) + b + fmtLike(m, v[1]) + c : all;
    });
    t = t.replace(PAIR, (all, a, mid, b, c, off, str) => {
      // skip "N churches in <City>" chips that slipped through: only rewrite pairs that equal or exceed one chip's scale
      return fmtLike(a, g.churches) + mid + fmtLike(b, g.cities) + c;
    });
    t = t.replace(TIMED, (all, n, rest) => fmtLike(n, g.timed) + rest);
    parts[i] = t;
  }
  const out = parts.join('');
  return out === html ? null : out;
}

export function runServicesHealer(kind, html, sv, path) {
  if (kind === 'svhub') return healServicesHub(html, sv);
  if (kind === 'svguide') return healServicesGuide(html, sv, path);
  return null;
}
