// Run with node tests/nas/test_pkg_groups.cjs; no dependencies.
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
const context = vm.createContext({document, esc: s => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'), gb: n => String(n), pkgOnPs5: null,
  PKG_TABS: {pkg: {ps4: false}, ps4: {ps4: true}}, PKG_FOLDER: {}});
vm.runInContext(html.slice(html.indexOf('const pkgShown = {}'), html.indexOf('async function pkgInstallAll(k)')), context);
const pkg = (id, tid, category='Game', name='Test') => ({id, title_id: tid, category, name, file: id+'.pkg', size: 1});
const packages = [pkg('update','PPSA01234','Update'), pkg('dlc','PPSA01234','DLC'), pkg('base','PPSA01234'),
  pkg('other','PPSA56789'), pkg('unknown1',''), pkg('unknown2',''), {...pkg('ps4','CUSA01234'), ps4: true}];
context.data = {pkgs: packages, settings: {}, games: []};
vm.runInContext("renderPkgTab(data, 'pkg')", context);
let list = document.getElementById('pkg-list').innerHTML;
assert.equal((list.match(/class="pkg-group"/g) || []).length, 1);
assert.ok(list.includes('3 packages'));
assert.ok(list.includes('1 Game · 1 Update · 1 DLC'));
assert.ok(list.indexOf('base.pkg') < list.indexOf('update.pkg'));
assert.ok(list.indexOf('update.pkg') < list.indexOf('dlc.pkg'));
assert.ok(list.includes('<tbody hidden>'));
assert.ok(!list.includes('ps4.pkg'));
assert.equal(vm.runInContext('pkgShown.pkg.length', context), 6);
vm.runInContext("togglePkgGroup('pkg', 'PPSA01234')", context);
assert.ok(!document.getElementById('pkg-list').innerHTML.includes('<tbody hidden>'));
vm.runInContext("renderPkgTab(data, 'pkg')", context);
assert.ok(document.getElementById('pkg-list').innerHTML.includes('aria-expanded="true"'));
document.getElementById('pkg-k').value = 'DLC';
vm.runInContext("renderPkgTab(data, 'pkg')", context);
assert.equal(vm.runInContext('pkgShown.pkg.join()', context), 'dlc');
assert.ok(!document.getElementById('pkg-list').innerHTML.includes('pkg-group'));
vm.runInContext("renderPkgTab(data, 'ps4')", context);
assert.equal(vm.runInContext('pkgShown.ps4.join()', context), 'ps4');
context.data.pkgs = [pkg('safe', 'PPSA00001', 'Game', '<script>'), pkg('safe2', 'PPSA00001', 'DLC')];
document.getElementById('pkg-k').value = '';
vm.runInContext("renderPkgTab(data, 'pkg')", context);
assert.ok(!document.getElementById('pkg-list').innerHTML.includes('<script>'));
console.log('PASS: UI syntax, game grouping, category order, independent unknowns, collapse persistence, filters, install IDs, platform separation and escaping');
// Compression controls always send Zstd for ampr-emu-ng, for any game.
vm.runInContext(html.slice(html.indexOf("let packMode = 'zstd'"), html.indexOf("// quer3q's game reports")), context);
context.data = {games: [{id:'test', name:'Test', can_queue:false}], settings:{}};
context.confirm = () => true;
const notices = [], requests = [];
context.alert = text => notices.push(text);
context.act = (action, confirmation, extra) => requests.push({action, ...extra});
(async () => {
  assert.equal(vm.runInContext('packOptions().level', context), 5);
  assert.ok(vm.runInContext('packControls()', context).includes('max="22"') && !vm.runInContext('packControls()', context).includes('LZ4'));
  await vm.runInContext("compress('test', false, false)", context);
  assert.equal(requests[0].codec, 'zstd');
  assert.equal(requests[0].runtime, 'ng');
  await vm.runInContext("convertGame('test', 'lz4')", context);   // old callers still get Zstd
  assert.equal(requests[1].codec, 'zstd');
  assert.equal(requests[1].level, 5);
  vm.runInContext('packLevel = 99', context);
  await vm.runInContext("compress('test', false, false)", context);
  assert.equal(requests.length, 2);
  assert.ok(notices.length);
  console.log('PASS: Zstd-only controls, defaults, request payload and level validation');
})().catch(e => { console.error(e); process.exitCode = 1; });
