// ---- Scheduler: Cloudflare starts the GitHub jobs on time ------------------------------------------
// GitHub delays or skips scheduled runs when it is busy (Nov 26, 2026: an hourly job ran every 3 to 10 hours).
// Cloudflare's cron is reliable, so this Worker's cron (every 10 minutes) starts each job through GitHub's
// workflow_dispatch API on the timetable below. GitHub's own schedules stay in the workflows as a sparse
// fallback.
//
// Before starting a job it asks GitHub for that workflow's recent runs and skips if one is queued or running,
// or if one started recently (GitHub's fallback schedule, a push, or a manual run). A job skipped because one
// is still running is retried on the next ticks until it starts (or its slot expires), so the 3-hourly full
// run is never lost behind a long counts run.
//
// Needs: the GH_DISPATCH_TOKEN secret (a fine-grained GitHub token for stridematt/sitemaps with
// Actions: Read and write) and the SCHEDULER_KV namespace. Status, without secrets:
//   https://www.rallytakesthetrain.com/christmas-rtt-scheduler.json
// tools/truth/health_check.py reads it every hour and raises an issue if ticks stop or dispatches fail.

export const REPO = 'stridematt/sitemaps';
export const STATUS_PATH = '/christmas-rtt-scheduler.json';

// The timetable, in UTC. slot(h, m) is the 10-minute slot (m = 0, 10, ... 50).
// gap: skip if a run of the workflow started in the last `gap` minutes. ttl: how long a missed start is retried.
export const JOBS = [
  { id: 'hreflang-full', workflow: 'hreflang.yml', inputs: { mode: 'full' }, when: (h, m) => m === 20 && h % 3 === 0, gap: 20, ttl: 90 },
  { id: 'hreflang-counts', workflow: 'hreflang.yml', inputs: { mode: 'counts' }, when: (h, m) => m === 50, gap: 20, ttl: 30 },
  { id: 'verify-live', workflow: 'verify-live.yml', when: (h, m) => m === 30, gap: 20, ttl: 30 },
  { id: 'counts-health', workflow: 'counts-health.yml', when: (h, m) => m === 40, gap: 20, ttl: 30 },
  { id: 'services-counts', workflow: 'services-counts.yml', when: (h, m) => m === 40, gap: 20, ttl: 30 },
  { id: 'indexnow-recent', workflow: 'indexnow-recent.yml', when: (h, m) => m === 40 && h % 6 === 0, gap: 60, ttl: 60 },
];

const ACTIVE = new Set(['queued', 'in_progress', 'waiting', 'requested', 'pending']);
const MIN = 60 * 1000;

function gh(env, path, init = {}) {
  return fetch(`https://api.github.com/repos/${REPO}${path}`, {
    ...init,
    headers: {
      authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
      accept: 'application/vnd.github+json',
      'x-github-api-version': '2022-11-28',
      'user-agent': 'rtt-hreflang-scheduler',
      ...(init.body ? { 'content-type': 'application/json' } : {}),
    },
  });
}

// Decide for one due job: { start: true } or { start: false, reason, retry }.
export function decide(runs, job, now) {
  for (const r of runs) {
    if (ACTIVE.has(r.status)) return { start: false, reason: `a run is ${r.status.replace('_', ' ')}`, retry: true };
  }
  // A finished run only covers the slot if it did real work: a GitHub scheduled run that stepped aside for ours
  // (hreflang.yml's gate job) finishes in seconds and must not make us skip.
  const worked = (r) => r.event === 'workflow_dispatch' || (Date.parse(r.updated_at || r.created_at) - Date.parse(r.created_at)) > 3 * MIN;
  const recent = runs.find((r) => now - Date.parse(r.created_at) < job.gap * MIN && worked(r));
  if (recent) return { start: false, reason: `a ${recent.event} run started ${Math.round((now - Date.parse(recent.created_at)) / MIN)} min ago`, retry: false };
  return { start: true };
}

