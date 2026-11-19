# Squarespace sync

The Worker heals every Christmas events page as it is served. This sync writes the same
corrections back into the stored Squarespace posts, so the editor, RSS, search snippets and any
copy served without the Worker say exactly what the live site says.

* Same code as the Worker: `worker/src/sqsp.js` calls the healer in `worker/src/heal.js`.
* Source of truth: `tools/truth/live.json`, rebuilt every 3 hours by the GitHub workflow.
* What it updates per post:
  * SEO title and SEO description
  * Post title (only counts, never years or dates)
  * Excerpt
  * Code and text blocks: counts, filter totals, structured data, and past events removed
* Which posts: every path in `tools/sqsp/ids.json` (Squarespace post ids, refreshed by the truth build).
  A post is checked again when its live counts change, and at least once a week.
* What it never touches: posts outside `/christmas-events/`, drafts, and posts edited in the
  last 15 minutes.

## Running it

It runs in a signed-in Squarespace admin tab (it uses the admin session, no API key needed).
Open `https://rally-takes-the-train-site.squarespace.com/config/pages`, then in the console:

```js
const src = await fetch('https://raw.githubusercontent.com/stridematt/sitemaps/main/tools/sqsp/rtt-sqsp-sync.js').then(r => r.text());
(0, eval)(src + ';window.RTTSync=RTTSync;');
const dry = await RTTSync.run({ apply: false });   // report only
dry.plans                                           // what would change, per post
const done = await RTTSync.run({ apply: true });    // write (up to 400 posts per run)
```

Options for `run`:

* `apply`: false for a dry run (default false)
* `limit`: most posts written per run (default 400)
* `delayMs`: pause between writes (default 400)
* `quietMinutes`: skip posts edited this recently (default 15)
* `only`: an array of paths to limit the run to

## Backups and undo

Before every write the post's full previous version is saved in the browser (IndexedDB
`rtt-sqsp-sync`). To put a post back:

```js
await RTTSync.backups('/christmas-events/denver-co')   // list saved versions
await RTTSync.restore('/christmas-events/denver-co')   // restore the latest one
```

## Build and test

```sh
cd worker
npm run bundle:sqsp   # writes tools/sqsp/rtt-sqsp-sync.js
npm run test:sqsp
```
