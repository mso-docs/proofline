/* Proofline dashboard. Renders the run store snapshot; live updates arrive over /api/stream (SSE). */
(()=>{
const q=new URLSearchParams(location.search);
const S={view:q.get('view')||'map',theme:q.get('theme')||localStorage.getItem('pl-theme')||'dark',sel:q.get('ac'),data:null,log:[],live:false};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const art=p=>window.PROOFLINE_SNAPSHOT?`artifacts/${p}`:`/artifacts/${p}`;
const hm=t=>t?new Date(t).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}):'';
const dt=t=>t?new Date(t).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}):'';
function applyTheme(){document.body.classList.toggle('light',S.theme==='light')}
function groups(){const g=new Map();for(const a of S.data.acs){const k=a.use_case||'Other';if(!g.has(k))g.set(k,{id:k,name:a.use_case_title||'',acs:[]});g.get(k).acs.push(a)}return [...g.values()]}
function running(){return new Set(S.data.runs.filter(r=>r.status==='running'&&r.body&&r.body.ac).map(r=>r.body.ac))}
function verdict(a){return running().has(a.id)?'run':a.verdict}
function counts(){const c={pass:0,fail:0,run:0,idle:0};S.data.acs.forEach(a=>c[verdict(a)]++);return c}
const stale=()=>new Set((S.data.drift?.stale||[]).map(s=>s.ac));

function top(){const c=counts();const st=S.data.status,prd=S.data.prds.at(-1);const tgt=S.data.target||{};
const tab=(v,l,n)=>`<a data-view="${v}" class="${S.view===v?'on':''}">${l}${n?`<span class="n">${n}</span>`:''}</a>`;
return `<div class="top"><div class="logo"><div class="mark"></div>Proofline</div>
<div class="crumb"><b>${esc(tgt.name||'Kane workspace')}</b><i>/</i>PRD <span class="mono">${esc(prd?prd.name:'none yet')}</span><i class="sess-i">/</i><span class="mono sess">${esc(st.session||'no session')}</span></div>
<div class="tabs">${tab('map','Requirements map')}${tab('evidence','Evidence',c.fail)}${tab('drift','Drift',S.data.drift?.stale?.length)}${tab('history','History')}</div>
<div class="cmdk">⌘<span>Drive Kane from your agent: ingest_prd · design_tests · run_suite · maintain_drift</span><kbd>MCP</kbd></div>
<div class="live ${S.live?'':'off'}">${window.PROOFLINE_SNAPSHOT?'STATIC':q.get('stream')==='0'?'SNAPSHOT':S.live?'LIVE':'OFFLINE'}</div><div class="theme"><a data-theme="dark" class="${S.theme==='dark'?'on':''}">☾</a><a data-theme="light" class="${S.theme==='light'?'on':''}">☀</a></div></div>`}

function pipe(){const p=S.data.status.pipeline||{};const order=S.data.pipeline_order;const k=S.data.status.kane||{};
const cls=s=>!s?'':s.state==='done'?'done':s.state==='run'?'run':s.state==='fail'?'fail':'';
return `<div class="pipe"><span class="k">KANE-CLI ▸</span>${order.map((n,i)=>{const s=p[n];return `${i?`<div class="conn ${cls(p[order[i-1]])==='done'&&s?'done':''}"></div>`:''}<div class="stage ${cls(s)}"><div class="dot">${cls(s)==='done'?'✓':cls(s)==='run'?'':cls(s)==='fail'?'✕':i+1}</div><div><b>${n}</b><small>${esc(s?s.detail||s.state:'idle')}</small></div></div>`}).join('')}
${(k.fixture||S.data.target?.fixture)?'<span class="mockflag">fixture kane-cli · scripted verdicts</span>':''}<div class="target">kane-cli <span class="url">${esc(k.installed?k.version:'not installed')}</span></div></div>`}

