// Run with node tests/nas/test_pack_format.cjs; no dependencies.
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = readFileSync(require('node:path').join(__dirname, '../../nas-lz4/ui.html'), 'utf8');
for (const [, script] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(script);
const elements = new Map();
const document = {getElementById: id => {
  if (!elements.has(id)) elements.set(id, {value: '', checked: true, innerHTML: '', textContent: ''});
  return elements.get(id);
}};
let mode;
const context = vm.createContext({document, esc: s => String(s ?? '').replaceAll('<', '&lt;'), data: null,
  packMode: 'zstd', packLevel: 5, packProfile: true, selectPackMode: m => { mode = m; context.packMode = m; },
  render: () => {}});
vm.runInContext(html.slice(html.indexOf('// The format the Compress buttons'), html.indexOf('// My games\' sub-tabs')), context);
// Only Zstd is packed: no format choice, no LZ4 anywhere in the controls.
assert.ok(!html.includes('id="t-zstd"') && !html.includes('id="p-zstd"') && !html.includes("'#zstd'"));
assert.ok(html.includes('<div id="fmtbar"></div>'));
vm.runInContext('renderFmtBar()', context);
let bar = document.getElementById('fmtbar').innerHTML;
assert.ok(bar.includes('🗜 Zstd') && !bar.includes('LZ4') && !bar.includes('setPackMode(') && bar.includes('max="22"'));
vm.runInContext(html.slice(html.indexOf('function canPack('), html.indexOf('function packControls(')), context);
const games = {
  source: {id: 'source', can_queue: true}, noAmpr: {id: 'n', can_queue: false},
  zstdDone: {id: 'z', pack_codec: 'zstd', output: '/zstd/z'}, lz4Done: {id: 'l', pack_codec: 'lz4', output: '/lz4/l'},
  running: {id: 'r', can_queue: true, running: true}, folder: {id: 'f', output_only: true}};
const can = (g, m) => vm.runInContext(`canPack(${JSON.stringify(g)}${m ? `, '${m}'` : ''})`, context);
assert.ok(can(games.source) && can(games.noAmpr) && can(games.lz4Done));
assert.ok(!can(games.zstdDone) && !can(games.running) && !can(games.folder) && !can(games.source, 'ng'));
assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext('packOptions()', context))), {codec: 'zstd', runtime: 'ng', level: 5, profile: true});
// The Compress dialog only offers Zstd and sends it.
const ctx2 = vm.createContext({document: {getElementById: () => null, body: {insertAdjacentHTML() {}}}, data: {games: [], settings: {}},
  packMode: 'zstd', packLevel: 5, packProfile: true, savePackPrefs() {}, renderFmtBar() {}, localStorage: {getItem: () => null, setItem() {}},
  compress: (...a) => { ctx2.sent = a; }});
vm.runInContext(html.slice(html.indexOf('// The Compress dialog:'), html.indexOf('function convertGame(id, codec)')), ctx2);
vm.runInContext("pk = {id: 'g', g: {can_queue: false}, mode: 'zstd', level: 7, profile: true, remember: false}; pkPick('lz4')", ctx2);
assert.equal(vm.runInContext('pk.mode', ctx2), 'zstd');
vm.runInContext("pk.remember = true; pkGo(true)", ctx2);
assert.deepEqual(JSON.parse(JSON.stringify(ctx2.sent)), ['g', true, false, {codec: 'zstd', runtime: 'ng', level: 7, profile: true}, false]);
assert.equal(vm.runInContext('packSkip && packMode', ctx2), 'zstd');
// My games' sub-tabs list each copy in its own tab, escaped, with its own folder name on the buttons.
const ctx3 = vm.createContext({document, esc: s => String(s ?? '').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
  gb: n => String(n), PS5_EN: {works: 'Works'}, KIND_EN: {exfat: 'exFAT image'}, xferText: () => ''});
vm.runInContext(html.slice(html.indexOf("let libTab = 'orig'"), html.indexOf('// Whether a game can be compressed in the chosen format now.')), ctx3);
ctx3.d = {copies: [{id: 'G-lz4', game: 'G', codec: 'lz4', runtime: 'legacy', name: '<b>G', title_id: 'PPSA00001', bytes: 1, source_bytes: 2, saved_percent: 50},
                   {id: 'G-zstd', game: 'G', codec: 'zstd', runtime: 'ng', name: 'G', bytes: 1},
                   {id: 'src:I', game: 'I', codec: 'lz4', kind: 'exfat', name: 'Imported', bytes: 1}],
          games: [{id: 'G', verdict: 'LZ4', output: '/output/G-lz4'}, {id: 'I', source_codec: 'lz4'}, {id: 'only', output_only: true}]};
const lz4 = vm.runInContext("copiesHtml(d, 'lz4')", ctx3), zs = vm.runInContext("copiesHtml(d, 'zstd')", ctx3);
assert.equal(vm.runInContext('originalGames(d).map(g => g.id).join()', ctx3), 'G');
vm.runInContext('renderLibTabs(d)', ctx3);
assert.ok(document.getElementById('libtabs').innerHTML.includes('Folder / exFAT <span class="n">1'));
assert.ok(document.getElementById('libtabs').innerHTML.includes('⚡ LZ4 <span class="n">2'));
assert.ok(lz4.includes('exFAT image') && lz4.includes('data-id="I" onclick="pushSrc(this.dataset.id)"'));
assert.ok(!lz4.slice(lz4.indexOf('Imported')).includes('Delete copy'));
assert.ok(lz4.includes('data-id="G-lz4"') && !lz4.includes('G-zstd') && lz4.includes('APR-EMU') && !lz4.includes('<b>G'));
assert.ok(zs.includes('data-id="G-zstd"') && !zs.includes('data-id="G-lz4"') && zs.includes('ampr-emu-ng'));
assert.ok(!/\n\n/.test(lz4.replace(/\s+/g, ' ')) && lz4.includes("?\\n\\n"));  // confirm text stays one line in onclick
console.log('Copy tab tests passed');
console.log('Compress dialog tests passed');
console.log('Format switch tests passed');

// TOML profiles are gone: no editor, no chooser, no TOML switch.
assert.ok(!html.includes('profile-editor') && !html.includes('openProfile') && !/TOML profile/.test(html));
console.log('No TOML tests passed');
