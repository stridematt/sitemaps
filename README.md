# Rally Takes the Train sitemaps

Static files served at https://sitemaps.rallytakesthetrain.com/ through GitHub Pages.

- `hreflang-sitemap.xml`: language and region alternates for the international pages on https://www.rallytakesthetrain.com/. Generated; do not edit by hand.
- `tools/clusters.json`: the source for the hreflang sitemap. Each cluster is one guide in its different languages or countries, with its x-default.
- `tools/build_hreflang.py`: checks `clusters.json` (valid codes, no page in two clusters, no code used twice in a cluster, x-default present) and writes `hreflang-sitemap.xml`.
- `tools/auto_pair.py`: runs every 3 hours in GitHub Actions. Reads the site sitemap, opens pages it hasn't seen before and adds them to `clusters.json` when the site itself declares them as language versions of each other, then rebuilds the sitemap and commits. Sources it trusts: the cluster list in the site-wide Squarespace language script, each page's language switcher link (the `rtt-post__meta` line, e.g. "Lire en français"), and matching Christmas Eve denomination URLs across countries. Every page must be live, canonical to itself, indexable and declare the expected language. Doubtful cases go to the review issue instead.
- `tools/find_unpaired.py`: pattern check run with the job above; lists likely pairs by URL and clustered pages that no longer exist.
- Both report to one GitHub issue, "hreflang: pages to review", which closes itself when everything is paired. Rejected suggestions go in `tools/hreflang-ignore.txt`.
- `worker/`: the Cloudflare Worker on www.rallytakesthetrain.com (see below).
- `CNAME`: the custom domain for GitHub Pages
- `llms-full.txt` and `llms.txt`: the complete AI guide to https://www.rallytakesthetrain.com/ with every address written in full. The version served at https://www.rallytakesthetrain.com/llms.txt lists the same pages, with the three large directories written as site paths.
- `robots.txt`: allows crawling and points to the sitemap

## What the hreflang sitemap covers

- Christmas events for kids: the country hub (`/christmas-events-for-kids` for the U.S. plus every country guide, including the English country guides as `en-<country>`), and each city guide paired with its local-language version.
- Christmas Eve services: the hub (`/christmas-eve-services-near-me`) with Canada, the UK and Quebec (French), and each denomination page across those countries.
- Christmas train rides: the U.S. page with the UK, Germany, Austria, Switzerland, France and Italy pages.

## Adding pages

