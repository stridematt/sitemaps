// Squarespace sync: write the healed counts back into the stored posts, so Squarespace itself
// (editor, RSS, search previews, any copy served without the Worker) says the same as the live site.
// The same healer code as the Worker is used, so both always agree.
//
// planItem() is pure and runs in Node tests and in the browser. run() talks to the Squarespace
// admin API and only works inside a signed-in Squarespace admin tab.
import { healCity, healGuide, refToday } from './heal.js';

const SEP = '<!--rtt-block-->';
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const unesc = (s) => String(s).replace(/&quot;/g, '"').replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/&amp;/g, '&');

export function kindFor(path, live) {
  if (!live || !path || !path.startsWith('/christmas-events/')) return null;
  if (live.guides && live.guides[path]) return 'guide';
  if (live.pages && live.pages[path]) return 'city';
  return null;
}

// Every block that carries HTML (code blocks and text blocks), in page order.
export function htmlBlocks(layout) {
  const out = [];
  const walk = (o) => {
    if (Array.isArray(o)) return o.forEach(walk);
    if (!o || typeof o !== 'object') return;
    if (o.value && typeof o.value.html === 'string' && o.id) out.push(o);
    for (const k of Object.keys(o)) if (k !== 'value' && o[k] && typeof o[k] === 'object') walk(o[k]);
  };
  walk(layout);
  return out;
}

// Work out what a stored post should say today. Returns null when nothing needs to change,
// otherwise { item (patched copy), changes: [{ field, before, after }], removedCards }.
export function planItem(item, live, today = refToday()) {
  const path = item.fullUrl;
  const kind = kindFor(path, live);
  if (!kind) return null;
  const seo = item.seoData || {};
  const layout = item.body && item.body.layout;
  const blocks = layout && typeof layout === 'object' ? htmlBlocks(layout) : [];
  const excerpt = (item.excerpt && item.excerpt.html) || '';

  const head = [
    `<title>${esc(seo.seoTitle || '')}</title>`,
    `<meta name="description" content="${esc(seo.seoDescription || '')}">`,
    `<meta property="og:title" content="${esc(item.title || '')}">`,
    `<meta property="og:description" content="${esc(excerpt)}">`,
  ].join('\n');
  const doc = `<html><head>\n${head}\n</head><body>${SEP}${blocks.map((b) => b.value.html).join(SEP)}${SEP}</body></html>`;

  let healed = null;
  try {
    healed = kind === 'guide' ? healGuide(doc, today, live, path) : healCity(doc, today, live.pages, path);
  } catch (e) {
    return { error: 'healer: ' + e.message };
  }
  if (!healed) return null;

  const hd = healed.slice(0, healed.indexOf('</head>'));
  const get = (re) => { const m = hd.match(re); return m ? unesc(m[1]) : null; };
  const nTitle = get(/<title>([^<]*)<\/title>/);
  const nDesc = get(/<meta name="description" content="([^"]*)"/);
  const nPost = get(/<meta property="og:title" content="([^"]*)"/);
  const nEx = get(/<meta property="og:description" content="([^"]*)"/);
  const body = healed.slice(healed.indexOf('<body>') + 6, healed.lastIndexOf('</body>'));
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
  if (seo.seoTitle) set('seoTitle', seo.seoTitle, nTitle, (v) => { next.seoData.seoTitle = v; });
  if (seo.seoDescription) set('seoDescription', seo.seoDescription, nDesc, (v) => { next.seoData.seoDescription = v; });
  set('title', item.title || '', nPost, (v) => { next.title = v; });
  if (excerpt) set('excerpt', excerpt, nEx, (v) => { next.excerpt.html = v; if (typeof next.excerpt.raw === 'string') next.excerpt.raw = v; });

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

// A short, readable account of one plan (for dry runs and the run log).
export function describe(plan) {
  const lines = [];
  for (const c of plan.changes) {
    if (c.field.startsWith('block:')) continue;
    lines.push(`${c.field}: ${strip(c.before)} => ${strip(c.after)}`);
  }
  const blocks = plan.changes.filter((c) => c.field.startsWith('block:')).length;
  if (blocks) lines.push(`${blocks} code block${blocks > 1 ? 's' : ''} updated${plan.removedCards ? `, ${plan.removedCards} past event${plan.removedCards > 1 ? 's' : ''} removed` : ''}`);
  return lines;
}
const strip = (s) => String(s).replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim().slice(0, 220);

