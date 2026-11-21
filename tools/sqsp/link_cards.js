// Link event cards to their event pages, on every Christmas events city page.
//
// Some city pages carry cards for events that have their own event page, but the card doesn't link it
// (the card was built before the event page, so it points at the organizer). This adds the same two links
// the card builder writes when the event page exists: the card title, and the "See photos, dates and full
// details" button (its wording copied from a card on the same page that already links its event page, so
// it's always in the page's language; if no card on the page links yet, only the title is linked).
//
// Matching, strict: the event page slug must start with the card name's slug (exact) and be the only one;
// otherwise every distinctive word of the name must be in exactly one slug (fuzzy) and that page's own
// title must match the card name. Slugs are taken from sitemap.xml, limited to the code suffixes this page
// already uses. Counts never change: cards and free flags are compared before and after every write.
//
// Run in a signed-in Squarespace admin tab (https://rally-takes-the-train-site.squarespace.com/config/pages):
//   (0, eval)(await fetch('https://raw.githubusercontent.com/stridematt/sitemaps/main/tools/sqsp/link_cards.js').then(r => r.text()));
//   await RTTLink.run({ apply: false })            // dry run: RTTLink.state.plans
//   await RTTLink.run({ apply: true })             // write; backups in IndexedDB rtt-sqsp-sync
//   RTTLink.state                                  // progress while it runs
// Undo one post: the sync's RTTSync.restore(path), or RTTLink.restore(path).
(function () {
  const COLLECTION = '6ae8c64da7d5c013a6eb8e11';
  const RAW = 'https://raw.githubusercontent.com/stridematt/sitemaps/main/tools/';
  const postUrl = (id) => `/api/content/blogs/${COLLECTION}/text-posts/${id}`;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const STOP = new Set(['the', 'and', 'for', 'with', 'christmas', 'santa', 'navidad', 'noel', 'weihnachten', 'kids', 'children', 'family', 'familia', 'del', 'des', 'les', 'der', 'die', 'das', 'con', 'per', 'van', 'het', 'een', 'und']);
  const slugify = (t) => String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/&/g, 'and').replace(/['’]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const norm = (t) => slugify(t).replace(/-/g, ' ');
  const text = (html) => { const d = document.createElement('div'); d.innerHTML = html; return d.textContent.trim(); };
  const count = (s, k) => s.split(k).length - 1;
  const state = { started: null, apply: false, pages: 0, read: 0, planned: 0, written: 0, linked: 0, verified: 0, rejected: [], skipped: [], errors: [], plans: [], done: false };

  function crumb() {
    const m = document.cookie.match(/(?:^|; )crumb=([^;]+)/);
    if (!m) throw new Error('not signed in to the Squarespace admin');
    return decodeURIComponent(m[1]);
  }
  function idb() {
    return new Promise((res, rej) => {
      const r = indexedDB.open('rtt-sqsp-sync', 1);
      r.onupgradeneeded = () => r.result.createObjectStore('backups', { keyPath: 'key' });
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
    });
  }
  async function backup(item, note) {
    const db = await idb();
    await new Promise((res, rej) => {
      const tx = db.transaction('backups', 'readwrite');
      tx.objectStore('backups').put({ key: `${item.id}@${item.updatedOn}`, id: item.id, path: item.fullUrl, at: Date.now(), item, note });
      tx.oncomplete = res; tx.onerror = () => rej(tx.error);
    });
  }
  async function restore(path) {
    const db = await idb();
    const all = await new Promise((res) => { const out = []; const c = db.transaction('backups').objectStore('backups').openCursor(); c.onsuccess = () => { const x = c.result; if (!x) return res(out); if (x.value.path === path) out.push(x.value); x.continue(); }; });
    all.sort((a, b) => b.at - a.at);
    if (!all[0]) throw new Error('no backup for ' + path);
    const cur = await fetch(postUrl(all[0].id)).then((r) => r.json());
    await put({ ...all[0].item, updatedOn: cur.updatedOn });
    return `restored ${path} from ${new Date(all[0].at).toISOString()}`;
  }
  async function put(item) {
    const r = await fetch(postUrl(item.id), { method: 'PUT', headers: { Accept: 'application/json, text/plain, */*', 'Content-Type': 'application/json', 'X-CSRF-Token': crumb() }, body: JSON.stringify(item) });
    if (!r.ok) throw new Error('PUT ' + r.status);
  }
  async function getJSON(url, tries = 6) {
    for (let i = 0; i < tries; i++) {
      const r = await fetch(url);
      if (r.status === 429 || r.status === 503) { await sleep(Math.min(8000 * (i + 1), 60000)); continue; }
      if (!r.ok) return { status: r.status };
      return { status: 200, json: await r.json() };
    }
    return { status: 429 };
  }
  function htmlBlocks(layout) {
    const out = [];
    const walk = (o) => { if (Array.isArray(o)) return o.forEach(walk); if (!o || typeof o !== 'object') return; if (o.value && typeof o.value.html === 'string' && o.id) out.push(o); for (const k of Object.keys(o)) if (k !== 'value' && o[k] && typeof o[k] === 'object') walk(o[k]); };
    walk(layout); return out;
  }

  const CARD = /<section class="rtt-pe-ride" id="([^"]+)"[\s\S]*?<\/section>/g;
  const H3 = /(<h3 id="[^"]+">)([\s\S]*?)(<\/h3>)/;
  const BOOK_EXT = /<a class="rtt-pe-ride__book" href="https?:\/\/[^"]*"[^>]*>[\s\S]*?<\/a>/;
  const BOOK_EVP = /<a class="rtt-pe-ride__book" href="\/christmas-events\/[a-z0-9-]+" data-rtt-evp="[a-z0-9-]+">([\s\S]*?)<\/a>/;

  // Plan the links for one page's html (pure apart from the slug index).
  function planHtml(html, path, index, notEvents) {
    const linked = new Set([...html.matchAll(/data-rtt-evp="([a-z0-9-]+)"/g)].map((m) => m[1]));
    const suffixes = new Set([...linked].map((s) => s.split('-').pop()));
    const own = path.split('/').pop().split('-').pop();
    const cityBase = slugify(path.split('/').pop().replace(/^(navidad-con-ninos|natal-com-criancas|noel-avec-les-enfants|activites-de-noel-pour-enfants|weihnachten-mit-kindern|natale-con-i-bambini|kerst-met-kinderen|kodomo-christmas|rozhdestvo-s-detmi|christmas-in)-/, '').replace(/-with-kids$/, '').replace(/-[a-z]{2}$/, ''));
    if (own.length === 2) suffixes.add(own);
    const bookInner = (html.match(BOOK_EVP) || [])[1] || null;   // this page's own button wording
    const pool = [...suffixes].flatMap((x) => index.get(x) || []).filter((s) => !linked.has(s) && !notEvents.has(s));
    const out = [];
    const taken = new Set();
    for (const m of html.matchAll(CARD)) {
      const sec = m[0];
      const hm = sec.match(H3);
      if (!hm || hm[2].includes('<a ')) continue;
      const name = text(hm[2]);
      const b = slugify(name);
      if (!b) continue;
      // The slug has to name this place: the card's town (data-xf-town) or the city page's own city.
      const town = slugify((sec.match(/data-xf-town="([^"]*)"/) || [])[1] || '');
      const places = [town, cityBase].filter(Boolean);
      const here = (s) => { const rest = '-' + s.slice(0, s.lastIndexOf('-')) + '-'; return places.some((t) => rest.includes('-' + t + '-')); };
      let cands = pool.filter((s) => s.startsWith(b + '-') && s.slice(b.length + 1).split('-').length <= 5 && (here(s) || s === b + '-' + s.split('-').pop()));
      let how = 'exact';
      if (cands.length !== 1) {
        const toks = b.split('-').filter((t) => t.length > 2 && !STOP.has(t));
        cands = toks.length >= 2 ? pool.filter((s) => { const st = new Set(s.split('-')); return toks.every((t) => st.has(t)) && here(s); }) : [];
        how = 'fuzzy';
      }
      if (cands.length !== 1 || taken.has(cands[0])) continue;
      taken.add(cands[0]);
      out.push({ id: m[1], name, slug: cands[0], how });
    }
    return { links: out, bookInner };
  }

  function applyHtml(html, links, bookInner) {
    const by = new Map(links.map((l) => [l.id, l.slug]));
    return html.replace(CARD, (sec, id) => {
      const slug = by.get(id);
      if (!slug) return sec;
      let s = sec.replace(H3, `$1<a class="rtt-evp-h" href="/christmas-events/${slug}" data-rtt-evp="${slug}">$2</a>$3`);
      if (bookInner && BOOK_EXT.test(s)) s = s.replace(BOOK_EXT, `<a class="rtt-pe-ride__book" href="/christmas-events/${slug}" data-rtt-evp="${slug}">${bookInner}</a>`);
      return s;
    });
  }

  async function run(opts = {}) {
    const { apply = false, only = null, limit = Infinity, workers = 3, quietMinutes = 15, delayMs = 300 } = opts;
    Object.assign(state, { started: new Date().toISOString(), apply, pages: 0, read: 0, planned: 0, written: 0, linked: 0, verified: 0, rejected: [], skipped: [], errors: [], plans: [], done: false });
    const bust = '?t=' + Date.now();
    const live = await fetch(RAW + 'truth/live.json' + bust).then((r) => r.json());
    const ids = await fetch(RAW + 'sqsp/ids.json' + bust).then((r) => r.json());
    let sm = '';
    for (let i = 0; i < 6 && !sm; i++) { const r = await fetch('/sitemap.xml'); if (r.ok) sm = await r.text(); else await sleep(10000 * (i + 1)); }
    if (!sm) throw new Error('could not read sitemap.xml');
    const notEvents = new Set([...Object.keys(live.pages), ...Object.keys(live.guides)].map((p) => p.split('/').pop()));
    const index = new Map();
    for (const m of sm.matchAll(/christmas-events\/([a-z0-9-]+)<\/loc>/g)) {
      const s = m[1]; const x = s.split('-').pop();
      if (!index.has(x)) index.set(x, []);
      index.get(x).push(s);
    }
    const todo = Object.keys(ids).filter((p) => live.pages[p] && !live.guides[p] && (!only || only.includes(p)));
    state.pages = todo.length;
    let next = 0;
    const one = async (path) => {
      const id = ids[path];
      const g = await getJSON(postUrl(id));
      if (g.status !== 200) { state.errors.push({ path, error: 'GET ' + g.status }); return; }
      const cur = g.json; state.read++;
      if (cur.workflowState !== 1) return;
      const blocks = htmlBlocks(cur.body && cur.body.layout);
      const plan = [];
      for (const b of blocks) {
        if (!b.value.html.includes('rtt-pe-ride')) continue;
        const p = planHtml(b.value.html, path, index, notEvents);
        if (p.links.length) plan.push({ block: b.id, ...p });
      }
      if (!plan.length) return;
      // Fuzzy matches: the event page's own title has to match the card name.
      for (const p of plan) {
        const keep = [];
        for (const l of p.links) {
          if (l.how === 'exact') { keep.push(l); continue; }
          const e = await getJSON(`/christmas-events/${l.slug}?format=json`);
          const t = e.json && e.json.item && e.json.item.title || '';
          const a = norm(t), c = norm(l.name);
          if (e.status === 200 && e.json.item.workflowState === 1 && a && (a === c || a.includes(c) || c.includes(a))) { state.verified++; keep.push(l); }
          else state.rejected.push({ path, card: l.name, slug: l.slug, title: t, status: e.status });
          await sleep(150);
        }
        p.links = keep;
      }
      const n = plan.reduce((k, p) => k + p.links.length, 0);
      if (!n) return;
      state.planned++;
      state.plans.push({ path, links: plan.flatMap((p) => p.links.map((l) => `${l.how}: ${l.name} -> ${l.slug}`)), titleOnly: plan.some((p) => !p.bookInner) });
      if (!apply) return;
      if (state.written >= limit) { state.skipped.push({ path, why: 'over limit' }); return; }
      if (Date.now() - cur.updatedOn < quietMinutes * 60000) { state.skipped.push({ path, why: 'edited recently' }); return; }
      const item = JSON.parse(JSON.stringify(cur));
      const byId = new Map(htmlBlocks(item.body.layout).map((b) => [b.id, b]));
      for (const p of plan) {
        const b = byId.get(p.block);
        const before = b.value.html, after = applyHtml(before, p.links, p.bookInner);
        if (count(after, '<section class="rtt-pe-ride"') !== count(before, '<section class="rtt-pe-ride"') || count(after, 'data-xf-fl="free') !== count(before, 'data-xf-fl="free')) throw new Error('card or free count would change');
        b.value.html = after;
      }
      await backup(cur, 'before linking cards to their event pages');
      await put(item);
      const back = await getJSON(postUrl(id));
      const want = htmlBlocks(item.body.layout).map((b) => b.value.html).join('');
      const got = back.json ? htmlBlocks(back.json.body.layout).map((b) => b.value.html).join('') : '';
      if (got !== want) state.errors.push({ path, error: 'read-back differs; check and restore if needed' });
      state.written++; state.linked += n;
      await sleep(delayMs);
    };
    const worker = async () => { while (next < todo.length) { const p = todo[next++]; try { await one(p); } catch (e) { state.errors.push({ path: p, error: e.message }); } } };
    await Promise.all(Array.from({ length: workers }, worker));
    state.done = true; state.finished = new Date().toISOString();
    return state;
  }

  window.RTTLink = { run, restore, state, planHtml, applyHtml };
})();
