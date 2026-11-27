"""Hourly health check of the Christmas events counts. Exits 1 (and writes health.md) when something is wrong.

Checks:
  1. The hub is live and shows its total from the events directory (header x-rtt-count-source: db).
     'crawl-guard' means the directory count fell far below the page crawl: the database or its sync is suspect.
  2. The hub's number is not far below the crawl's number in live.json.
  3. The recount (hreflang.yml, counts job) succeeded in the last 3 hours, and has not failed 3 times running.
  4. The crawl's city count did not drop more than 5% from the last full run's (the Nov 26 failure: 251 towns).
  5. live.json was regenerated in the last 6 hours.
  6. The Cloudflare scheduler (worker/src/scheduler.js) ticked in the last 25 minutes, has its GitHub token,
     and its last attempts to start jobs did not fail.

Usage: GH_TOKEN=... python3 tools/truth/health_check.py   (in Actions, gh is already signed in)
"""
import datetime, json, os, re, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('GITHUB_REPOSITORY', 'stridematt/sitemaps')
HUB = 'https://www.rallytakesthetrain.com/christmas-events-for-kids'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
now = datetime.datetime.now(datetime.timezone.utc)
problems, notes = [], []


def gh(*args):
    return json.loads(subprocess.run(['gh', 'api', *args], capture_output=True, text=True, check=True).stdout)


def ts(s):
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))


live = json.load(open(os.path.join(HERE, 'live.json'), encoding='utf-8'))
crawl = live['total']['events']

# 1 and 2: the hub as visitors get it
try:
    req = urllib.request.Request(HUB + '?health=' + now.strftime('%H%M'), headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        src, html = r.headers.get('x-rtt-count-source'), r.read().decode('utf-8', 'replace')
    m = re.search(r'([\d,]+) Christmas events in [\d,]+ cities', html)
    shown = int(m.group(1).replace(',', '')) if m else None
    notes.append(f'Hub: {shown:,} events shown, source {src}' if shown else f'Hub: no total found, source {src}')
    if src != 'db':
        problems.append(f'The hub total is not coming from the events directory (x-rtt-count-source: {src}). '
                        + ('The directory count fell far below the crawl, so the database or its sync is suspect.' if src == 'crawl-guard'
                           else 'The Worker could not read the database.'))
    if shown is None:
        problems.append('The hub page does not show a total event count.')
    elif shown < 0.85 * crawl:
        problems.append(f'The hub shows {shown:,} events, far below the crawl ({crawl:,}).')
except Exception as e:
    problems.append(f'The hub page could not be read: {e}')

# 3: the full recount
try:
    runs = gh(f'repos/{REPO}/actions/workflows/hreflang.yml/runs?per_page=15')['workflow_runs']
    results = []
    for run in runs:
        if run['status'] != 'completed' or run['event'] not in ('schedule', 'workflow_dispatch'):
            continue
        jobs = gh(f'repos/{REPO}/actions/runs/{run["id"]}/jobs')['jobs']
        job = next((j for j in jobs if j['name'] == 'counts'), None)
        if job and job['conclusion'] in ('success', 'failure'):
            results.append((ts(job['completed_at']), job['conclusion'], run['html_url']))
    ok = [r for r in results if r[1] == 'success']
    if not ok or now - ok[0][0] > datetime.timedelta(hours=3):
        problems.append(f'The full recount has not succeeded in 3 hours (last success: {ok[0][0]:%Y-%m-%d %H:%M} UTC).' if ok
                        else 'The full recount has not succeeded in its last runs.')
    streak = 0
    for r in results:
        if r[1] != 'failure':
            break
        streak += 1
    if streak >= 3:
        problems.append(f'The full recount failed {streak} times in a row. Latest: {results[0][2]}')
    if ok:
        notes.append(f'Full recount: last success {ok[0][0]:%Y-%m-%d %H:%M} UTC; {streak} failures since')
except Exception as e:
    problems.append(f'Could not read the full recount runs: {e}')

# 4: city count against the previous full run
try:
    commits = gh(f'repos/{REPO}/commits?path=tools/truth/counted_events.json&per_page=2')
    if len(commits) == 2:
        url = f'https://raw.githubusercontent.com/{REPO}/{commits[1]["sha"]}/tools/truth/live.json'
        with urllib.request.urlopen(url, timeout=60) as r:
            prev = json.load(r)
        a, b = len(prev.get('cities', {})), len(live.get('cities', {}))
        notes.append(f'Cities: {b:,} now, {a:,} at the full run before')
        if b < 0.95 * a:
            gone = sorted(set(prev['cities']) - set(live['cities']))
            problems.append(f'The city count dropped from {a:,} to {b:,} ({len(gone)} gone, e.g. {", ".join(gone[:8])}).')
except Exception as e:
    notes.append(f'City comparison skipped: {e}')

# 5: live.json freshness
gen = live.get('generated')
if gen:
    age = now - datetime.datetime.strptime(gen, '%Y-%m-%dT%H:%MZ').replace(tzinfo=datetime.timezone.utc)
    notes.append(f'live.json generated {gen} ({age.total_seconds() / 3600:.1f} hours ago)')
    if age > datetime.timedelta(hours=6):
        problems.append(f'live.json has not been regenerated in {age.total_seconds() / 3600:.0f} hours.')

# 6: the Cloudflare scheduler that starts these jobs
try:
    req = urllib.request.Request('https://www.rallytakesthetrain.com/christmas-rtt-scheduler.json?h=' + now.strftime('%H%M'), headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        sch = json.load(r)
    tick = sch.get('tick')
    started = sorted((j.get('lastStart') or '' for j in (sch.get('jobs') or {}).values()), reverse=True)
    notes.append(f'Scheduler: last tick {tick}, token {"set" if sch.get("tokenSet") else "MISSING"}, last start {started[0] if started and started[0] else "none yet"}')
    if not sch.get('tokenSet'):
        problems.append('The Cloudflare scheduler has no GitHub token (GH_DISPATCH_TOKEN secret on the rtt-hreflang Worker), so it cannot start jobs.')
    if not tick or now - ts(tick) > datetime.timedelta(minutes=25):
        problems.append(f'The Cloudflare scheduler has not ticked since {tick}. Check the cron trigger on the rtt-hreflang Worker.')
    if sch.get('errors'):
        problems.append('The Cloudflare scheduler could not start jobs: ' + '; '.join(sch['errors'])
                        + ('. The GitHub token may have expired or lost access.' if any(' 401' in e or ' 403' in e or ' 404' in e for e in sch['errors']) else ''))
except Exception as e:
    problems.append(f'The Cloudflare scheduler status could not be read: {e}')

body = [f'Last checked: {now:%Y-%m-%d %H:%M} UTC', '']
body += ['**Problems**', ''] + [f'- {p}' for p in problems] + [''] if problems else ['All checks passed.', '']
body += ['**Readings**', ''] + [f'- {n}' for n in notes]
open('health.md', 'w', encoding='utf-8').write('\n'.join(body) + '\n')
print('\n'.join(body))
sys.exit(1 if problems else 0)