// ------------------------------------------------------------------ browser runner
const COLLECTION = '6ae8c64da7d5c013a6eb8e11'; // "Christmas Events for Kids" blog
const LIVE_URL = 'https://raw.githubusercontent.com/stridematt/sitemaps/main/tools/truth/live.json';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function crumb() {
  const m = document.cookie.match(/(?:^|; )crumb=([^;]+)/);
  if (!m) throw new Error('not signed in to the Squarespace admin (no crumb cookie)');
  return decodeURIComponent(m[1]);
}

const DB = 'rtt-sqsp-sync';
function idb() {
  return new Promise((res, rej) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore('backups', { keyPath: 'key' });
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
async function backup(item) {
  const db = await idb();
  await new Promise((res, rej) => {
    const tx = db.transaction('backups', 'readwrite');
    tx.objectStore('backups').put({ key: `${item.id}@${item.updatedOn}`, id: item.id, path: item.fullUrl, at: Date.now(), item });
    tx.oncomplete = res;
    tx.onerror = () => rej(tx.error);
  });
}
export async function backups(id) {
  const db = await idb();
  return new Promise((res) => {
    const out = [];
    const c = db.transaction('backups').objectStore('backups').openCursor();
    c.onsuccess = () => {
      const cur = c.result;
      if (!cur) return res(out.sort((a, b) => b.at - a.at));
      if (!id || cur.value.id === id || cur.value.path === id) out.push(cur.value);
      cur.continue();
    };
  });
}

const postUrl = (id) => `/api/content/blogs/${COLLECTION}/text-posts/${id}`;
async function put(item) {
  const r = await fetch(postUrl(item.id), {
    method: 'PUT',
    headers: { Accept: 'application/json, text/plain, */*', 'Content-Type': 'application/json', 'X-CSRF-Token': crumb() },
    body: JSON.stringify(item),
  });
  if (!r.ok) throw new Error(`PUT ${r.status}`);
  return r.json().catch(() => ({}));
}

// Put a post back the way it was before a sync (latest backup by default).
export async function restore(idOrPath, which = 0) {
  const list = await backups(idOrPath);
  if (!list[which]) throw new Error('no backup for ' + idOrPath);
  const cur = await fetch(postUrl(list[which].id)).then((r) => r.json());
  const old = { ...list[which].item, updatedOn: cur.updatedOn };
  await put(old);
  return `restored ${list[which].path} to its copy from ${new Date(list[which].at).toISOString()}`;
}

// Scan the collection, plan every post, and (with apply) write up to `limit` of them.
// Posts edited in the last `quietMinutes` are left alone so a sync never overwrites live editing.
export async function run(opts = {}) {
  const { apply = false, limit = 400, delayMs = 400, quietMinutes = 15, only = null, onProgress = null } = opts;
  const state = { started: new Date().toISOString(), apply, scanned: 0, planned: 0, written: 0, skipped: [], errors: [], plans: [], done: false };
  if (typeof window !== 'undefined') window.__rttSyncState = state;
  const live = opts.live || (await fetch(LIVE_URL + '?t=' + Date.now()).then((r) => r.json()));
  const today = opts.today || refToday();
  state.today = today;
  state.liveGenerated = live.generated;

  const todo = [];
  let start = null, guard = 0;
  do {
    const j = await fetch(`/api/content-collections/${COLLECTION}/content-items?limit=50${start ? '&start=' + encodeURIComponent(start) : ''}`).then((r) => r.json());
    for (const it of j.results || []) {
      state.scanned++;
      if (only && !only.includes(it.fullUrl)) continue;
      if (it.workflowState !== 1) continue; // published posts only
      let plan;
      try { plan = planItem(it, live, today); } catch (e) { plan = { error: e.message }; }
      if (!plan) continue;
      if (plan.error) { state.errors.push({ path: it.fullUrl, error: plan.error }); continue; }
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
        const cur = await fetch(postUrl(id)).then((r) => r.json()); // fresh copy, the shape PUT expects
        if (Date.now() - cur.updatedOn < quietMinutes * 60000) { state.skipped.push({ path: cur.fullUrl, why: 'edited recently' }); continue; }
        const plan = planItem(cur, live, today);
        if (!plan || plan.error) { if (plan && plan.error) state.errors.push({ path: cur.fullUrl, error: plan.error }); continue; }
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
  state.finished = new Date().toISOString();
  return state;
}