function tiles(){const c=counts(),st=stale();
if(!S.data.acs.length)return `<div class="canvas-head"><div><h1>Requirements map</h1><p>No acceptance criteria yet. Ingest a PRD: <span class="mono">python3 -m proofline ingest prd.md</span> or the <span class="mono">ingest_prd</span> MCP tool.</p></div></div>`;
return `<div class="canvas-head"><div><h1>Requirements map</h1><p>Each tile is one acceptance criterion from the PRD, grouped by use case. Click a tile for its evidence.</p></div>
<div class="legend"><span><i style="background:var(--pass)"></i>Passing ${c.pass}</span><span><i style="background:var(--fail)"></i>Failing ${c.fail}</span><span><i style="background:var(--amber)"></i>Running ${c.run}</span><span><i style="background:var(--idle)"></i>No run yet ${c.idle}</span></div></div>
<div class="map">${groups().map(u=>{const n=u.acs.length,p=u.acs.filter(a=>verdict(a)==='pass').length,f=u.acs.filter(a=>verdict(a)==='fail').length,r=u.acs.filter(a=>verdict(a)==='run').length;
return `<div class="uc"><div class="uc-h"><span class="id">${esc(u.id)}</span><b>${esc(u.name)}</b></div><div class="uc-meta"><span>${p}/${n} pass</span><span>${Math.round((p+f)/n*100)}% covered</span></div>
<div class="uc-bar"><span style="width:${p/n*100}%;background:var(--pass)"></span><span style="width:${f/n*100}%;background:var(--fail)"></span><span style="width:${r/n*100}%;background:var(--amber)"></span></div>
<div class="tiles">${u.acs.map(a=>{const v=verdict(a);return `<div class="tile ${v} ${S.sel===a.id?'sel':''} ${S.view==='drift'&&st.has(a.id)?'stale':''}" data-ac="${esc(a.id)}"><div class="ac">${esc(a.id)}<span>${v==='idle'?'—':v==='run'?'● running':v.toUpperCase()}${a.flaky?'<em class="flk">↯ flaky</em>':''}</span></div><div class="t">${esc(a.title)}</div></div>`}).join('')}</div></div>`}).join('')}</div>`}

function insp(){const c=counts(),T=S.data.acs.length||1,C=2*Math.PI*30,cov=Math.round((c.pass+c.fail)/T*100),pr=c.pass+c.fail?Math.round(c.pass/(c.pass+c.fail)*100):0;
const fails=S.data.acs.filter(a=>a.verdict==='fail');const f=fails[0];const tests=S.data.status.tests;
const runs=S.data.runs.filter(r=>r.kind==='testmd-run');const feed=S.data.events.filter(e=>['verdict','stage','run_start'].includes(e.kind)).slice(-7).reverse();
return `<div class="insp"><div class="sect">Coverage<span>${esc(S.data.prds.at(-1)?.name||'')}</span></div>
<div class="ring"><svg width="84" height="84" viewBox="0 0 84 84"><circle cx="42" cy="42" r="30" fill="none" stroke="var(--idle-soft)" stroke-width="9"/>
<circle cx="42" cy="42" r="30" fill="none" stroke="var(--pass)" stroke-width="9" stroke-dasharray="${C*c.pass/T} ${C}" transform="rotate(-90 42 42)"/>
<circle cx="42" cy="42" r="30" fill="none" stroke="var(--fail)" stroke-width="9" stroke-dasharray="${C*c.fail/T} ${C}" stroke-dashoffset="${-C*c.pass/T}" transform="rotate(-90 42 42)"/>
<circle cx="42" cy="42" r="30" fill="none" stroke="var(--amber)" stroke-width="9" stroke-dasharray="${C*c.run/T} ${C}" stroke-dashoffset="${-C*(c.pass+c.fail)/T}" transform="rotate(-90 42 42)"/></svg>
<div><div class="big">${cov}%</div><small>${c.pass+c.fail} of ${S.data.acs.length} ACs have a verdict</small><small style="color:var(--pass)">${pr}% of verdicts pass</small></div></div>
<div class="kpis"><div class="kpi"><b>${tests}</b><span>tests</span></div><div class="kpi"><b>${runs.length}</b><span>test runs</span></div><div class="kpi"><b style="color:var(--fail)">${c.fail}</b><span>failing</span></div></div>
<div class="sect">Needs attention</div>
${f?`<div class="card"><span class="pill fail">FAIL · ${esc(f.id)}</span><h4>${esc(f.title)}</h4><p>${esc(f.history.at(-1)?.rationale||'')}. ${f.history.filter(h=>h.value<1).length} of ${f.history.length} runs failed.</p><div style="margin-top:9px;display:flex;gap:6px"><a class="btn primary" data-open="${esc(f.id)}">Open evidence →</a><span class="btn ghost mono" title="Rerun from your agent">run_suite</span></div></div>`:'<div class="card"><p>Nothing failing.</p></div>'}
<div class="sect">Live feed</div><div class="feed">${feed.map(e=>{const b=e.body;const pill=e.kind==='verdict'?`<span class="pill ${b.verdict}">${b.verdict.toUpperCase()}</span> ${esc(b.ac)} · ${esc(b.rationale)}`:e.kind==='stage'?`<span class="pill ice">STAGE</span> ${esc(b.name)} · ${esc(b.state)} ${esc(b.detail)}`:`<span class="pill run">RUN</span> ${esc(b.command)}`;return `<div><span class="tm">${hm(e.created_at)}</span><span>${pill}</span></div>`}).join('')}</div></div>`}