async function startJob(env, job, now) {
  const r = await gh(env, `/actions/workflows/${job.workflow}/runs?per_page=10&exclude_pull_requests=true`);
  if (!r.ok) return { ok: false, action: `error: runs lookup HTTP ${r.status}`, retry: true };
  // push runs of hreflang.yml only validate files (seconds); they are not the job being scheduled
  const runs = ((await r.json()).workflow_runs || []).filter((x) => x.event !== 'pull_request' && x.event !== 'push');
  const d = decide(runs, job, now);
  if (!d.start) return { ok: true, action: `skipped: ${d.reason}`, retry: d.retry };
  const body = JSON.stringify({ ref: 'main', ...(job.inputs ? { inputs: job.inputs } : {}) });
  const s = await gh(env, `/actions/workflows/${job.workflow}/dispatches`, { method: 'POST', body });
  if (s.status === 204) return { ok: true, action: 'started', retry: false };
  const msg = (await s.text()).slice(0, 160).replace(/\s+/g, ' ');
  return { ok: false, action: `error: dispatch HTTP ${s.status} ${msg}`, retry: s.status >= 500 || s.status === 429 };
}

export async function runScheduler(env, nowMs = Date.now()) {
  const kv = env.SCHEDULER_KV;
  let st = {};
  try { st = (kv && (await kv.get('status', 'json'))) || {}; } catch (e) { st = {}; }
  const jobs = st.jobs || {};
  const pending = st.pending || {};
  const d = new Date(nowMs);
  const h = d.getUTCHours();
  const m = Math.floor(d.getUTCMinutes() / 10) * 10;

  // Due now, plus earlier starts still waiting (until their slot expires).
  const due = new Map();
  for (const job of JOBS) if (job.when(h, m)) due.set(job.id, { job, since: nowMs });
  for (const [id, since] of Object.entries(pending)) {
    const job = JOBS.find((j) => j.id === id);
    if (!job || due.has(id)) continue;
    if (nowMs - since > job.ttl * MIN) {
      // not an error: the job kept running past its next slot, so that slot was covered by the run itself
      jobs[id] = { ...(jobs[id] || {}), at: d.toISOString(), action: 'missed: a run was busy for the whole slot', ok: true };
      delete pending[id];
      continue;
    }
    due.set(id, { job, since });
  }

  const errors = [];
  if (due.size && !env.GH_DISPATCH_TOKEN) {
    errors.push('GH_DISPATCH_TOKEN secret is not set');
  } else {
    for (const [id, { job, since }] of due) {
      let res;
      try { res = await startJob(env, job, nowMs); } catch (e) { res = { ok: false, action: `error: ${e.message}`, retry: true }; }
      jobs[id] = { at: d.toISOString(), action: res.action, ok: res.ok, ...(res.action === 'started' ? { lastStart: d.toISOString() } : { lastStart: (jobs[id] || {}).lastStart || null }) };
      if (res.retry) pending[id] = since; else delete pending[id];
      if (!res.ok) errors.push(`${id}: ${res.action}`);
    }
  }

  const out = { tick: d.toISOString(), tokenSet: !!env.GH_DISPATCH_TOKEN, errors, jobs, pending };
  if (kv) {
    try { await kv.put('status', JSON.stringify(out)); } catch (e) { /* status is best effort */ }
  }
  if (errors.length) console.log('scheduler: ' + errors.join(' | '));
  return out;
}

export async function schedulerStatus(env) {
  let st = null;
  try { st = env.SCHEDULER_KV ? await env.SCHEDULER_KV.get('status', 'json') : null; } catch (e) { st = null; }
  const body = st || { tick: null, note: 'no tick recorded yet' };
  return new Response(JSON.stringify({ ...body, tokenSet: !!env.GH_DISPATCH_TOKEN, timetable: JOBS.map((j) => ({ id: j.id, workflow: j.workflow })) }, null, 1), {
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'x-robots-tag': 'noindex' },
  });
}
