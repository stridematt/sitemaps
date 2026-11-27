// Unit tests for the Cloudflare scheduler (src/scheduler.js): timetable, skip rules, retries, status.
import assert from 'node:assert/strict';
import { JOBS, decide, runScheduler } from '../src/scheduler.js';

let n = 0;
const t = async (name, fn) => { await fn(); n++; console.log('ok  ', name); };
const MIN = 60 * 1000;
const at = (iso) => Date.parse(iso);
const byId = (id) => JOBS.find((j) => j.id === id);

function kv() {
  const m = new Map();
  return { get: async (k, type) => (m.has(k) ? (type === 'json' ? JSON.parse(m.get(k)) : m.get(k)) : null), put: async (k, v) => m.set(k, v), m };
}

// A fake GitHub: runs per workflow, records dispatches.
function fakeGitHub(runsByWf = {}, { dispatchStatus = 204, runsStatus = 200 } = {}) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const u = new URL(url);
    const wf = (u.pathname.match(/workflows\/([^/]+)\//) || [])[1];
    if (u.pathname.endsWith('/dispatches')) {
      calls.push({ wf, body: JSON.parse(init.body), auth: init.headers.authorization });
      return new Response(dispatchStatus === 204 ? null : '{"message":"Bad credentials"}', { status: dispatchStatus });
    }
    return new Response(JSON.stringify({ workflow_runs: runsByWf[wf] || [] }), { status: runsStatus });
  };
  return calls;
}

await t('timetable: counts hourly at :50, full every 3 hours at :20, health hourly at :40', () => {
  const due = (iso) => JOBS.filter((j) => j.when(new Date(iso).getUTCHours(), Math.floor(new Date(iso).getUTCMinutes() / 10) * 10)).map((j) => j.id).sort();
  assert.deepEqual(due('2026-11-27T05:50:00Z'), ['hreflang-counts']);
  assert.deepEqual(due('2026-11-27T06:20:00Z'), ['hreflang-full']);
  assert.deepEqual(due('2026-11-27T05:20:00Z'), []);
  assert.deepEqual(due('2026-11-27T05:40:00Z'), ['counts-health', 'services-counts']);
  assert.deepEqual(due('2026-11-27T06:40:00Z'), ['counts-health', 'indexnow-recent', 'services-counts']);
  assert.deepEqual(due('2026-11-27T05:30:00Z'), ['verify-live']);
  // each hour has exactly one counts start
  let counts = 0;
  for (let mi = 0; mi < 60; mi += 10) if (byId('hreflang-counts').when(5, mi)) counts++;
  assert.equal(counts, 1);
});

await t('decide: start when nothing ran; skip and retry while one runs; skip a slot already covered', () => {
  const now = at('2026-11-27T05:50:00Z');
  const job = byId('hreflang-counts');
  assert.deepEqual(decide([], job, now), { start: true });
  const running = decide([{ status: 'in_progress', event: 'schedule', created_at: '2026-11-27T05:35:00Z' }], job, now);
  assert.equal(running.start, false); assert.equal(running.retry, true);
  const covered = decide([{ status: 'completed', event: 'schedule', created_at: '2026-11-27T05:35:00Z', updated_at: '2026-11-27T05:46:00Z' }], job, now);
  assert.equal(covered.start, false); assert.equal(covered.retry, false);
  // a scheduled run that stepped aside (done in seconds) does not cover the slot
  assert.deepEqual(decide([{ status: 'completed', event: 'schedule', created_at: '2026-11-27T05:45:00Z', updated_at: '2026-11-27T05:45:20Z' }], job, now), { start: true });
  assert.deepEqual(decide([{ status: 'completed', event: 'workflow_dispatch', created_at: '2026-11-27T04:50:00Z' }], job, now), { start: true });
});