function dock(min){const runs=S.data.runs.filter(r=>r.kind==='testmd-run');const t0=runs.length?Date.parse(runs[0].created_at):0,t1=runs.length?Math.max(...runs.map(r=>Date.parse(r.finished_at||new Date().toISOString()))):1,span=Math.max(1,t1-t0);
const lanes=groups().map(u=>[u.id,u.name,runs.filter(r=>u.acs.some(a=>a.id===r.body?.ac))]);
const seg=r=>{const l=(Date.parse(r.created_at)-t0)/span*96,w=Math.max(1.2,((Date.parse(r.finished_at||new Date().toISOString())-Date.parse(r.created_at))/span*96));const s=r.status==='pass'?'pass':r.status==='fail'?'fail':'run';return `<div class="seg ${s}" style="left:${l}%;width:${w}%" title="${esc(r.body?.ac)} · ${esc(r.status)}" data-ac="${esc(r.body?.ac)}">${w>7?'<span class="thumb"></span>':''}<i></i><i></i>${s==='fail'?'<span class="x">✕</span>':''}</div>`};
const bars=runs.slice(-60).map((r,i)=>`<span style="height:${30+((i*37)%60)}%;background:${r.status==='fail'?'var(--fail)':r.status==='pass'?'var(--pass)':'var(--amber)'}"></span>`).join('');
const p=runs.filter(r=>r.status==='pass').length,f=runs.filter(r=>r.status==='fail').length,rn=runs.filter(r=>r.status==='running').length;
const logs=S.data.events.filter(e=>['kane','log','screenshot','verdict'].includes(e.kind)).slice(-60).map(e=>{const b=e.body;let t;
 if(e.kind==='verdict')t=b.verdict==='pass'?`<span class="g">✓ ${esc(b.ac)} passed</span>`:`<span class="r">✕ ${esc(b.ac)} · ${esc(b.rationale)}</span>`;
 else if(e.kind==='screenshot')t=`screenshot → <span class="c">${esc(b.path.split('/').slice(-3).join('/'))}</span>`;
 else if(e.kind==='log')t=`<span class="a">${esc(b.line)}</span>`;
 else t=`<span class="c">▸</span> ${esc(b.type||('step '+b.step))} ${esc(b.title||b.remark||b.overall_status||b.summary||'')}`;
 return `<p><span class="k">${hm(e.created_at)}</span> ${t}</p>`}).join('');
if(min)return `<div class="dock min"><div class="tl" style="justify-content:center"><div class="scrub" style="margin:0"><div class="ctrl"><span>⏮</span><span class="on">▶</span><span>⏭</span></div><div class="ruler"><div class="hist">${bars}</div><div class="win"></div></div></div></div><div class="log" style="display:flex;align-items:center;gap:10px">${S.data.events.length?`<span class="pill ice">LAST</span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(S.data.runs.at(-1)?.command||'')} · ${hm(S.data.runs.at(-1)?.created_at)}</span>`:''}</div></div>`;
return `<div class="dock"><div class="tl"><div class="tl-h"><b>Run timeline</b><small>${runs.length} test runs · ${hm(runs[0]?.created_at)} → ${hm(runs.at(-1)?.finished_at)}</small><div class="r"><span class="pill pass">${p} pass</span><span class="pill fail">${f} fail</span><span class="pill run">${rn} running</span><span class="pill ice">⇢ follow live</span></div></div>
<div class="lanes">${lanes.map(l=>`<div class="lane"><div class="nm"><b>${esc(l[0])}</b> · ${esc((l[1]||'').split(' ')[0].toLowerCase())}</div><div class="track">${l[2].map(seg).join('')}</div></div>`).join('')}</div>
<div class="scrub"><div class="ctrl"><span>⏮</span><span class="on">▶</span><span>⏭</span><span>1×</span></div><div class="ruler"><div class="hist">${bars}</div><div class="win"></div></div></div></div>
<div class="log"><div class="lh"><b>Logs</b><span class="mono">kane-cli · secrets redacted</span></div><div class="logbody">${logs}</div></div></div>`}

