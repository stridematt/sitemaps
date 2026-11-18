# Rally Takes the Train sitemaps

Static files served at https://sitemaps.rallytakesthetrain.com/ through GitHub Pages.

- `hreflang-sitemap.xml`: language and region alternates for the international pages on https://www.rallytakesthetrain.com/. Generated; do not edit by hand.
- `tools/clusters.json`: the source for the hreflang sitemap. Each cluster is one guide in its different languages or countries, with its x-default.
- `tools/build_hreflang.py`: checks `clusters.json` (valid codes, no page in two clusters, no code used twice in a cluster, x-default present) and writes `hreflang-sitemap.xml`.
- `tools/find_unpaired.py`: compares the live site sitemap with `clusters.json` and lists translated pages that aren't paired yet, plus clustered pages that no longer exist. Runs daily in GitHub Actions and opens an issue titled "hreflang: pages to review" when it finds something. Rejected suggestions go in `tools/hreflang-ignore.txt`.
- `worker/`: the Cloudflare Worker on www.rallytakesthetrain.com (see below).
- `CNAME`: the custom domain for GitHub Pages
- `llms-full.txt` and `llms.txt`: the complete AI guide to https://www.rallytakesthetrain.com/ with every address written in full. The version served at https://www.rallytakesthetrain.com/llms.txt lists the same pages, with the three large directories written as site paths.
- `robots.txt`: allows crawling and points to the sitemap

## What the hreflang sitemap covers

- Christmas events for kids: the country hub (`/christmas-events-for-kids` for the U.S. plus every country guide, including the English country guides as `en-<country>`), and each city guide paired with its local-language version.
- Christmas Eve services: the hub (`/christmas-eve-services-near-me`) with Canada, the UK and Quebec (French), and each denomination page across those countries.
- Christmas train rides: the U.S. page with the UK, Germany, Austria, Switzerland, France and Italy pages.

## Adding pages

1. Add a cluster, or a page to an existing cluster, in `tools/clusters.json`.
2. Run `python3 tools/build_hreflang.py`.
3. Commit `tools/clusters.json` and `hreflang-sitemap.xml` together.

A page that has no version in another language or country does not need an entry.

## Cloudflare Worker (`worker/`)

Runs on `www.rallytakesthetrain.com/*` and reads `tools/clusters.json` from this repo (refreshed every 5 minutes, with a bundled copy as a fallback):

- Adds `<link rel="alternate" hreflang>` tags for the whole cluster, plus x-default, to every clustered page, and sets `<html lang>` to the page's language.
- Serves the hreflang sitemap at https://www.rallytakesthetrain.com/hreflang-sitemap.xml (submit this one in Search Console). Its robots.txt code is inactive: `/robots.txt` has its own route to the rally-indexnow Worker, which takes priority.
- Leaves every other request untouched. If anything fails, the original Squarespace page is returned.

A commit to `clusters.json` goes live on the site within about 5 minutes, with no redeploy. It reads the data from GitHub, then the GitHub Pages copy, then the last good copy saved in Cloudflare's cache; if none are available, pages pass through untouched.

Deployed in Cloudflare as the Worker `rtt-hreflang` (account hello@rallytakesthetrain.com) on the route `www.rallytakesthetrain.com/*`, with its workers.dev and preview URLs turned off. Redeploy only when the Worker code changes: `cd worker && npm install && npm run bundle && npm test`, then paste `worker/deploy/rtt-hreflang.min.js` into the Worker in the Cloudflare editor and deploy (or `npx wrangler deploy` with an API token). Each tagged page gets an `x-rtt-hreflang: tagged` response header, which is an easy way to check it.

## Hosting

`sitemaps.rallytakesthetrain.com` needs a DNS record in Cloudflare (the domain's DNS host): CNAME `sitemaps` to `stridematt.github.io`, set to DNS only (grey cloud) so GitHub Pages can serve its HTTPS certificate. Submit the sitemap in the `rallytakesthetrain.com` Domain property in Google Search Console, which covers both the `sitemaps` and `www` hosts.
