// Germany hub count sync. ST = {slug:{N,F,start,end,name}} from live city pages.
// HS.de(html), HS.en(html), HS.glob(html) return {html, log}. Pure string transforms.
var HS = {};
HS.MO = ['Januar','Februar','März','April','Mai','Juni','Juli','August','September','Oktober','November','Dezember'];
HS.dd = s => +s.slice(8, 10) + '. ' + HS.MO[+s.slice(5, 7) - 1];
HS.ME = ['January','February','March','April','May','June','July','August','September','October','November','December'];
HS.de_ = s => HS.ME[+s.slice(5, 7) - 1] + ' ' + (+s.slice(8, 10));
HS.TODAY = '2026-11-17';
HS.fmtN = n => n >= 1000 ? String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '.') : String(n);
HS.fmtNen = n => n >= 1000 ? String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',') : String(n);
HS.dates = (h) => h.replace(/"datePublished":"[^"]*"/g, '"datePublished":"' + HS.TODAY + 'T09:00:00-08:00"').replace(/"dateModified":"[^"]*"/g, '"dateModified":"' + HS.TODAY + 'T09:00:00-08:00"');
HS.tiles = (h) => {
  const a = h.indexOf('<ul class="rtt-rcs"'); const e = h.indexOf('</ul>', a);
  const inner = h.slice(h.indexOf('>', a) + 1, e);
  const tiles = inner.match(/<li class="rtt-rc">[\s\S]*?<\/li>/g) || [];
  return { a: h.indexOf('>', a) + 1, e, tiles };
};
HS.slugOf = t => (t.match(/href="\/christmas-events\/([^"]+)"/) || [])[1];
HS.de = (h, ST) => {
  const log = []; const T = HS.tiles(h); const have = new Set(T.tiles.map(HS.slugOf));
  let tiles = T.tiles.slice();
  for (const [s, v] of Object.entries(ST)) if (v.lang === 'de' && v.N > 0 && !have.has(s) && v.name) {
    tiles.push('<li class="rtt-rc"><h3 class="rtt-rc__h"><a href="/christmas-events/' + s + '">Weihnachten mit Kindern in ' + v.name + '</a></h3><p class="rtt-rc__meta"></p><p class="rtt-rc__hook"></p></li>'); log.push('add ' + s);
  }
  const rows = [];
  tiles.forEach((t, i) => {
    const s = HS.slugOf(t), v = ST[s]; if (!v) { log.push('nostats ' + s); rows.push({ t, N: -1, i, s }); return; }
    const C = (t.match(/Weihnachten mit Kindern in ([^<]+)<\/a>/) || [])[1];
    const { N, F } = v;
    const meta = N + (N === 1 ? ' Veranstaltung' : ' Veranstaltungen') + (F === 0 ? '' : F === N ? ' &middot; alle kostenlos' : ' &middot; ' + F + ' kostenlos');
    let hook = 'Für die Saison 2026 haben wir ' + (N === 1 ? 'eine Weihnachtsveranstaltung' : N + ' Weihnachtsveranstaltungen') + ' für Kinder in ' + C + ' geprüft';
    if (v.start) hook += v.start === v.end ? ', am ' + HS.dd(v.start) : ', vom ' + HS.dd(v.start) + ' bis ' + HS.dd(v.end);
    hook += '.' + (F === 0 ? '' : F === N ? (N === 1 ? ' Sie ist kostenlos.' : ' Alle sind kostenlos.') : F === 1 ? ' Eine davon ist kostenlos.' : ' Davon sind ' + F + ' kostenlos.');
    const nt = t.replace(/<p class="rtt-rc__meta">[\s\S]*?<\/p>/, '<p class="rtt-rc__meta">' + meta + '</p>').replace(/<p class="rtt-rc__hook">[\s\S]*?<\/p>/, '<p class="rtt-rc__hook">' + hook + '</p>');
    if (nt !== t) log.push(s + ' ' + N + '/' + F);
    rows.push({ t: nt, N, F, i, s, C });
  });
  rows.sort((x, y) => (y.N - x.N) || (x.i - y.i));
  let out = h.slice(0, T.a) + rows.map(r => r.t).join('') + h.slice(T.e);
  const live = rows.filter(r => r.N > 0); const TN = live.reduce((a, r) => a + r.N, 0), TF = live.reduce((a, r) => a + r.F, 0), TC = live.length;
  out = out.replace(/(haben wir )[\d.]+( Weihnachtsveranstaltungen für Kinder in )\d+( Städten geprüft)/, '$1' + HS.fmtN(TN) + '$2' + TC + '$3')
    .replace(/(Weihnachten mit Kindern in Deutschland 2026: )[\d.]+( Tipps)/g, '$1' + HS.fmtN(TN) + '$2')
    .replace(/(Weihnachten mit Kindern in Deutschland: )[\d.]+( geprüfte Tipps in )\d+( Städten, )[\d.]+( kostenlos)/g, '$1' + HS.fmtN(TN) + '$2' + TC + '$3' + HS.fmtN(TF) + '$4');
  // ItemList in tile order
  out = out.replace(/("@id":"https:\/\/www\.rallytakesthetrain\.com\/christmas-events\/weihnachten-mit-kindern-deutschland#cities","numberOfItems":)\d+,"itemListElement":\[[\s\S]*?\]\}/, (m, p) =>
    p + rows.length + ',"itemListElement":[' + rows.map((r, k) => '{"@type":"ListItem","position":' + (k + 1) + ',"name":"Weihnachten mit Kindern in ' + r.C + ' (2026)","url":"https://www.rallytakesthetrain.com/christmas-events/' + r.s + '"}').join(',') + ']}');
  out = HS.dates(out);
  return { html: out, log, TN, TF, TC };
};
HS.en = (h, ST) => {
  const log = []; const T = HS.tiles(h); const rows = [];
  T.tiles.forEach((t, i) => {
    const s = HS.slugOf(t), v = ST[s]; if (!v) { log.push('nostats ' + s); rows.push({ t, N: -1, F: 0, i }); return; }
    const { N, F } = v;
    let nt = t.replace(/<p class="rtt-rc__meta">[\s\S]*?<\/p>/, '<p class="rtt-rc__meta">' + N + (N === 1 ? ' event' : ' events') + (F === 0 ? '' : F === N ? ' &middot; all free' : ' &middot; ' + F + ' free') + '</p>')
      .replace(/(we confirmed )\d+( Christmas events? for kids)/, '$1' + N + '$2')
      .replace(/running from [A-Z][a-z]+ \d+ to [A-Z][a-z]+ \d+/, x => v.start ? (v.start === v.end ? 'on ' + HS.de_(v.start) : 'running from ' + HS.de_(v.start) + ' to ' + HS.de_(v.end)) : x)
      .replace(/Of these, (\d+|all) (?:are|is) free\./, F === N ? 'All of them are free.' : F === 1 ? 'One of them is free.' : 'Of these, ' + F + ' are free.');
    if (F === 0) nt = nt.replace(/ (?:Of these, \d+ are free|One of them is free|All of them are free)\./, '');
    if (nt !== t) log.push(s + ' ' + N + '/' + F);
    rows.push({ t: nt, N, F, i, s });
  });
  rows.sort((x, y) => (y.N - x.N) || (x.i - y.i));
  let out = h.slice(0, T.a) + rows.map(r => r.t).join('') + h.slice(T.e);
  const live = rows.filter(r => r.N > 0); const TN = live.reduce((a, r) => a + r.N, 0), TF = live.reduce((a, r) => a + r.F, 0), TC = live.length;
  out = out.replace(/(We found )[\d,]+( confirmed Christmas events for kids in )\d+( cities across Germany)/, '$1' + HS.fmtNen(TN) + '$2' + TC + '$3')
    .replace(/(Christmas events for kids in Germany for 2026: )[\d,]+( family events in )\d+( cities, )[\d,]+( free)/g, '$1' + HS.fmtNen(TN) + '$2' + TC + '$3' + HS.fmtNen(TF) + '$4');
  // reorder ItemList by tile order
  const m = out.match(/("@id":"https:\/\/www\.rallytakesthetrain\.com\/christmas-events\/christmas-in-germany-with-kids#cities","numberOfItems":\d+,"itemListElement":)(\[[\s\S]*?\])\}/);
  if (m) { const L = JSON.parse(m[2]); const by = {}; L.forEach(x => by[x.url.split('/').pop()] = x);
    const NL = rows.map((r, k) => Object.assign({}, by[r.s], { position: k + 1 })).filter(x => x.url);
    if (NL.length === L.length) out = out.replace(m[0], m[1] + JSON.stringify(NL) + '}'); else log.push('itemlist mismatch'); }
  out = HS.dates(out);
  return { html: out, log, TN, TF, TC };
};
HS.glob = (h, ST) => {
  const log = []; const a = h.indexOf('<script type="application/json" id="xn-data">'); if (a < 0) return { html: h, log: ['no xn-data'] };
  const s0 = h.indexOf('>', a) + 1, e = h.indexOf('</script>', s0); const D = JSON.parse(h.slice(s0, e));
  let withEv = 0, cities = 0; const DI = D.c.findIndex(c => c[0] === 'DE');
  for (const p of D.p) { if (p[3] !== DI) continue; const langs = String(p[6] || '').split(','); const de = langs.map(x => x.split(':')).find(x => x[0] === 'de' && /^weihnachten-mit-kindern-/.test(x[1]));
    if (!de) continue; const v = ST[de[1]]; cities++;
    if (v && v.N !== p[5]) { log.push(de[1] + ' ' + p[5] + '->' + v.N); p[5] = v.N; }
    if (p[5] > 0) withEv++; }
  const row = D.c.find(c => c[0] === 'DE');
  if (row && row[6] !== withEv) { log.push('DE with events ' + row[6] + '->' + withEv); row[6] = withEv; }
  let out = h.slice(0, s0) + JSON.stringify(D) + h.slice(e);
  out = out.replace(/("description":"\d+ city guides, )\d+( with confirmed 2026 events"\}\},\{"@type":"ListItem")/, (m0, p1, p2) => m0);
  out = out.replace(/(christmas-in-germany-with-kids","name":"Christmas events for kids in Germany","about":\{"@id":"#c-de"\},"description":"\d+ city guides, )\d+( with confirmed 2026 events)/, '$1' + withEv + '$2');
  return { html: out, log, cities, withEv };
};
if (typeof module !== 'undefined') module.exports = HS;