function evidence(){const a=S.data.acs.find(x=>x.id===S.sel)||S.data.acs.find(x=>x.verdict==='fail')||S.data.acs.find(x=>x.history.length);if(!a)return '';S.sel=a.id;
const last=a.history.at(-1);const shots=S.data.artifacts.filter(x=>x.run_id===last?.run_id);const run=S.data.runs.find(r=>r.id===last?.run_id);
const v=a.verdict;const tr=S.data.traces?.[last?.trace_id];const steps=(tr?.spans)||[];
const fails=S.data.acs.filter(x=>x.verdict==='fail'),i=fails.findIndex(x=>x.id===a.id);
const main=shots.at(-1);
return `<div class="scrim" data-close="1"></div><div class="evid"><div class="ev-h"><span class="pill ${v}">${v.toUpperCase()}</span><div style="min-width:0"><h2>${esc(a.title)}</h2><div class="mono" style="color:var(--muted);font-size:10.5px;margin-top:2px">${esc(a.id)} · ${esc(a.use_case||'')} ${esc(a.use_case_title||'')} · run ${esc(last?.run_id||'none')} · ${dt(last?.at)}</div></div><div class="r">${fails.length>1?`<a class="btn ghost" data-open="${esc(fails[(i-1+fails.length)%fails.length].id)}">◀ prev</a><a class="btn ghost" data-open="${esc(fails[(i+1)%fails.length].id)}">next ▶</a>`:''}<a class="btn" data-close="1">✕</a></div></div>
<div class="ev-b"><div style="display:flex;flex-direction:column;gap:8px;min-height:0"><div class="shot"><div class="bar"><i></i><i></i><i></i><span>${esc(a.test_path||'')}</span>${main?`step ${main.step??'?'} / ${shots.length}`:'no screenshots'}</div>
${main?`<img class="shot-img" src="${art(main.path)}" alt="Screenshot of ${esc(a.id)} step ${main.step}">`:'<div class="page"><p>No screenshot in this run’s evidence pack.</p></div>'}
<div class="filmstrip">${shots.map(s=>`<div class="${s===main?'cur':''}" style="background-image:url('${art(s.path)}');background-size:cover"><span>${s.step??''}</span></div>`).join('')}</div></div></div>
<div class="ev-r"><div class="eva"><div class="card exp"><h5>EXPECTED</h5><p>${esc(a.title)}</p></div><div class="card act"><h5>ACTUAL</h5><p>${esc(last?.rationale||'No run yet')}</p></div></div>
<div class="card"><div class="sect" style="margin-bottom:6px">Steps<span>kane-cli testmd</span></div><div class="steps">${steps.map(s=>`<div class="${s.status==='failed'?'f':''}"><span class="ic ${s.status==='passed'?'ok':s.status==='failed'?'no':'sk'}">${s.status==='passed'?'✓':s.status==='failed'?'✕':'–'}</span>${esc(s.name)}<small>${esc(s.remark||'')}</small></div>`).join('')}</div></div>
<div style="display:flex;gap:6px;flex-wrap:wrap"><span class="pill idle">trace ${esc(last?.trace_id||'')}</span><span class="pill idle">ac_pass = ${last?last.value:'—'}</span><span class="pill ice">${a.history.length} runs · ${a.history.map(h=>h.value>=1?'P':'F').join(' ')}</span>${a.flaky?'<span class="pill stale">↯ flaky</span>':''}</div>
<div class="card overtime" style="flex:1;min-height:0"><div class="sect" style="margin-bottom:6px">This criterion over time<span>${a.history.length} runs</span></div><div class="steps">${a.history.slice().reverse().map(h=>`<div class="${h.value<1?'f':''}"><span class="ic ${h.value>=1?'ok':'no'}">${h.value>=1?'✓':'✕'}</span>${esc(h.run_id)} · ${esc(h.rationale)}<small>${dt(h.at)}</small></div>`).join('')}</div>
<p style="margin-top:8px">${a.flaky?'Verdict flipped with the same test and PRD: flaky.':a.history.length>1&&a.history.every(h=>h.value<1)?'Fails every run: not flaky.':''}</p></div></div></div></div>`}

