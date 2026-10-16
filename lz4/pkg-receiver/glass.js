/* Images tab: one card per game with a choice of its images (the original
   exFAT / FFPFSC and the LZ4 copy's exFAT image), from the catalog's game and
   variant fields. Lines are joined without newlines: end every statement
   with ; and use no line comments. */
function groupImgs(list){var by={},out=[];
list.forEach(function(g){var k=g.game;if(!k){out.push({one:g});return;}
if(!by[k]){by[k]={vars:[]};out.push(by[k]);}by[k].vars.push(g);});
return out.map(function(x){if(x.one)return x.one;if(x.vars.length===1)return x.vars[0];
x.vars.sort(function(a,b){return (a.variant==='LZ4')-(b.variant==='LZ4');});
return {group:1,vars:x.vars,title:x.vars[0].title.replace(/ \(LZ4\)$/,'')};});}
function imgCard(x){var d=document.createElement('div');d.className='card';var sel=0;
var lead=x.vars.filter(function(v){return v.hasIcon;})[0];
var cov=lead?'<img class='+covCls(lead)+' src=http://'+pcEl.value+':9898/icon/'+encodeURIComponent(lead.id)+'>':'<div class=\"cov cov5\"><span>'+imgIcon(x.vars[0].format)+'</span></div>';
d.innerHTML=cov+'<div class=t>'+esc(x.title)+'</div><div class=vsel></div><div class=m></div>';
var vs=d.querySelector('.vsel'),m=d.querySelector('.m');
function pick(i){sel=i;var bs=vs.children;for(var k=0;k<bs.length;k++)bs[k].className=k===i?'on':'';var v=x.vars[i];
m.innerHTML='<span class=vfmt style=background:'+fmtColor(v.format)+'>'+esc((v.format||'img').toUpperCase())+'</span> &middot; '+esc(v.sizeText||'');}
x.vars.forEach(function(v,i){var b=document.createElement('button');b.textContent=v.variant||v.format;b.onclick=function(ev){ev.stopPropagation();pick(i);};vs.appendChild(b);});
pick(0);
var cb=document.createElement('button');cb.textContent='Copy to homebrew';
cb.onclick=function(ev){ev.stopPropagation();var v=x.vars[sel];copyImg(v.id,v.file||v.title,v.size||0);};
d.appendChild(cb);return d;}
/* Stay awake: a switch in the header for awake.c (on unless switched off). */
;(function(){var hd=document.querySelector('.hd');if(!hd)return;
var b=document.createElement('button');b.id='awake';b.textContent='Stay awake';
hd.insertBefore(b,document.getElementById('pcstat'));
function show(j){b.className=j.always?'on':'';b.textContent=j.always?'☀ Stay awake: on':'☾ Stay awake: off';
b.title=j.always?'The PS5 never goes to rest mode while this runs':'The PS5 stays awake only while it installs or copies';}
fetch('/api/keep-awake').then(function(r){return r.json();}).then(show).catch(function(){b.style.display='none';});
b.onclick=function(){fetch('/api/keep-awake?always='+(b.className==='on'?0:1)).then(function(r){return r.json();}).then(show);};})();
/* Installed / On PS5 marks from /api/installed (installed.c): games and
   patches by title ID and version, images by file name in the homebrew
   folders (a sent LZ4 copy is the folder <game>-lz4). */
var inst={apps:{},files:{}},reg=[];
function verNum(v){return parseFloat(String(v||'').replace(/^0+(?=\d)/,''))||0;}
function fileOn(name){var f=inst.files[name];return f?(f.dir?2:1):0;}
function imgOn(v){if(v.variant==='LZ4'&&v.game&&fileOn(v.game+'-lz4'))return 1;var f=inst.files[v.file||''];
if(!f)return 0;return f.dir||!v.size||f.size>=v.size?1:-1;}
function markOf(g){var a=g.titleId?inst.apps[g.titleId]:null;
if(g.format==='pkg'){if(!a)return '';
if(g.role==='Patch'){return verNum(a.ver)>=verNum(g.version)?'✓ Installed':(a.ver?'Not installed · game is v'+esc(a.ver):(a.patch?'✓ A patch is installed':''));}
if(g.role==='DLC')return '';return '✓ Installed'+(a.ver?' · v'+esc(a.ver):'');}
var on=imgOn(g);if(on>0)return '✓ On PS5'+(a?' · installed':'');if(on<0)return 'Partly copied';return a?'✓ Installed':'';}
function markGroup(x){var a=x.vars[0].titleId?inst.apps[x.vars[0].titleId]:null,on=x.vars.filter(function(v){return imgOn(v)>0;});
return on.length?'✓ On PS5: '+on.map(function(v){return v.variant;}).join(', ')+(a?' · installed':''):(a?'✓ Installed':'');}
function mark1(r){var t=r.x?markGroup(r.x):markOf(r.g);var el=r.d.querySelector('.inst');
if(!el){el=document.createElement('div');el.className='inst';
if(r.sub){var f=r.d.firstChild;if(f)f.appendChild(el);}else{var bs0=[].filter.call(r.d.children,function(c){return c.tagName==='BUTTON';}),b=bs0[bs0.length-1];if(b)r.d.insertBefore(el,b);else r.d.appendChild(el);}}
el.innerHTML=t;el.className='inst'+(t.charAt(0)==='✓'?'':' dim');el.style.display=t?'':'none';
if(r.x){var bs=r.d.querySelectorAll('.vsel button');for(var i=0;i<bs.length&&i<r.x.vars.length;i++){var v=r.x.vars[i];bs[i].textContent=(v.variant||v.format)+(imgOn(v)>0?' ✓':'');}}}
function marks(){reg.forEach(mark1);}
function loadInst(){fetch('/api/installed').then(function(r){return r.json();}).then(function(j){var a={},f={};
(j.apps||[]).forEach(function(x){a[x.id]=x;});(j.files||[]).forEach(function(x){f[x.path.split('/').pop()]=x;});
inst={apps:a,files:f};marks();}).catch(function(){});}
;(function(){var c0=card,i0=imgCard,r0=render;
card=function(g,sub){var d=c0(g,sub);var r={d:d,g:g,sub:sub};reg.push(r);mark1(r);return d;};
imgCard=function(x){var d=i0(x);var r={d:d,x:x};reg.push(r);mark1(r);return d;};
render=function(){reg=[];return r0.apply(this,arguments);};
loadInst();setInterval(loadInst,30000);})();
