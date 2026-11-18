// Makes the minified bundle a single line (template literals that hold a newline
// become "\n" strings) so it can be pasted or typed into the Cloudflare editor.
import { readFileSync, writeFileSync } from 'node:fs';
const p = new URL('../deploy/rtt-hreflang.min.js', import.meta.url);
const s = readFileSync(p, 'utf8').replace(/\n$/, '').replaceAll('`\n`', '"\\n"');
if (s.includes('\n')) throw new Error('bundle still has a line break');
writeFileSync(p, s + '\n');
