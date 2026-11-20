// Test fixture locations. Saved copies of live pages live in test/fixtures/dyn and
// test/fixtures/audit; set RTT_DYN or FIXTURES to use copies kept somewhere else.
import { existsSync } from 'node:fs';
const here = (p) => new URL(p, import.meta.url).pathname;
export const DYN = process.env.RTT_DYN || (existsSync(here('./fixtures/dyn/')) ? here('./fixtures/dyn/') : '/home/claude/dyn/');
export const FIX = process.env.FIXTURES || (existsSync(here('./fixtures/audit')) ? here('./fixtures/audit') : '/home/claude/audit');