function drift(){const d=S.data.drift;if(!d)return `<div class="canvas-head"><div><h1>Drift</h1><p>No new PRD version yet. Run <span class="mono">maintain_drift</span> with the new file.</p></div></div>`;
return `<div class="canvas-head"><div><h1>Drift</h1><p>${esc(d.new)} compared with ${esc(d.old)}. Each changed criterion is matched to the tests that check it.</p></div><div class="legend"><span><i style="background:var(--fail)"></i>Removed</span><span><i style="background:var(--pass)"></i>Added</span><span><i style="background:var(--amber)"></i>Stale test</span></div></div>
<div class="drift"><div class="diff"><div class="dh"><b>${esc(d.old)}</b> → ${esc(d.new)} <span class="pill pass">+${d.plus}</span><span class="pill fail">−${d.minus}</span></div>
<div class="code">${d.lines.map(l=>l.kind==='hunk'?`<div class="hunk"><span class="ln"></span><span class="ln"></span><span></span><span>${esc(l.text)}</span></div>`:`<div class="${l.kind==='ctx'?'':l.kind}"><span class="ln">${l.old??''}</span><span class="ln">${l.new??''}</span><span class="s">${l.kind==='add'?'+':l.kind==='del'?'−':' '}</span><span>${l.html.replace(/^(#+ )?(AC-[\d.]+)/,'<span class="h">$1$2</span>')}</span></div>`).join('')}</div>
<div style="margin-top:auto;border-top:1px solid var(--line);padding:10px 12px;display:grid;grid-template-columns:repeat(4,1fr);gap:8px"><div class="kpi"><b>${d.changed.length}</b><span>ACs changed</span></div><div class="kpi"><b style="color:var(--amber)">${d.stale.length}</b><span>tests stale</span></div><div class="kpi"><b>${d.untested_new.length}</b><span>new AC, no test</span></div><div class="kpi"><b>${d.removed.length}</b><span>ACs removed</span></div></div></div>
<div class="stalelist"><div class="sect">Stale tests · ${d.stale.length} of ${S.data.status.tests}<span>kane-cli maintain reconcile</span></div>
${d.stale.map(s=>`<div class="st hot"><b>${esc(s.test.split('/').pop())}</b><span class="pill stale">STALE</span><div class="why">${esc(s.ac)} · ${esc(s.reason)}</div><small>was “${esc(s.was)}”${s.now?` · now “${esc(s.now)}”`:''}</small></div>`).join('')}
${d.untested_new.map(a=>`<div class="st"><b>${esc(a)} · new criterion</b><span class="pill idle">NO TEST</span><small>design_tests will cover it.</small></div>`).join('')}
<div class="maintain"><div class="cmd">$ <b>${esc(d.kane?.command||'kane-cli maintain reconcile')}</b></div><span class="btn ${d.kane?.exit_code===0?'primary':''}">${d.kane?.exit_code===0?'⟳ plan saved · '+esc(d.kane?.final?.summary||''):'exit '+esc(d.kane?.exit_code)}</span></div></div></div>`}

function historyView(){const suites=new Map();for(const a of S.data.acs)for(const h of a.history){if(!suites.has(h.suite))suites.set(h.suite,{at:h.at,v:[]});suites.get(h.suite).v.push(h.value)}
const list=[...suites.entries()].sort((a,b)=>Date.parse(a[1].at)-Date.parse(b[1].at));const N=S.data.acs.length||1;
const pass=list.map(([,s])=>Math.round(s.v.filter(x=>x>=1).length/s.v.length*100)),cov=list.map(([,s])=>Math.round(s.v.length/N*100));
const W=600,H=300,n=Math.max(1,list.length-1),xs=i=>40+i/n*(W-60),ys=v=>H-30-v/100*(H-50);
const line=(a,c,dash)=>`<polyline points="${a.map((v,i)=>xs(i)+','+ys(v)).join(' ')}" fill="none" stroke="${c}" stroke-width="2.4" ${dash?'stroke-dasharray="5 4"':''}/>`+a.map((v,i)=>`<circle cx="${xs(i)}" cy="${ys(v)}" r="3.2" fill="var(--panel)" stroke="${c}" stroke-width="2"/>`).join('');
const grid=[0,25,50,75,100].map(v=>`<line x1="40" x2="${W-20}" y1="${ys(v)}" y2="${ys(v)}" stroke="var(--line)"/><text x="32" y="${ys(v)+3}" text-anchor="end" font-size="10" fill="var(--faint)" font-family="JetBrains Mono">${v}%</text>`).join('')+list.map((s,i)=>`<text x="${xs(i)}" y="${H-10}" text-anchor="middle" font-size="10" fill="var(--faint)" font-family="JetBrains Mono">#${i+1}</text>`).join('');
const flaky=S.data.acs.filter(a=>a.flaky),flips=S.data.acs.filter(a=>a.flips>0).sort((a,b)=>b.flips-a.flips);
const spark=vals=>{const w=200,h=20;if(vals.length<2)vals=[vals[0]||0,vals[0]||0];return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${vals.map((v,i)=>`${(i/(vals.length-1)*w).toFixed(1)},${(h-2-v/100*(h-4)).toFixed(1)}`).join(' ')}" fill="none" stroke="var(--amber)" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`};
const uc=groups().map(u=>{const per=list.map(([id])=>{const v=u.acs.flatMap(a=>a.history.filter(h=>h.suite===id).map(h=>h.value));return v.length?Math.round(v.filter(x=>x>=1).length/v.length*100):0});return [u.id+' '+u.name,per,(per.at(-1)??0)+'%']});
const d=(a)=>a.length>1?a.at(-1)-a[0]:0;
return `<div class="canvas-head"><div><h1>History</h1><p>${list.length} suite runs · every verdict is kept, nothing is overwritten.</p></div><div class="legend" style="align-items:center"><div class="exports"><a class="btn" href="/api/acs" download="acs.json">⇩ ACs JSON</a><a class="btn" href="/api/manifest" download="manifest.json">⇩ Manifest</a><span class="btn primary mono" title="python3 -m proofline export site/">export_dashboard</span></div></div></div>
<div class="hist-grid"><div class="box bigchart"><h3>Pass rate and coverage by suite run</h3><div class="sub"><span style="color:var(--amber)">━</span> coverage &nbsp; <span style="color:var(--pass)">┅</span> pass rate of verdicts</div>
<div class="hist-top"><div class="kpi"><b>${cov.at(-1)??0}%</b><span>coverage <span class="delta ${d(cov)>=0?'up':''}">${d(cov)>=0?'▲':'▼'} ${Math.abs(d(cov))} pts</span></span></div><div class="kpi"><b>${pass.at(-1)??0}%</b><span>pass rate <span class="delta ${d(pass)>=0?'up':''}">${d(pass)>=0?'▲':'▼'} ${Math.abs(d(pass))} pts</span></span></div><div class="kpi"><b>${flaky.length}</b><span>flaky tests</span></div><div class="kpi"><b>${S.data.manifest_count}</b><span>hashed artifacts</span></div></div>
<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${grid}${line(pass,'var(--pass)',1)}${line(cov,'var(--amber)')}</svg></div>
<div class="box"><h3>Pass rate by use case</h3><div class="sub">per suite run</div><div class="sparks">${uc.map(u=>`<div class="sp"><span>${esc(u[0])}</span>${spark(u[1])}<b>${u[2]}</b></div>`).join('')}</div></div>
<div class="box"><h3>Flip-floppers</h3><div class="sub">tests that changed verdict without a test or PRD change are flagged flaky</div><div class="flips">${flips.length?flips.map(f=>`<div class="fl" data-ac="${esc(f.id)}"><span class="ac">${esc(f.id)}</span><span class="t">${esc(f.title)}</span><span class="seq">${f.history.map(h=>`<i class="${h.value>=1?'p':'f'}"></i>`).join('')}</span><b>${f.flips}↯</b></div>`).join(''):'<p class="sub">No verdict has flipped yet.</p>'}</div></div></div>`}

function render(){if(!S.data)return;applyTheme();const v=S.view;let main;
if(v==='drift')main=`<div class="main"><div class="canvas">${drift()}</div>${insp()}</div>`;
else if(v==='history')main=`<div class="main" style="grid-template-columns:1fr"><div class="canvas">${historyView()}</div></div>`;
else main=`<div class="main" style="position:relative"><div class="canvas">${tiles()}</div>${insp()}${v==='evidence'?evidence():''}</div>`;
document.getElementById('app').innerHTML=top()+pipe()+main+dock(v!=='map');
const lb=document.querySelector('.logbody');if(lb)lb.scrollTop=lb.scrollHeight}

function setView(v,ac){S.view=v;if(ac)S.sel=ac;const u=new URL(location);u.searchParams.set('view',v);if(S.sel)u.searchParams.set('ac',S.sel);history.replaceState(null,'',u);render()}
document.addEventListener('click',e=>{const t=e.target.closest('[data-view],[data-theme],[data-ac],[data-open],[data-close]');if(!t)return;
if(t.dataset.view)return setView(t.dataset.view);if(t.dataset.theme){S.theme=t.dataset.theme;localStorage.setItem('pl-theme',S.theme);return render()}
if(t.dataset.open||t.dataset.ac)return setView('evidence',t.dataset.open||t.dataset.ac);if(t.dataset.close)return setView('map')});

function index(d){d.traces={};return d}
async function load(){if(window.PROOFLINE_SNAPSHOT){S.data=index(window.PROOFLINE_SNAPSHOT);return render()}
const r=await fetch('/api/snapshot');S.data=index(await r.json());
if(S.view==='evidence'&&S.sel!==undefined)await loadTrace();render()}
async function loadTrace(){const a=S.data.acs.find(x=>x.id===S.sel)||S.data.acs.find(x=>x.verdict==='fail');if(!a||!a.history.length||window.PROOFLINE_SNAPSHOT)return;
try{const ev=await (await fetch('/api/evidence?ac='+encodeURIComponent(a.id))).json();S.data.traces[a.history.at(-1).trace_id]={spans:ev.steps||[]}}catch{}}
let pending=null;function refresh(){clearTimeout(pending);pending=setTimeout(load,250)}
const _set=setView;setView=async(v,ac)=>{_set(v,ac);if(v==='evidence'){await loadTrace();render()}};
load().then(()=>{if(window.PROOFLINE_SNAPSHOT||q.get('stream')==='0')return;const es=new EventSource('/api/stream');es.onopen=()=>{S.live=true;render()};es.onerror=()=>{S.live=false;render()};
['kane','log','stage','verdict','run_start','run_end','screenshot','session'].forEach(k=>es.addEventListener(k,()=>refresh()))});
})();
