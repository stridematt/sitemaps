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

Deployed in Cloudflare as the Worker `rtt-hreflang` (account hello@rallytakesthetrain.com) on the routes in `tools/worker-routes.txt` (the Christmas and other international sections plus `/hreflang-sitemap.xml`), with its workers.dev and preview URLs turned off. Favicon, uploaded files, Squarespace API beacons, the blog, shop and other pages never start the Worker. Pages in those sections that aren't clustered pass straight through without their body being read. If a clustered page ever falls outside these routes, the 3-hour job flags it in the review issue. Redeploy only when the Worker code changes: `cd worker && npm install && npm run bundle && npm test`, then paste `worker/deploy/rtt-hreflang.min.js` into the Worker in the Cloudflare editor and deploy (or `npx wrangler deploy` with an API token). Each tagged page gets an `x-rtt-hreflang: tagged` response header, which is an easy way to check it.

## Hosting

`sitemaps.rallytakesthetrain.com` needs a DNS record in Cloudflare (the domain's DNS host): CNAME `sitemaps` to `stridematt.github.io`, set to DNS only (grey cloud) so GitHub Pages can serve its HTTPS certificate. Submit the sitemap in the `rallytakesthetrain.com` Domain property in Google Search Console, which covers both the `sitemaps` and `www` hosts.