New translated pages are paired automatically within about 3 hours if the site declares them (site script cluster list or the page's language switcher). To add or fix one by hand:

1. Add a cluster, or a page to an existing cluster, in `tools/clusters.json`.
2. Run `python3 tools/build_hreflang.py`.
3. Commit `tools/clusters.json` and `hreflang-sitemap.xml` together.

A page that has no version in another language or country does not need an entry.

## Cloudflare Worker (`worker/`)

Runs on `www.rallytakesthetrain.com/*` and reads `tools/clusters.json` from this repo (refreshed every 5 minutes, with a bundled copy as a fallback):

- Adds `<link rel="alternate" hreflang>` tags for the whole cluster, plus x-default, to every clustered page, and sets `<html lang>` to the page's language.
- Serves the hreflang sitemap at https://www.rallytakesthetrain.com/hreflang-sitemap.xml (submit this one in Search Console). Its robots.txt code is inactive: `/robots.txt` has its own route to the rally-indexnow Worker, which takes priority.
- On clustered pages, switches off the old hreflang tags that the site-wide Squarespace language script adds in the browser (their link tags get `rel="x-rtt-hreflang-off"`), so Google only sees the Worker's set. The script still sets the page language, content-language and og:locale.
- Edge cache: anonymous GET requests in these sections are cached at Cloudflare for 5 minutes (404s for 1 minute, errors never), using Tiered Cache, so visitors and crawlers worldwide get pages from a nearby data center. Skipped for signed-in, cart or password cookies (`SiteUserInfo`, `SiteUserSecureAuthToken`, `siteUserCrumb`, `_acloggedin`, `hasCart`, `Locked`, `SQ_LANGUAGE_SESSION`), Squarespace special URLs (`?format=`, `?nochrome`, `?preview`, `?password`) and non-GET requests. Ad tracking parameters (`utm_*`, `fbclid`, `gclid`...) are dropped before the request reaches Squarespace so they don't split the cache. Browsers are told `no-cache`, so they always check back with the edge. An edited page shows up within 5 minutes; to see it sooner, purge that URL in Cloudflare (Caching, Configuration, Purge cache).
- Leaves everything else untouched. If anything fails, the original Squarespace page is returned.

A commit to `clusters.json` goes live on the site within about 5 minutes, with no redeploy. It reads the data from GitHub, then the GitHub Pages copy, then the last good copy saved in Cloudflare's cache; if none are available, pages pass through untouched.

Deployed in Cloudflare as the Worker `rtt-hreflang` (account hello@rallytakesthetrain.com) on the routes in `tools/worker-routes.txt` (the Christmas and other international sections plus `/hreflang-sitemap.xml`), with its workers.dev and preview URLs turned off. Favicon, uploaded files, Squarespace API beacons, the blog, shop and other pages never start the Worker. Pages in those sections that aren't clustered pass straight through without their body being read. If a clustered page ever falls outside these routes, the 3-hour job flags it in the review issue. Redeploy only when the Worker code changes: `cd worker && npm install && npm run bundle && npm test`, commit and push, then upload `worker/deploy/rtt-hreflang.min.js` through the Cloudflare API (`PUT /accounts/{account}/workers/scripts/rtt-hreflang/content`, from a signed-in dashboard tab or with an API token, or `npx wrangler deploy`). The dashboard code editor freezes on this bundle, so don't paste it there. Test fixtures (saved live pages) go in `worker/test/fixtures/dyn` and `worker/test/fixtures/audit`, or set `RTT_DYN` and `FIXTURES`. GitHub Actions (`.github/workflows/worker.yml`) runs on every change to `worker/`: it saves fresh copies of the test pages from Squarespace, rebuilds the bundle, runs every test including the Miniflare suite, and on main commits the rebuilt `worker/deploy/rtt-hreflang.min.js`. The tests work out what to expect from whatever copy of the pages they get, so they don't go stale as events pass. Each tagged page gets an `x-rtt-hreflang: tagged` response header, which is an easy way to check it.

## Hosting

`sitemaps.rallytakesthetrain.com` needs a DNS record in Cloudflare (the domain's DNS host): CNAME `sitemaps` to `stridematt.github.io`, set to DNS only (grey cloud) so GitHub Pages can serve its HTTPS certificate. Submit the sitemap in the `rallytakesthetrain.com` Domain property in Google Search Console, which covers both the `sitemaps` and `www` hosts.

## llms.txt

`llms.txt` and `llms-full.txt` are rebuilt from the live site every 3 hours by the same GitHub Action (`tools/llms/build_llms.py`) and served at https://www.rallytakesthetrain.com/llms.txt and /llms-full.txt by the Worker (routes `www.rallytakesthetrain.com/llms.txt` and `/llms-full.txt`).

- Hand-written parts (book facts, guides, museums, policies, the Optional list) live in `tools/llms/template.md`. Edit that file to change them; the `{{...}}` placeholders are filled in by the build.
- Built from the site each run: the Christmas events directory (the A to Z list on /christmas-events-for-kids plus any English city guide in sitemap.xml not yet in that list), the six Christmas Eve sections (every page, via ?format=json), counts, the language list (codes from `tools/clusters.json`), and a "Pages added recently" list for any other new page in sitemap.xml that the template does not mention yet.
- Hand-picked "Start at" links per language (the Christmas train pages) are in `tools/llms/start_links.json`.
- Page titles already looked up are kept in the Actions cache (`.state/llms-titles.json`), so each run only fetches new pages.
- The build refuses to write if the new file has fewer than 95% of the last file's links, a section is missing, or a placeholder is left over, so a bad run never replaces a good file.
- The Worker serves the GitHub copy (cached 5 minutes at Cloudflare), then the GitHub Pages copy, then the last good copy saved in Cloudflare's cache, then Squarespace's own llms.txt.

## Live counts (self-healing numbers)

Every number on the Christmas events pages that changes as the site grows or as the season goes by (events, free events, cities, countries, filter totals, FAQ answers, titles and descriptions) is corrected from one source of truth.

- `tools/truth/build_truth.py` runs every 3 hours in GitHub Actions. It finds city guides from the hub finder and A to Z, from English U.S. and Canada guides in sitemap.xml, and from the city cards on every country and state guide (so a new city counts as soon as its guide links it). It reads every city guide's event cards (dates and free flags), drops events whose last day has passed, and writes `tools/truth/live.json`: totals, countries, U.S. states and Canadian provinces, every city page and every country or state guide. Every page is re-read every run (the sitemap lastmod lags, so it is not trusted), and each city is counted once using its fuller language version. New country and region guides are found from the newest-posts feed and crawled down to their cities. It also writes `tools/sqsp/ids.json` (each page's Squarespace post id).
- A page filed as a U.S. city whose own markup says another country (`data-ke-country`, else its events' `addressCountry`) is left out of the U.S. counts and logged: state codes double as country codes in slugs (`-co` Colombia/Colorado, `-de` Germany/Delaware, `-ca` Canada/California...).
- The Worker (`worker/src/heal.js`) reads `live.json` every 5 minutes and corrects the hub (`/christmas-events-for-kids`), every country and state guide, and every city page as it serves them: past events removed, every count phrase rewritten in about 30 languages (dates, times, ages, prices and years are never touched). Healed pages carry the header `x-rtt-counts: healed` (or `clean` when nothing was stale).
- The hub leads with event counts: each country row reads "N events in M cities", and the city finder shows each city's events.
- Tests: `cd worker && node test/heal.test.mjs && npm test`.

## Squarespace sync (`tools/sqsp/`)

Writes the same corrections back into the stored Squarespace posts (SEO title, SEO description, excerpt, post title, and the code blocks), so Squarespace itself matches the live site. It runs in a signed-in Squarespace admin tab, keeps a backup of every post before writing it, skips drafts and posts edited in the last 15 minutes, and skips any post where it finds a count it cannot read (those are listed for a hand fix). See `tools/sqsp/README.md`.

## sitemap.xml (self-maintaining)

Squarespace's own sitemap lags behind new pages and keeps URLs that now return 404 or redirect. `tools/sitemap/build_fix.py` runs every 3 hours in GitHub Actions and writes `tools/sitemap/fix.json`:

- **Added:** every live, indexable Christmas events city page and country or state guide, every Christmas Eve page, and the new address of any renamed page, when Squarespace's sitemap does not list them yet. Each is checked first: it must return 200, have no noindex, and be canonical to itself. Once Squarespace lists a page itself, it drops off the add list.
- **Removed:** URLs in Squarespace's sitemap that return 404/410 or redirect. Every URL is re-checked about every two days (3,000 per run, plus everything that failed last time). If Squarespace rate-limits the sitemap.xml fetch (429 right after the counts crawl), it waits and retries up to 6 times, then keeps the previous list rather than failing the job. If a run would remove more than 3% of the sitemap at once, it keeps the previous list instead (an outage, not real deletions).

The Worker applies `fix.json` as https://www.rallytakesthetrain.com/sitemap.xml is served (header `x-rtt-sitemap: fixed +N -M`). A request with the header `x-rtt-raw: 1` gets Squarespace's own copy. If the fix list can't be loaded, or the result would pass the 50,000 URL limit, Squarespace's sitemap is served unchanged.

Since 2026-11-25 the site has more than 50,000 URLs, so Squarespace serves `/sitemap.xml` as an index of `sitemap0.xml`, `sitemap1.xml`, ... and lists those files by relative name, which the sitemap protocol does not allow. The Worker (route `www.rallytakesthetrain.com/sitemap*`) then serves:

- `/sitemap.xml`: the index with every file as a full URL, plus `/sitemap-new-pages.xml` when there are pages to add (`x-rtt-sitemap: index N files +new-pages M`)
- `/sitemapN.xml`: Squarespace's file with the dead URLs dropped (`x-rtt-sitemap: fixed +0 -M`)
- `/sitemap-new-pages.xml`: the pages Squarespace does not list yet (`x-rtt-sitemap: new pages M`)

Every script that reads URLs from the sitemap follows the index through `tools/sitemap/sitemap_read.py` (`SR.expand(text, url, fetch)`; tests: `python3 tools/sitemap/test_sitemap_read.py`), and so do `tools/sqsp/link_cards.js` and the rally-events sitemap audit. A new script that reads `/sitemap.xml` should use it too.
