# Rally Takes the Train sitemaps

Static files served at https://sitemaps.rallytakesthetrain.com/ through GitHub Pages.

- `hreflang-sitemap.xml`: language and region alternates for the international pages on https://www.rallytakesthetrain.com/. Generated; do not edit by hand.
- `tools/clusters.json`: the source for the hreflang sitemap. Each cluster is one guide in its different languages or countries, with its x-default.
- `tools/build_hreflang.py`: checks `clusters.json` (valid codes, no page in two clusters, no code used twice in a cluster, x-default present) and writes `hreflang-sitemap.xml`.
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

## Hosting

`sitemaps.rallytakesthetrain.com` needs a DNS record in Cloudflare (the domain's DNS host): CNAME `sitemaps` to `stridematt.github.io`, set to DNS only (grey cloud) so GitHub Pages can serve its HTTPS certificate. Submit the sitemap in the `rallytakesthetrain.com` Domain property in Google Search Console, which covers both the `sitemaps` and `www` hosts.
