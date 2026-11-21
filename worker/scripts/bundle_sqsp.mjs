import fs from 'node:fs';
const strip = (src) => src.replace(/^import .*$/mg, '').replace(/^export (async function|function|const|let|class) /mg, '$1 ');
const heal = strip(fs.readFileSync('src/heal.js', 'utf8'));
const sqsp = strip(fs.readFileSync('src/sqsp.js', 'utf8'));
const out = `// Built from worker/src/heal.js and worker/src/sqsp.js (same code as the Worker). Rebuild: node scripts/bundle_sqsp.mjs
var RTTSync = (() => {
const { healCity, healGuide, refToday, claimedCounts } = (() => {
${heal}
return { healCity, healGuide, refToday, claimedCounts };
})();
${sqsp}
return { backups, describe, htmlBlocks, kindFor, planItem, restore, run, signature };
})();
`;
fs.writeFileSync('../tools/sqsp/rtt-sqsp-sync.js', out);
console.log('written', out.length);
