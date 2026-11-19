// Makes the minified bundle a single line (template literals that hold a newline
// become "\n" strings) so it can be pasted or typed into the Cloudflare editor.
import { readFileSync, writeFileSync } from 'node:fs';
const p = new URL('../deploy/rtt-hreflang.min.js', import.meta.url);
import { createHash } from 'node:crypto';
let s = readFileSync(p, 'utf8').replace(/\n$/, '').replaceAll('`\n`', '"\\n"');
// stamp the build so healed-page caches from older code are never reused
const id = createHash('sha256').update(s).digest('hex').slice(0, 10);
s = s.replace(/(=)"dev"/, `$1"${id}"`);
if (s.includes('\n')) throw new Error('bundle still has a line break');
writeFileSync(p, s + '\n');