await t('tick starts the due job with its inputs and records the status', async () => {
  const calls = fakeGitHub();
  const env = { GH_DISPATCH_TOKEN: 'tok', SCHEDULER_KV: kv() };
  const out = await runScheduler(env, at('2026-11-27T06:20:30Z'));
  assert.deepEqual(calls.map((c) => [c.wf, c.body]), [['hreflang.yml', { ref: 'main', inputs: { mode: 'full' } }]]);
  assert.equal(calls[0].auth, 'Bearer tok');
  assert.equal(out.jobs['hreflang-full'].action, 'started');
  assert.equal(out.errors.length, 0);
  assert.equal((await env.SCHEDULER_KV.get('status', 'json')).tick, '2026-11-27T06:20:30.000Z');
});

await t('push runs (file checks) do not count as the job having run', async () => {
  const calls = fakeGitHub({ 'hreflang.yml': [{ status: 'in_progress', event: 'push', created_at: '2026-11-27T05:49:00Z' }] });
  await runScheduler({ GH_DISPATCH_TOKEN: 'tok', SCHEDULER_KV: kv() }, at('2026-11-27T05:50:00Z'));
  assert.equal(calls.length, 1);
});

await t('a full run blocked by a running counts job is retried on the next ticks until it starts', async () => {
  const store = kv();
  const env = { GH_DISPATCH_TOKEN: 'tok', SCHEDULER_KV: store };
  let calls = fakeGitHub({ 'hreflang.yml': [{ status: 'in_progress', event: 'workflow_dispatch', created_at: '2026-11-27T05:50:00Z' }] });
  let out = await runScheduler(env, at('2026-11-27T06:20:00Z'));
  assert.equal(calls.length, 0);
  assert.ok(out.pending['hreflang-full']);
  calls = fakeGitHub({ 'hreflang.yml': [{ status: 'completed', event: 'workflow_dispatch', created_at: '2026-11-27T05:50:00Z' }] });
  out = await runScheduler(env, at('2026-11-27T06:30:00Z'));
  assert.deepEqual(calls.filter((c) => c.wf === 'hreflang.yml').map((c) => c.body.inputs), [{ mode: 'full' }]);
  assert.equal(out.pending['hreflang-full'], undefined);
});

await t('a retry that never finds a free slot expires quietly (not an error)', async () => {
  const store = kv();
  const env = { GH_DISPATCH_TOKEN: 'tok', SCHEDULER_KV: store };
  fakeGitHub({ 'hreflang.yml': [{ status: 'in_progress', event: 'workflow_dispatch', created_at: '2026-11-27T05:50:00Z' }] });
  await runScheduler(env, at('2026-11-27T05:50:00Z'));
  const out = await runScheduler(env, at('2026-11-27T06:30:00Z'));
  assert.equal(out.pending['hreflang-counts'], undefined);
  assert.match(out.jobs['hreflang-counts'].action, /^missed/);
  assert.equal(out.errors.length, 0);
});

await t('a bad token is reported as an error, and a missing token is reported without calling GitHub', async () => {
  fakeGitHub({}, { dispatchStatus: 401 });
  const bad = await runScheduler({ GH_DISPATCH_TOKEN: 'old', SCHEDULER_KV: kv() }, at('2026-11-27T05:40:00Z'));
  assert.equal(bad.errors.length, 2);
  assert.match(bad.errors[0], /HTTP 401/);
  const calls = fakeGitHub();
  const none = await runScheduler({ SCHEDULER_KV: kv() }, at('2026-11-27T05:40:00Z'));
  assert.equal(calls.length, 0);
  assert.equal(none.tokenSet, false);
  assert.match(none.errors[0], /GH_DISPATCH_TOKEN/);
});

await t('nothing due: no GitHub calls, still records the tick', async () => {
  const calls = fakeGitHub();
  const out = await runScheduler({ GH_DISPATCH_TOKEN: 'tok', SCHEDULER_KV: kv() }, at('2026-11-27T05:00:00Z'));
  assert.equal(calls.length, 0);
  assert.equal(out.tick, '2026-11-27T05:00:00.000Z');
});

console.log(`\n${n} scheduler tests passed`);
