import { readFileSync, writeFileSync } from 'node:fs';
const src = (f) => readFileSync(new URL('../src/', import.meta.url).pathname + f, 'utf8');
function wrap(name, code) {
  const names = [...code.matchAll(/^export (?:async )?(?:function|const|let|class) ([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  if (/^import /m.test(code)) throw new Error(name + ' has imports');
  const body = code.replace(/^export (?=(?:async )?(?:function|const|let|class) )/gm, '');
  return `const __${name} = (() => {\n${body}\nreturn { ${names.join(', ')} };\n})();\n`;
}
let idx = src('index.js');
const imps = [...idx.matchAll(/^import \{([^}]+)\} from '\.\/(\w+)\.js';\n/gm)];
let head = wrap('heal', src('heal.js')) + wrap('services', src('services.js'));
for (const m of imps) { idx = idx.replace(m[0], ''); head += `const {${m[1]}} = __${m[2]};\n`; }
if (/^import /m.test(idx)) throw new Error('index still imports');
idx = idx.replace(/let BUILD = 'dev';/, "let BUILD = 'sv" + process.argv[2] + "';");
writeFileSync(new URL('../deploy/rtt-hreflang.modules-bundle.js', import.meta.url).pathname, '// rtt-hreflang (index + heal + services), sitemaps ' + process.argv[2] + '\n' + head + idx);
console.log('ok', (head + idx).length);
