var RTTSync = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // src/sqsp.js
  var sqsp_exports = {};
  __export(sqsp_exports, {
    backups: () => backups,
    describe: () => describe,
    htmlBlocks: () => htmlBlocks,
    kindFor: () => kindFor,
    planItem: () => planItem,
    restore: () => restore,
    run: () => run
  });

  // src/heal.js
  function refToday(now = Date.now()) {
    return new Date(now - 12 * 3600 * 1e3).toISOString().slice(0, 10);
  }
  var EVENT_WORDS = [
    "events?",
    "Events?",
    "Christmas events?",
    "family events?",
    "kids events?",
    "kids Christmas events?",
    "confirmed events?",
    "activit\xE9s?",
    "sorties",
    "Veranstaltungen",
    "Tipps",
    "gepr\xFCfte Tipps",
    "Ausflugstipps",
    "Termine",
    "uitjes",
    "uitstappen",
    "activiteiten",
    "planes",
    "eventos",
    "actividades",
    "eventi",
    "programas",
    "programmi",
    "atividades",
    "juleaktiviteter",
    "aktiviteter",
    "julevenemang",
    "evenemang",
    "arrangementer",
    "joulutapahtumaa",
    "tapahtumaa",
    "kar\xE1csonyi programot?",
    "programot?",
    "programok",
    "wydarze\u0144",
    "wydarzenia",
    "imprez",
    "evenimente",
    "\u043F\u043E\u0434\u0456\u0457",
    "\u043F\u043E\u0434\u0456\u0439",
    "\u043F\u043E\u0434\u0456\u0457",
    "\u03B5\u03BA\u03B4\u03B7\u03BB\u03CE\u03C3\u03B5\u03B9\u03C2",
    "\u03B5\u03BA\u03B4\u03AE\u03BB\u03C9\u03C3\u03B7",
    "doga\u0111anja",
    "s\xFCndmust",
    "pas\u0101kumi",
    "rengini\u0173",
    "renginiai",
    "podujat\xED",
    "prireditev",
    "vi\xF0bur\xF0ir",
    "vi\xF0bur\xF0i"
  ];
  var FREE_AFTER = [
    "free",
    "Free",
    "kostenlos",
    "gratis",
    "gratuites?",
    "gratuits?",
    "gratuitos",
    "gratuitas",
    "gratuiti",
    "gratuite",
    "ingyenes",
    "maksuttomia",
    "bezp\u0142atnych",
    "bezp\u0142atne",
    "darmowych",
    "\u0431\u0435\u0437\u043A\u043E\u0448\u0442\u043E\u0432\u043D\u0438\u0445",
    "\u0431\u0435\u0437\u043A\u043E\u0448\u0442\u043E\u0432\u043D\u0456",
    "\u03B4\u03C9\u03C1\u03B5\u03AC\u03BD",
    "besplatnih",
    "tasuta",
    "bezmaksas",
    "nemokam\u0173",
    "zadarmo",
    "brezpla\u010Dnih",
    "\xF3keypis",
    "free events?"
  ];
  var SP = "[\\s\\u00a0\\u202f]+";
  var NUM = "(\\d{1,3}(?:[,.\\u00a0\\u202f]\\d{3})+|\\d+)";
  var ADJ = `(?:(?:confirmed|verified|family|Christmas|holiday|festive|kids|gepr\xFCfte|best\xE4tigte|weihnachtliche)${SP}){0,2}`;
  var E_RE = new RegExp(`(^|[^\\d.,:/-])${NUM}(?=${SP}${ADJ}(?:${EVENT_WORDS.join("|")})(?![\\w-]))`, "g");
  var F_RE = new RegExp(`(^|[^\\d.,:/-])${NUM}(?=${SP}(?:${FREE_AFTER.join("|")})(?![\\w-]))`, "g");
  var FOUND_RE = /(\b(?:We|we) found )(\d[\d,]*)( for kids)/g;
  var ARE_FREE_RE = /(^|[^\d.,:\/-])(\d+)(?= (?:are|is) free)/g;
  var THEM_RE = /(^|[^\d.,:\/-])(\d+)(?= of them (?:are |is )?free)/g;
  var OF_WORDS = "(?:of(?: the)?|von|de|sur|van|van de|di|av|af|z|din|\u03B1\u03C0\u03CC|od|i\u0161|\u0438\u0437|\u0437|af|af de)";
  var OF_RE = new RegExp(`(^|[^\\d.,:/-])(\\d+)(${SP}${OF_WORDS}${SP})(\\d+)(?=${SP}(?:are free|is free|${EVENT_WORDS.join("|")})(?![\\w-]))`, "g");
  var JA_RE = /(\d+)件/g;
  var JA_FREE_RE = /(無料|무료\s?)(\d+)(件|개)/g;
  var KO_RE = /(행사\s?)(\d+)(개)/g;
  function fmtLike(old, n) {
    const sep = (old.match(/[,.  ]/) || [""])[0];
    const s = String(n);
    return sep && n >= 1e3 ? s.replace(/\B(?=(\d{3})+(?!\d))/g, sep) : s;
  }
  var toInt = (s) => parseInt(String(s).replace(/[^\d]/g, ""), 10);
  var PAID_RE = /(^|[^\d.,:\/-])(\d+)(?= (?:are|is) (?:ticketed|paid))/g;
  var FREE_HINT = /\b(?:free|kostenlos|gratis|gratuit|gratuites?|gratuitos?|gratuiti|ingyenes|maksuttom|bezpłatn|δωρεάν|tasuta|bezmaksas|nemokam|zadarmo|brezplačn|ókeypis)/i;
  var PAID_HINT = /\b(?:tickets?|ticketed|paid|sign up ahead|book ahead|kostenpflichtig|payant|payantes?|de pago|a pagamento|pagos)/i;
  function rewriteCounts(text, N, F, only, base) {
    if (!text || !/\d/.test(text)) return text;
    const P = N - F;
    const ok = (v, kind) => !only || only[kind].has(v);
    let t = text.replace(OF_RE, (all, pre, a, mid, b, off, str) => {
      const va = toInt(a), vb = toInt(b);
      if (!ok(vb, "e")) return all;
      const rest = str.slice(off + all.length, off + all.length + 160).split(/[.!?。]/)[0];
      const lead = str.slice(Math.max(0, off - 60), off);
      let x = a;
      const paid = PAID_HINT.test(rest) || !FREE_HINT.test(rest) && PAID_HINT.test(lead);
      const free = !paid && (FREE_HINT.test(rest) || FREE_HINT.test(lead));
      if (paid) x = only && !only.p.has(va) ? a : fmtLike(a, P);
      else if (free) x = ok(va, "f") ? fmtLike(a, F) : a;
      return pre + x + mid + fmtLike(b, N);
    });
    t = t.replace(PAID_RE, (all, pre, n) => !only || only.p.has(toInt(n)) ? pre + fmtLike(n, P) : all);
    t = t.replace(F_RE, (all, pre, n) => ok(toInt(n), "f") ? pre + fmtLike(n, F) : all);
    t = t.replace(THEM_RE, (all, pre, n) => ok(toInt(n), "f") ? pre + fmtLike(n, F) : all);
    t = t.replace(FOUND_RE, (all, a, n, b) => ok(toInt(n), "e") ? a + fmtLike(n, N) + b : all);
    t = t.replace(ARE_FREE_RE, (all, pre, n, off, str) => {
      if (/\b(?:of|von|de|sur|van|di) (?:the )?$/.test(str.slice(Math.max(0, off - 8), off + pre.length))) return all;
      return ok(toInt(n), "f") ? pre + fmtLike(n, F) : all;
    });
    t = t.replace(E_RE, (all, pre, n) => ok(toInt(n), "e") ? pre + fmtLike(n, N) : all);
    if (base) {
      t = t.replace(JA_FREE_RE, (all, a, n, b) => toInt(n) === base.f ? a + F + b : all);
      t = t.replace(/(\d+)(件が無料)/g, (all, n, b) => toInt(n) === base.f ? F + b : all);
      t = t.replace(KO_RE, (all, a, n, b) => toInt(n) === base.e ? a + N + b : all);
      t = t.replace(JA_RE, (all, n, off, str) => str.slice(Math.max(0, off - 3), off).includes("\u7121\u6599") || toInt(n) !== base.e ? all : N + "\u4EF6");
    }
    return t === text ? t : englishGrammar(t);
  }
  function englishGrammar(t) {
    return t.replace(/\b1 ((?:(?:confirmed|verified|family|Christmas|holiday|kids|free) )*)events\b/g, "1 $1event").replace(/\b1 ((?:(?:Christmas|Holiday) )*)Events\b/g, "1 $1Event").replace(/\b1 of them are free\b/g, "1 of them is free").replace(/\b([2-9]|\d{2,}) of them is free\b/g, "$1 of them are free").replace(/, 0 of them free\b/g, ", none of them free").replace(/\band 0 of them (?:are|is) free\b/g, "and none of them are free").replace(/\b0 free events?\b/g, "no free events").replace(/\bAll 1 events\b/g, "1 event").replace(/(^|[.!?] )0 of the (\d+)/g, "$1None of the $2").replace(/\b1 planes\b/g, "1 plan").replace(/\b1 activités\b/g, "1 activit\xE9").replace(/\b1 sorties\b/g, "1 sortie").replace(/\b1 Ausflugstipps\b/g, "1 Ausflugstipp").replace(/\b1 Tipps\b/g, "1 Tipp").replace(/\b1 Veranstaltungen\b/g, "1 Veranstaltung").replace(/\b1 geprüfte Tipps\b/g, "1 gepr\xFCfter Tipp").replace(/\b1 uitjes\b/g, "1 uitje").replace(/\b1 uitstappen\b/g, "1 uitstap").replace(/\b1 eventi\b/g, "1 evento").replace(/\b1 programas\b/g, "1 programa").replace(/\b1 atividades\b/g, "1 atividade").replace(/\b1 eventos\b/g, "1 evento").replace(/\b1 actividades\b/g, "1 actividad");
  }
  function claimedCounts(text) {
    const e = /* @__PURE__ */ new Set(), f = /* @__PURE__ */ new Set();
    if (!text) return { e, f };
    for (const m of text.matchAll(OF_RE)) e.add(toInt(m[4]));
    for (const m of text.matchAll(F_RE)) f.add(toInt(m[2]));
    for (const m of text.matchAll(THEM_RE)) f.add(toInt(m[2]));
    for (const m of text.matchAll(FOUND_RE)) e.add(toInt(m[2]));
    for (const m of text.matchAll(E_RE)) e.add(toInt(m[2]));
    return { e, f };
  }
  function healCityLinks(html, pages, self, mask) {
    return html.replace(/<a href="(\/christmas-events\/[a-z0-9-]+)"([^>]*)>([\s\S]*?)<\/a>/g, (all, p, attrs, inner) => {
      if (p === self || !/\d/.test(inner)) return all;
      const c = pages && pages[p];
      return mask(c && c[0] ? `<a href="${p}"${attrs}>${rewriteCounts(inner, c[0], c[1])}</a>` : all);
    });
  }
  var CARD_RE = /<section class="rtt-pe-ride"([^>]*)>/g;
  function lastDay(tag) {
    const m = tag.match(/data-cal="([^"]*)"/);
    if (!m) return "";
    try {
      const c = JSON.parse(m[1].replace(/&quot;/g, '"').replace(/&amp;/g, "&"));
      let best = "";
      for (const r of c.d || []) {
        const x = r[3] || r[0] || "";
        if (x > best) best = x;
      }
      return best;
    } catch (e) {
      return "";
    }
  }
  function attrOf(tag, name) {
    const m = tag.match(new RegExp(`\\b${name}="([^"]*)"`));
    return m ? m[1] : "";
  }
  function sectionEnd(html, i) {
    const re = /<section\b|<\/section>/g;
    re.lastIndex = i + 1;
    let depth = 1, m;
    while (m = re.exec(html)) {
      depth += m[0] === "</section>" ? -1 : 1;
      if (!depth) return m.index + 10;
    }
    return -1;
  }
  function healCity(html, today, pages, self) {
    if (!html.includes('class="rtt-pe-ride"')) return null;
    const cards = [];
    for (const m of html.matchAll(CARD_RE)) {
      const tag = m[1];
      cards.push({ start: m.index, id: attrOf(tag, "id"), last: lastDay(tag), fl: attrOf(tag, "data-xf-fl").split(" "), ty: attrOf(tag, "data-xf-ty").split(" ") });
    }
    if (!cards.length) return null;
    const N0 = cards.length, F0 = cards.filter((c) => c.fl.includes("free")).length;
    const past = cards.filter((c) => c.last && c.last < today);
    const live = cards.filter((c) => !(c.last && c.last < today));
    const N = live.length, F = live.filter((c) => c.fl.includes("free")).length;
    if (!N) return null;
    const head = html.slice(0, html.indexOf("</head>") + 1);
    const claimed = claimedCounts(
      [...head.matchAll(/<title>([^<]*)<\/title>|<meta (?:name|property|itemprop)="(?:description|og:title|og:description|twitter:title|twitter:description|name)" content="([^"]*)"/g)].map((m) => m[1] || m[2]).join(" | ")
    );
    const headStale = [...claimed.e].some((v) => v !== N) || [...claimed.f].some((v) => v !== F);
    let linksStale = false;
    if (pages) {
      for (const m of html.matchAll(/<a href="(\/christmas-events\/[a-z0-9-]+)"[^>]*>(?:(?!<\/a>)[\s\S]){0,300}?(\d+) events?</g)) {
        const c = pages[m[1]];
        if (m[1] !== self && c && c[0] && c[0] !== toInt(m[2])) {
          linksStale = true;
          break;
        }
      }
    }
    if (!past.length && N === N0 && F === F0 && !headStale && !linksStale) return null;
    const only = { e: /* @__PURE__ */ new Set([N0, ...claimed.e]), f: /* @__PURE__ */ new Set([F0, ...claimed.f]), p: /* @__PURE__ */ new Set([N0 - F0]) };
    const base = { e: N0, f: F0 };
    let out = html;
    const gone = new Set(past.map((c) => c.id));
    for (const c of [...past].sort((a, b) => b.start - a.start)) {
      const end = sectionEnd(out, c.start);
      if (end > 0) out = out.slice(0, c.start) + out.slice(end);
    }
    if (gone.size) {
      out = out.replace(/<li\b[^>]*>(?:(?!<\/?li\b)[\s\S]){0,1500}?href="#([^"]+)"[\s\S]{0,1500}?<\/li>/g, (li, id) => gone.has(id) && !/<li\b/.test(li.slice(3)) ? "" : li);
    }
    out = out.replace(/<title>([^<]*)<\/title>/, (all, t) => `<title>${rewriteCounts(t, N, F, null, base)}</title>`);
    out = out.replace(
      /(<meta (?:name|property|itemprop)="(?:description|og:title|og:description|twitter:title|twitter:description|name)" content=")([^"]*)(")/g,
      (all, a, t, b) => a + rewriteCounts(t, N, F, null, base) + b
    );
    out = out.replace(/(<script type="application\/ld\+json">)([\s\S]*?)(<\/script>)/g, (all, a, body, b) => {
      let j;
      try {
        j = JSON.parse(body);
      } catch (e) {
        return all;
      }
      let g = j["@graph"] || [j];
      const drop = /* @__PURE__ */ new Set();
      g = g.filter((x) => {
        if (x["@type"] !== "Event") return true;
        const id = String(x["@id"] || ""), u = String(x.url || "");
        const key = "ev-" + (id.split("#event-")[1] || "");
        const end = String(x.endDate || x.startDate || "").slice(0, 10);
        if (gone.has(key) || gone.has(u.split("#")[1]) || end && end < today) {
          drop.add(id);
          return false;
        }
        return true;
      });
      const fix = (o) => {
        if (Array.isArray(o)) return o.forEach(fix);
        if (!o || typeof o !== "object") return;
        if (o["@type"] === "ItemList" && Array.isArray(o.itemListElement)) {
          o.itemListElement = o.itemListElement.filter((e) => !(e.item && drop.has(e.item["@id"])));
          o.itemListElement.forEach((e, i) => {
            e.position = i + 1;
          });
          if ("numberOfItems" in o && o.numberOfItems === N0) o.numberOfItems = N;
          else if ("numberOfItems" in o) o.numberOfItems = o.itemListElement.length;
        }
        for (const k of ["name", "description", "headline", "text"]) if (typeof o[k] === "string") o[k] = rewriteCounts(o[k], N, F, only, base);
        for (const v of Object.values(o)) if (v && typeof v === "object") fix(v);
      };
      if (j["@graph"]) {
        j["@graph"] = g;
        fix(j["@graph"]);
      } else if (!g.length) return "";
      else fix(j);
      return a + JSON.stringify(j).replace(/</g, "\\u003c") + b;
    });
    const has = (attr, v) => live.filter((c) => !v || c[attr].includes(v)).length;
    out = out.replace(/data-xf-total="\d+"/g, `data-xf-total="${N}"`);
    out = out.replace(/(<p class="rtt-xf__count"[^>]*>)([^<]*?)(\d+)([^<]*<\/p>)/g, (all, a, x, n, b) => englishGrammar(a + x + N + b));
    out = out.replace(/(<button[^>]*data-xf-type="([^"]*)"[^>]*>(?:(?!<\/button>)[\s\S])*?<b>)(\d+)(<\/b>)/g, (all, a, v, n, b) => a + has("ty", v) + b);
    out = out.replace(/(<(?:button|a)[^>]*data-xf-flag="([^"]*)"[^>]*>(?:(?!<\/(?:button|a)>)[\s\S])*?<b>)(\d+)(<\/b>)/g, (all, a, v, n, b) => a + has("fl", v) + b);
    out = out.replace(/(<h2[^>]*\bdata-n=")(\d+)("[^>]*>)/g, (all, a, n, b, off) => {
      const rest = out.slice(off + all.length);
      const nxt = rest.search(/<h2\b[^>]*\bdata-n=/);
      const seg = nxt < 0 ? rest : rest.slice(0, nxt);
      return a + (seg.match(/<section class="rtt-pe-ride"/g) || []).length + b;
    });
    const delta = N0 - N;
    if (delta > 0) {
      out = out.replace(/(<span class="rtt-ul__more"[^>]*>\+)(\d+)/g, (all, a, n) => a + Math.max(0, toInt(n) - delta));
      out = out.replace(/(<span class="rtt-ul__one"[^>]*>)(\d+)/g, (all, a, n) => a + Math.max(0, toInt(n) - delta));
    }
    const masks = [];
    if (pages) out = healCityLinks(out, pages, self, (x) => `\0${masks.push(x) - 1}\0`);
    const bodyAt = out.indexOf("</head>");
    const olds = [.../* @__PURE__ */ new Set([...only.e, ...only.f, ...only.p])].map(String);
    const parts = out.slice(bodyAt).split(/(<script\b[\s\S]*?<\/script>|<style\b[\s\S]*?<\/style>)/);
    for (let i = 0; i < parts.length; i += 2) {
      if (!olds.some((v) => parts[i].includes(v))) continue;
      parts[i] = parts[i].replace(/>([^<>]*\d[^<>]*)</g, (all, t) => olds.some((v) => t.includes(v)) ? ">" + rewriteCounts(t, N, F, only, base) + "<" : all);
    }
    out = out.slice(0, bodyAt) + parts.join("");
    out = out.replace(/\u0000(\d+)\u0000/g, (m0, i) => masks[+i]);
    return out === html ? null : out;
  }
  var CITY_WORDS = [
    "cities",
    "Canadian cities",
    "cities across",
    "villes",
    "St\xE4dten",
    "St\xE4dte",
    "ciudades",
    "citt\xE0",
    "cidades",
    "steden",
    "byer",
    "st\xE4der",
    "kaupungissa",
    "kaupunkia",
    "v\xE1rosban",
    "v\xE1rosban",
    "miastach",
    "ora\u0219e",
    "\u043C\u0456\u0441\u0442\u0430\u0445",
    "\u03C0\u03CC\u03BB\u03B5\u03B9\u03C2",
    "gradova",
    "linnas",
    "pils\u0113t\u0101s",
    "miestuose",
    "mest\xE1ch",
    "mestih",
    "b\xE6jum",
    "st\xF6\xF0um",
    "towns and cities"
  ];
  var C_RE = new RegExp(`(^|[^\\d.,:/-])${NUM}(?=${SP}(?:${CITY_WORDS.join("|")})(?![\\w-]))`, "g");
  var JA_CITY_RE = /(\d+)(の都市)/g;
  function dropPastItems(html, today) {
    return html.replace(/<li\b([^>]*\bdata-cal="[^"]*"[^>]*)>[\s\S]*?<\/li>/g, (li, attrs) => {
      const last = lastDay(attrs);
      return last && last < today ? "" : li;
    });
  }
  function healGuide(html, today, live, path) {
    const g = live && live.guides && live.guides[path];
    if (!g || !g.e) return null;
    const pages = live.pages || {};
    let out = dropPastItems(html, today);
    const items = (out.match(/\bdata-xf-ty="/g) || []).length;
    const masks = [];
    const mask = (s) => `\0${masks.push(s) - 1}\0`;
    out = out.replace(/<h2 id="city-[^"]*"[^>]*>[\s\S]*?(?=<h2\b|<\/article>|$)/g, (sec) => {
      const m = sec.match(/href="(\/christmas-events\/[a-z0-9-]+)(?:#[^"]*)?"/);
      const c = m && pages[m[1]];
      if (!c || !c[0]) return sec;
      return mask(healCityLinks(rewriteCounts(sec, c[0], c[1]), pages, path, (x) => x));
    });
    out = out.replace(/<li class="rtt-rc">[\s\S]*?<\/li>/g, (li) => {
      const m = li.match(/href="(\/christmas-events\/[a-z0-9-]+)"/);
      const c = m && pages[m[1]];
      return mask(c && c[0] ? rewriteCounts(li, c[0], c[1]) : li);
    });
    out = healCityLinks(out, pages, path, mask);
    out = out.replace(/(<script type="application\/ld\+json">)([\s\S]*?)(<\/script>)/g, (all, a, body, b) => {
      let j;
      try {
        j = JSON.parse(body);
      } catch (e) {
        return mask(all);
      }
      const walk = (o, E, F) => {
        if (Array.isArray(o)) return o.forEach((x) => walk(x, E, F));
        if (!o || typeof o !== "object") return;
        const u = String(o.url || o["@id"] || "");
        const p = u.replace("https://www.rallytakesthetrain.com", "").split("#")[0];
        const c = pages[p];
        const [e, f] = c && c[0] && p !== path ? c : [E, F];
        for (const k of ["name", "description", "headline", "text"]) {
          if (typeof o[k] !== "string") continue;
          let s = rewriteCounts(o[k], e, f);
          if (p === path || !c) s = s.replace(C_RE, (m0, pre, n) => pre + fmtLike(n, g.c));
          s = s.replace(/\((\d+) events?\)/, (m0, n) => `(${e} ${e === 1 ? "event" : "events"})`);
          o[k] = s;
        }
        for (const v of Object.values(o)) if (v && typeof v === "object") walk(v, e, f);
      };
      const before = JSON.stringify(j);
      walk(j, g.e, g.f);
      const after = JSON.stringify(j);
      return mask(after === before ? all : a + after.replace(/</g, "\\u003c") + b);
    });
    if (items) {
      out = out.replace(/data-xf-total="\d+"/g, `data-xf-total="${items}"`);
      out = out.replace(/(<p class="rtt-xf__count"[^>]*>)([^<]*?)(\d+)([^<]*<\/p>)/g, (all, a, x, n, b) => mask(a + x + items + b));
    }
    out = out.replace(/<script\b[\s\S]*?<\/script>|<style\b[\s\S]*?<\/style>/g, mask);
    const fixText = (t) => rewriteCounts(t, g.e, g.f).replace(C_RE, (m0, pre, n) => pre + fmtLike(n, g.c)).replace(JA_CITY_RE, (m0, n, b) => g.c + b);
    out = out.replace(/<title>([^<]*)<\/title>/, (all, t) => `<title>${fixText(t)}</title>`);
    out = out.replace(
      /(<meta (?:name|property|itemprop)="(?:description|og:title|og:description|twitter:title|twitter:description|name)" content=")([^"]*)(")/g,
      (all, a, t, b) => a + fixText(t) + b
    );
    const bodyAt = out.indexOf("</head>");
    out = out.slice(0, bodyAt) + out.slice(bodyAt).replace(/>([^<>]*\d[^<>]*)</g, (all, t) => ">" + fixText(t) + "<");
    out = out.replace(/\u0000(\d+)\u0000/g, (m0, i) => masks[+i]);
    return out === html ? null : out;
  }

  // src/sqsp.js
  var SEP = "<!--rtt-block-->";
  var esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  var unesc = (s) => String(s).replace(/&quot;/g, '"').replace(/&gt;/g, ">").replace(/&lt;/g, "<").replace(/&amp;/g, "&");
  function kindFor(path, live) {
    if (!live || !path || !path.startsWith("/christmas-events/")) return null;
    if (live.guides && live.guides[path]) return "guide";
    if (live.pages && live.pages[path]) return "city";
    return null;
  }
  function htmlBlocks(layout) {
    const out = [];
    const walk = (o) => {
      if (Array.isArray(o)) return o.forEach(walk);
      if (!o || typeof o !== "object") return;
      if (o.value && typeof o.value.html === "string" && o.id) out.push(o);
      for (const k of Object.keys(o)) if (k !== "value" && o[k] && typeof o[k] === "object") walk(o[k]);
    };
    walk(layout);
    return out;
  }
  function planItem(item, live, today = refToday()) {
    const path = item.fullUrl;
    const kind = kindFor(path, live);
    if (!kind) return null;
    const seo = item.seoData || {};
    const layout = item.body && item.body.layout;
    const blocks = layout && typeof layout === "object" ? htmlBlocks(layout) : [];
    const excerpt = item.excerpt && item.excerpt.html || "";
    const head = [
      `<title>${esc(seo.seoTitle || "")}</title>`,
      `<meta name="description" content="${esc(seo.seoDescription || "")}">`,
      `<meta property="og:title" content="${esc(item.title || "")}">`,
      `<meta property="og:description" content="${esc(excerpt)}">`
    ].join("\n");
    const doc = `<html><head>
${head}
</head><body>${SEP}${blocks.map((b) => b.value.html).join(SEP)}${SEP}</body></html>`;
    let healed = null;
    try {
      healed = kind === "guide" ? healGuide(doc, today, live, path) : healCity(doc, today, live.pages, path);
    } catch (e) {
      return { error: "healer: " + e.message };
    }
    if (!healed) return null;
    const hd = healed.slice(0, healed.indexOf("</head>"));
    const get = (re) => {
      const m = hd.match(re);
      return m ? unesc(m[1]) : null;
    };
    const nTitle = get(/<title>([^<]*)<\/title>/);
    const nDesc = get(/<meta name="description" content="([^"]*)"/);
    const nPost = get(/<meta property="og:title" content="([^"]*)"/);
    const nEx = get(/<meta property="og:description" content="([^"]*)"/);
    const body = healed.slice(healed.indexOf("<body>") + 6, healed.lastIndexOf("</body>"));
    const parts = body.split(SEP);
    if (parts.length !== blocks.length + 2) return { error: `block boundaries moved (${parts.length - 2} vs ${blocks.length})` };
    const next = JSON.parse(JSON.stringify(item));
    const changes = [];
    const set = (field, before, after, apply) => {
      if (after == null || after === before) return;
      changes.push({ field, before, after });
      apply(after);
    };
    next.seoData = next.seoData || {};
    if (seo.seoTitle) set("seoTitle", seo.seoTitle, nTitle, (v) => {
      next.seoData.seoTitle = v;
    });
    if (seo.seoDescription) set("seoDescription", seo.seoDescription, nDesc, (v) => {
      next.seoData.seoDescription = v;
    });
    set("title", item.title || "", nPost, (v) => {
      next.title = v;
    });
    if (excerpt) set("excerpt", excerpt, nEx, (v) => {
      next.excerpt.html = v;
      if (typeof next.excerpt.raw === "string") next.excerpt.raw = v;
    });
    const nextBlocks = htmlBlocks(next.body && next.body.layout);
    let removedCards = 0;
    blocks.forEach((b, i) => {
      const after = parts[i + 1];
      if (after === b.value.html) return;
      const cards = (s) => (s.match(/<section class="rtt-pe-ride"/g) || []).length;
      removedCards += cards(b.value.html) - cards(after);
      changes.push({ field: `block:${b.id}`, before: b.value.html, after });
      nextBlocks[i].value.html = after;
    });
    if (!changes.length) return null;
    return { kind, path, item: next, changes, removedCards };
  }
  function describe(plan) {
    const lines = [];
    for (const c of plan.changes) {
      if (c.field.startsWith("block:")) continue;
      lines.push(`${c.field}: ${strip(c.before)} => ${strip(c.after)}`);
    }
    const blocks = plan.changes.filter((c) => c.field.startsWith("block:")).length;
    if (blocks) lines.push(`${blocks} code block${blocks > 1 ? "s" : ""} updated${plan.removedCards ? `, ${plan.removedCards} past event${plan.removedCards > 1 ? "s" : ""} removed` : ""}`);
    return lines;
  }
  var strip = (s) => String(s).replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim().slice(0, 220);
  var COLLECTION = "6ae8c64da7d5c013a6eb8e11";
  var LIVE_URL = "https://raw.githubusercontent.com/stridematt/sitemaps/main/tools/truth/live.json";
  var sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function crumb() {
    const m = document.cookie.match(/(?:^|; )crumb=([^;]+)/);
    if (!m) throw new Error("not signed in to the Squarespace admin (no crumb cookie)");
    return decodeURIComponent(m[1]);
  }
  var DB = "rtt-sqsp-sync";
  function idb() {
    return new Promise((res, rej) => {
      const r = indexedDB.open(DB, 1);
      r.onupgradeneeded = () => r.result.createObjectStore("backups", { keyPath: "key" });
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  }
  async function backup(item) {
    const db = await idb();
    await new Promise((res, rej) => {
      const tx = db.transaction("backups", "readwrite");
      tx.objectStore("backups").put({ key: `${item.id}@${item.updatedOn}`, id: item.id, path: item.fullUrl, at: Date.now(), item });
      tx.oncomplete = res;
      tx.onerror = () => rej(tx.error);
    });
  }
  async function backups(id) {
    const db = await idb();
    return new Promise((res) => {
      const out = [];
      const c = db.transaction("backups").objectStore("backups").openCursor();
      c.onsuccess = () => {
        const cur = c.result;
        if (!cur) return res(out.sort((a, b) => b.at - a.at));
        if (!id || cur.value.id === id || cur.value.path === id) out.push(cur.value);
        cur.continue();
      };
    });
  }
  var postUrl = (id) => `/api/content/blogs/${COLLECTION}/text-posts/${id}`;
  async function put(item) {
    const r = await fetch(postUrl(item.id), {
      method: "PUT",
      headers: { Accept: "application/json, text/plain, */*", "Content-Type": "application/json", "X-CSRF-Token": crumb() },
      body: JSON.stringify(item)
    });
    if (!r.ok) throw new Error(`PUT ${r.status}`);
    return r.json().catch(() => ({}));
  }
  async function restore(idOrPath, which = 0) {
    const list = await backups(idOrPath);
    if (!list[which]) throw new Error("no backup for " + idOrPath);
    const cur = await fetch(postUrl(list[which].id)).then((r) => r.json());
    const old = { ...list[which].item, updatedOn: cur.updatedOn };
    await put(old);
    return `restored ${list[which].path} to its copy from ${new Date(list[which].at).toISOString()}`;
  }
  async function run(opts = {}) {
    const { apply = false, limit = 400, delayMs = 400, quietMinutes = 15, only = null, onProgress = null } = opts;
    const state = { started: (/* @__PURE__ */ new Date()).toISOString(), apply, scanned: 0, planned: 0, written: 0, skipped: [], errors: [], plans: [], done: false };
    if (typeof window !== "undefined") window.__rttSyncState = state;
    const live = opts.live || await fetch(LIVE_URL + "?t=" + Date.now()).then((r) => r.json());
    const today = opts.today || refToday();
    state.today = today;
    state.liveGenerated = live.generated;
    const todo = [];
    let start = null, guard = 0;
    do {
      const j = await fetch(`/api/content-collections/${COLLECTION}/content-items?limit=50${start ? "&start=" + encodeURIComponent(start) : ""}`).then((r) => r.json());
      for (const it of j.results || []) {
        state.scanned++;
        if (only && !only.includes(it.fullUrl)) continue;
        if (it.workflowState !== 1) continue;
        let plan;
        try {
          plan = planItem(it, live, today);
        } catch (e) {
          plan = { error: e.message };
        }
        if (!plan) continue;
        if (plan.error) {
          state.errors.push({ path: it.fullUrl, error: plan.error });
          continue;
        }
        state.planned++;
        state.plans.push({ path: it.fullUrl, id: it.id, lines: describe(plan) });
        todo.push(it.id);
      }
      if (onProgress) onProgress(state);
      start = j.hasNextPage ? j.nextPageStart : null;
    } while (start && ++guard < 400);
    if (apply) {
      for (const id of todo.slice(0, limit)) {
        try {
          const cur = await fetch(postUrl(id)).then((r) => r.json());
          if (Date.now() - cur.updatedOn < quietMinutes * 6e4) {
            state.skipped.push({ path: cur.fullUrl, why: "edited recently" });
            continue;
          }
          const plan = planItem(cur, live, today);
          if (!plan || plan.error) {
            if (plan && plan.error) state.errors.push({ path: cur.fullUrl, error: plan.error });
            continue;
          }
          await backup(cur);
          await put(plan.item);
          state.written++;
          if (onProgress) onProgress(state);
        } catch (e) {
          state.errors.push({ id, error: e.message });
        }
        await sleep(delayMs);
      }
      if (todo.length > limit) state.skipped.push({ why: `${todo.length - limit} more over the per-run limit; they go next run` });
    }
    state.done = true;
    state.finished = (/* @__PURE__ */ new Date()).toISOString();
    return state;
  }
  return __toCommonJS(sqsp_exports);
})();
