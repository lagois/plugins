"use strict";
const $=id=>document.getElementById(id);let state=null,active='monitor',busy=false,recipeEditorId=null,recipeEditorMode=null;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=v=>v==null?'--':Number(v).toFixed(1);const duration=v=>{let s=Math.max(0,Math.ceil(Number(v)||0));return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`};
function page(id){active=id;document.querySelectorAll('.page').forEach(el=>el.classList.toggle('hidden',el.id!==id));document.querySelectorAll('[data-nav]').forEach(el=>el.classList.toggle('active',el.dataset.nav===id));if(id==='history')loadHistory();if(id==='config')loadSettings();if(id==='system')loadDiagnostics();}
function message(t){$('messages').textContent=t;setTimeout(()=>{if($('messages').textContent===t)$('messages').textContent=''},6000)}
// Janelas próprias da interface: a confirmação nunca executa uma ação sem clique explícito.
const statusPT={IDLE:'Aguardando início',RUNNING:'Em execução',PAUSED:'Pausado',AWAIT_NEXT:'Aguardando avanço',RECOVERY_REQUIRED:'Recuperação necessária',COMPLETE:'Brassagem concluída',INTERRUPTED:'Brassagem interrompida',STOPPED:'Processo encerrado',FAULT:'Falha de sensor'};
const phasePT={WAIT_TARGET:'Aguardando temperatura-alvo',COUNTDOWN:'Contagem do tempo',WASH_PENDING:'Aguardando término da lavagem',WAIT_BOIL_CONFIRM:'Aquecendo até a temperatura de início da fervura',MASH:'Mostura',BOIL:'Fervura',DONE:'Concluído',IDLE:'Aguardando início',INTERRUPTED:'Interrompida',STOPPED:'Encerrada',COMPLETE:'Concluída',FAULT:'Falha de sensor',PAUSED:'Pausada',RECOVERY_REQUIRED:'Recuperação necessária',AWAIT_NEXT:'Aguardando avanço'};
const eventPT={PHASE_START:'Início de etapa',WASH_STARTED:'Lavagem iniciada',WASH_CONFIRMED:'Término da lavagem confirmado',ADDITION_CONFIRMED:'Adição confirmada',FINALIZED_BY_OPERATOR:'Brassagem concluída pelo operador',INTERRUPTED_BY_OPERATOR:'Brassagem interrompida pelo operador',STOPPED_BY_OPERATOR:'Processo encerrado pelo operador',HEATER_MANUAL_DISABLE:'Aquecimento desligado manualmente',HEATER_MANUAL_ENABLE:'Aquecimento habilitado manualmente',RESUMED:'Brassagem retomada',PAUSED:'Brassagem pausada',SETTING_CHANGED:'Configuração alterada',COMPLETE:'Brassagem concluída',INTERRUPTED:'Brassagem interrompida',STOPPED:'Processo encerrado',FAULT:'Falha de sensor',RUNNING:'Em execução',COUNTDOWN:'Contagem do tempo',WAIT_TARGET:'Aguardando temperatura-alvo'};
const sourcePT={Mash:'Mostura',Sparge:'Lavagem',Boil:'Fervura',MASH:'Mostura',SPARGE:'Lavagem',BOIL:'Fervura'};
function ptStatus(v){return statusPT[v]||phasePT[v]||v||'—'}
function ptPhase(v){return phasePT[v]||statusPT[v]||v||'—'}
function ptEvent(v){return eventPT[v]||ptStatus(v)}
function ptSource(v){return sourcePT[v]||v||'—'}
function ptSensorError(v){if(!v)return '—';const raw=String(v);const l=raw.toLowerCase();let description='Falha de leitura do sensor';if(/not found|no device|not present|missing|disconnected/.test(l))description='Sensor não encontrado ou desconectado';else if(/crc|checksum/.test(l))description='Falha de integridade na leitura do sensor';else if(/timeout|timed out/.test(l))description='Tempo de resposta do sensor excedido';else if(/permission denied/.test(l))description='Acesso ao sensor não permitido';else if(/invalid|out of range/.test(l))description='Leitura inválida do sensor';return description+' (detalhe técnico: '+raw+')'};
function uiDialog({title,body,kind='info',action='Entendi',cancel=false}){
 return new Promise(resolve=>{
  const overlay=$('beergoModal');if(!overlay||!overlay.hidden){resolve(false);return}
  const titleEl=$('beergoModalTitle'),bodyEl=$('beergoModalBody'),icon=$('beergoModalIcon'),ok=$('beergoModalOk'),no=$('beergoModalCancel');
  titleEl.textContent=title;bodyEl.textContent=body;icon.textContent=({info:'i',warning:'!',danger:'!',success:'✓'}[kind]||'i');
  icon.className='beergoModalIcon '+kind;ok.className='beergoModalOk '+kind;ok.textContent=action;no.hidden=!cancel;
  overlay.hidden=false;const prior=document.activeElement;const finish=value=>{overlay.hidden=true;ok.onclick=null;no.onclick=null;$('beergoModalClose').onclick=null;overlay.onkeydown=null;resolve(value);if(prior&&prior.focus)prior.focus()};
  ok.onclick=()=>finish(true);no.onclick=()=>finish(false);$('beergoModalClose').onclick=()=>finish(false);
  overlay.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();finish(false)}if(e.key==='Tab'){const items=[no,ok,$('beergoModalClose')].filter(x=>!x.hidden);const idx=items.indexOf(document.activeElement);if(e.shiftKey&&idx===0){e.preventDefault();items[items.length-1].focus()}else if(!e.shiftKey&&idx===items.length-1){e.preventDefault();items[0].focus()}}};
  (cancel?no:ok).focus();
 });
}
function uiConfirm(title,body,action='Confirmar',kind='warning'){return uiDialog({title,body,action,kind,cancel:true})}
async function command(url,body={}){if(busy)return;busy=true;try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'Erro HTTP '+r.status);await refresh()}catch(e){message(e.message)}finally{busy=false}}
async function finalizeProcess(){if(await uiConfirm('Concluir brassagem?','O SSR e a bomba serão desligados e o resultado será gravado no histórico.','Concluir','warning'))command('/api/process/finalize')}
async function interruptProcess(){if(await uiConfirm('Interromper brassagem?','O SSR e a bomba serão desligados e a interrupção será registrada no histórico.','Interromper','danger'))command('/api/process/interrupt')}
function togglePause(){if(!state)return;if(state.status==='PAUSED')command('/api/process/resume');else if(state.status==='RUNNING')command('/api/process/pause')}
// A confirmação contextual é apresentada uma vez por entrada na fase.
 // Cancelar mantém a solicitação pendente; o botão discreto permite reabri-la.
let contextualPromptKey='',contextualPromptDismissed=false,contextualPromptScheduled=false;
function contextualPrompt(s,pending){
 const phase=s.status==='RUNNING'&&!pending.length&&
  s.phase==='WASH_PENDING'?s.phase:'';
 const key=phase?[s.recipe_id,s.step_index,phase].join(':'):'';
 if(key!==contextualPromptKey){
  contextualPromptKey=key;contextualPromptDismissed=false;contextualPromptScheduled=false;
 }
 if(!key||contextualPromptDismissed||contextualPromptScheduled||active!=='monitor')return;
 if(!$('beergoModal').hidden)return;
 contextualPromptScheduled=true;
 setTimeout(async()=>{
  contextualPromptScheduled=false;
  if(!state||state.status!=='RUNNING'||active!=='monitor'||$('beergoModal').hidden===false)return;
  const current=[state.recipe_id,state.step_index,state.phase].join(':');
  if(current!==key||(state.pending_events||[]).length||contextualPromptDismissed)return;
  if(phase==='WASH_PENDING')await confirmWash();
  else await confirmBoil();
  // Se o operador cancelar, a confirmação continua pendente e pode ser reaberta.
  if(state&&state.status==='RUNNING'&&
   [state.recipe_id,state.step_index,state.phase].join(':')===key){
   contextualPromptDismissed=true;
   const reopen=phase==='WASH_PENDING'?'btnWash':'btnBoil';
   $(reopen).hidden=false;$('contextActions').hidden=false;
  }
 },0);
}
// Adições de sais e lúpulos: um pop-up por evento pendente, sem confirmação automática.
// Fechar/cancelar preserva o evento no backend e no painel de pendências.
let additionPromptSeen=new Set(),additionPromptBusy=false;
function additionPrompt(s,pending){
 const live=new Set(pending.map(e=>String(e.id)));
 for(const id of additionPromptSeen)if(!live.has(id))additionPromptSeen.delete(id);
 if(active!=='monitor'||additionPromptBusy||!$('beergoModal').hidden)return;
 const event=pending.find(e=>!additionPromptSeen.has(String(e.id)));
 if(!event)return;
 const id=String(event.id),recipeId=s.recipe_id,runId=s.run_id;
 additionPromptSeen.add(id);additionPromptBusy=true;
 setTimeout(async()=>{
  try{
   if(!state||active!=='monitor'||!$('beergoModal').hidden||state.recipe_id!==recipeId||state.run_id!==runId||!(state.pending_events||[]).some(e=>String(e.id)===id)){
    additionPromptSeen.delete(id);return;
   }
   const salt=id.startsWith('salt-')||/^(mash|sparge)$/i.test(String(event.phase||''));
   const title=salt?'Adicionar sais à água':'Adicionar lúpulo';
   const body=[event.name,event.amount,ptSource(event.phase)].filter(Boolean).join(' · ')+'. Confirme somente após realizar a adição.';
   const confirmed=await uiConfirm(title,body,'Confirmar adição','warning');
   if(confirmed&&state&&state.recipe_id===recipeId&&state.run_id===runId&&(state.pending_events||[]).some(e=>String(e.id)===id)){
    await command('/api/process/confirm-event',{id});
   }
  }finally{additionPromptBusy=false;}
 },0);
}
async function confirmWash(){
 if(!state||state.status!=='RUNNING'||state.phase!=='WASH_PENDING'||(state.pending_events||[]).length)return;
 if(await uiConfirm('Confirmar término da lavagem?','A lavagem foi concluída? Confirme para liberar a próxima etapa da brassagem.','Confirmar lavagem','warning')){
  if(state&&state.status==='RUNNING'&&state.phase==='WASH_PENDING'&&!(state.pending_events||[]).length)await command('/api/process/wash-confirm');
 }
}
async function confirmBoil(){
 if(!state||state.status!=='RUNNING'||state.phase!=='WAIT_BOIL_CONFIRM'||(state.pending_events||[]).length)return;
 if(await uiConfirm('Confirmar início da fervura?','O mosto já atingiu a fervura? Confirme para iniciar a contagem do tempo de fervura.','Confirmar fervura','warning')){
  if(state&&state.status==='RUNNING'&&state.phase==='WAIT_BOIL_CONFIRM'&&!(state.pending_events||[]).length)await command('/api/process/boil-confirm');
 }
}
async function nextPhase(){if(!state)return;if(state.phase==='WASH_PENDING'){message('Confirme o término da lavagem antes de avançar.');return}const x=state.recipe?.steps?.[state.step_index];if(await uiConfirm('Avançar para a próxima etapa?','Etapa atual: '+(x?.name||'atual')+'. O tempo restante será descartado e o próximo passo poderá solicitar aquecimento.','Avançar fase'))command('/api/process/next')}
function setVirtual(){let t=Number($('virtualTemp').value);if(!$('virtualTemp').value||t<10||t>100){message('Informe temperatura de 10 a 100 °C');return}command('/api/test/virtual',{temperature:t})}
async function importXML(){const f=$('xmlFile').files[0];if(!f){message('Selecione um BeerXML');return}await command('/api/recipe/import',{filename:f.name,xml:await f.text()});$('xmlFile').value=''}
const historyNames={COMPLETE:'Concluída',STOPPED:'Encerrada',INTERRUPTED:'Interrompida',FAULT:'Falha de sensor'};
async function loadHistory(){try{const r=await fetch('/api/history',{cache:'no-store'});if(!r.ok)throw Error('Erro ao consultar histórico');const h=await r.json();$('historyList').innerHTML=h.length?h.slice().reverse().map(x=>`<div class="recipeRow"><div class="recipeInfo"><strong>${esc(x.recipe)}</strong><small>Início: ${esc(x.timestamp||'Não registrado')} · Término: ${esc(x.finished_at||'Não registrado')}</small><span class="historyBadge">${esc(historyNames[x.result]||x.result||'Não informado')}</span></div><div class="historyActions"><button data-hview="${esc(x.id||'')}">Ver</button><button data-hanalysis="${esc(x.id||'')}">Análise</button><button class="danger" data-hdelete="${esc(x.id||'')}" ${x.id?'':'disabled'}>Excluir</button></div></div>`).join(''):'Nenhum registro ainda.';for(const [attr,action] of [['data-hview','view'],['data-hanalysis','analysis'],['data-hdelete','delete']])$('historyList').querySelectorAll('['+attr+']').forEach(b=>b.addEventListener('click',()=>historyAction(b.getAttribute(attr),action)))}catch(e){message(e.message)}}
async function historyAction(id,action){if(!id){message('Registro antigo sem identificador; detalhes não disponíveis.');return}if(action==='delete'){if(!await uiConfirm('Excluir histórico?','O registro selecionado será excluído definitivamente.','Excluir','danger'))return;await command('/api/history/delete',{id});$('historyDetail').classList.add('hidden');await loadHistory();return}try{const r=await fetch('/api/history/detail?id='+encodeURIComponent(id),{cache:'no-store'}),h=await r.json();if(!r.ok)throw Error(h.error||'Erro ao consultar histórico');const d=$('historyDetail');d.classList.remove('hidden');const samples=h.samples||[],valid=samples.filter(p=>p.sensor_ok&&Number.isFinite(p.temperature)),temps=valid.map(p=>p.temperature),min=temps.length?Math.min(...temps):null,max=temps.length?Math.max(...temps):null,avg=temps.length?temps.reduce((a,b)=>a+b,0)/temps.length:null;const elapsed=samples.length?Math.max(0,samples[samples.length-1].ts-samples[0].ts):null;const timeOn=key=>samples.reduce((sum,p,i)=>sum+(p[key]&&i+1<samples.length?Math.min(30,Math.max(0,samples[i+1].ts-p.ts)):0),0);const faults=samples.filter(p=>!p.sensor_ok).length;const fmtNum=n=>n==null?'Sem dados':Number(n).toFixed(1);d.innerHTML=`<h3>${action==='analysis'?'Análise':'Detalhes'}: ${esc(h.recipe)}</h3><p><b>Status:</b> ${esc(historyNames[h.result]||ptStatus(h.result))} · <b>Início:</b> ${esc(h.timestamp)} · <b>Término:</b> ${esc(h.finished_at||'Não registrado')}</p>${action==='analysis'?`<div class="historyAnalysis"><div><b>Temperatura mínima</b><p>${fmtNum(min)} °C</p></div><div><b>Temperatura média</b><p>${fmtNum(avg)} °C</p></div><div><b>Temperatura máxima</b><p>${fmtNum(max)} °C</p></div><div><b>Amostras</b><p>${samples.length}</p></div><div><b>Falhas do sensor (amostras)</b><p>${faults}</p></div><div><b>SSR ligado (amostrado)</b><p>${duration(timeOn('heater'))}</p></div><div><b>Bomba ligada (amostrada)</b><p>${duration(timeOn('pump'))}</p></div><div><b>Intervalo monitorado</b><p>${elapsed==null?'Sem dados':duration(elapsed)}</p></div></div><p class="muted">Indicadores estimados pelas amostras gravadas no intervalo configurado; não são medições elétricas independentes. Registros anteriores à Beta 8 podem não conter telemetria.</p>`:`<h4>Fases</h4><ul>${(h.phase_log||[]).map(p=>`<li>${esc(p.at)} — ${esc(p.name)}</li>`).join('')||'<li>Sem dados de fases.</li>'}</ul><h4>Eventos</h4><ul>${(h.event_log||[]).map(p=>`<li>${esc(p.at)} — ${esc(ptEvent(p.type))} ${esc(p.detail||'')}</li>`).join('')||'<li>Sem eventos detalhados.</li>'}</ul><p>Adições confirmadas: ${(h.confirmed_events||[]).length}</p>`}<button id="closeHistory">Fechar</button>`;$('closeHistory').onclick=()=>d.classList.add('hidden');d.scrollIntoView({behavior:'smooth',block:'start'})}catch(e){message(e.message)}}

function togglePump(){if(!state)return;command('/api/pump',{on:!state.pump})}
async function toggleHeater(){if(!state)return;const enable=!state.heater_manual_enabled;if(!enable&&!await uiConfirm('Desligar aquecimento?','A resistência permanecerá bloqueada até você ligá-la novamente.','Desligar','warning'))return;command('/api/heater/enable',{on:enable})}
function render(s){state=s;let step=s.recipe?.steps?.[s.step_index],running=s.status==='RUNNING';$('monRecipe').textContent=s.recipe?.name||'--';$('t1').textContent=fmt(s.temperature);$('alvo').textContent=s.current_target_c==null?'--':fmt(s.current_target_c);$('restante').textContent=duration(s.remaining_s);$('phaseTitle').textContent=step?.name||ptStatus(s.status);$('phaseSubtitle').textContent=s.phase==='WASH_PENDING'?'Lavagem · Pré-aquecendo para fervura':ptStatus(s.status)+' · '+ptPhase(s.phase);$('timerHint').textContent=s.test_speed===1?'Tempo real':'Teste acelerado '+s.test_speed+'×';$('pumpState').textContent=s.pump?'LIGADA':'DESLIGADA';$('heaterState').textContent=s.heater?'LIGADA':'DESLIGADA';$('heaterRequest').textContent=s.heater_requested?'ATIVO':'INATIVO';// Percentual solicitado ao SSR (não é medição elétrica da resistência).
const pidMostura=Boolean(s.pid_enabled&&step?.kind==='mash');
$('heaterPowerNow').textContent=pidMostura?(running&&s.heater_manual_enabled&&s.sensor_ok?Number(s.pid_power_pct||0).toFixed(1)+'%':'0%'):(s.heater?(step?.kind==='boil'?s.boil_power_pct:100)+'%':'0%');
$('thermalMode').textContent=s.pid_enabled?'PID (mostura)':'HISTERESE';$('pumpMode').textContent=!s.pump_phase_allowed?'Bloqueada nesta fase':s.pump_manual!==null?'Manual':s.pump_cycle_enabled?'Cíclica':'Sem ciclo';
$('pumpOnTime').textContent=s.pump_on_s+' s';$('pumpOffTime').textContent=s.pump_off_s+' s';
$('pumpNext').textContent=s.pump_next_s==null?'—':Math.ceil(s.pump_next_s/60)+' min';
$('pumpToggle').textContent=s.pump?'Desligar bomba':'Ligar bomba';
$('pumpToggle').disabled=!s.pump_phase_allowed||(!s.pump&&!s.pump_physical_enabled)||(!s.sensor_ok&&!s.pump);
$('heaterToggle').textContent=s.heater_manual_enabled?'Desligar aquecimento':'Ligar aquecimento';
$('heaterToggle').disabled=!s.heater_manual_enabled&&(!s.sensor_ok||!s.heater_physical_enabled);
$('thermalParameter').textContent=s.pid_enabled?('Kp='+Number(s.pid_kp).toLocaleString('pt-BR')+' · Ki='+Number(s.pid_ki).toLocaleString('pt-BR')+' · Kd='+Number(s.pid_kd).toLocaleString('pt-BR')):('Graus='+Number(s.hysteresis_c).toLocaleString('pt-BR')+' °C');
$('sideRecipeName').textContent=s.recipe?.name||'—';
$('sideRecipeSteps').innerHTML=(s.recipe?.steps||[]).map((x,i)=>`<div class="sideStep ${i===s.step_index?'current':''}"><span>${esc(x.name)}</span><b>${fmt(x.kind==='boil'?s.boil_reference_c:x.target)} °C · ${esc(x.minutes)}′</b></div>`).join('')||'Sem etapas.';
const pending=s.pending_events||[];additionPrompt(s,pending);$('pending').hidden=!pending.length;$('pendingList').innerHTML=pending.map(e=>`<div class="notice"><strong>${esc(e.name)}</strong> · ${esc(e.amount)} · ${esc(ptSource(e.phase))} <button data-confirm="${esc(e.id)}">Confirmar adição</button></div>`).join('');$('pendingList').querySelectorAll('[data-confirm]').forEach(b=>b.addEventListener('click',()=>command('/api/process/confirm-event',{id:b.dataset.confirm})));
const locked=['RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'].includes(s.status);
$('recipeList').innerHTML=(s.recipes||[]).map(r=>`<div class="recipeRow"><div class="recipeInfo"><strong>${esc(r.name)}</strong> ${r.id===s.recipe_id?'<strong>✓ Selecionada</strong>':''}<small>${esc(r.id)}</small></div><div class="recipeActions"><button data-recipe-view="${esc(r.id)}">Ver</button><button data-recipe-edit="${esc(r.id)}" ${locked?'disabled':''}>Alterar</button><button class="danger" data-recipe-delete="${esc(r.id)}" ${locked||r.id===s.recipe_id?'disabled':''}>Excluir</button><button data-recipe-select="${esc(r.id)}" ${locked||r.id===s.recipe_id?'disabled':''}>Selecionar</button></div></div>`).join('');
$('recipeList').querySelectorAll('[data-recipe-view]').forEach(b=>b.addEventListener('click',()=>openRecipe(b.dataset.recipeView,'view')));
$('recipeList').querySelectorAll('[data-recipe-edit]').forEach(b=>b.addEventListener('click',()=>openRecipe(b.dataset.recipeEdit,'edit')));
$('recipeList').querySelectorAll('[data-recipe-delete]').forEach(b=>b.addEventListener('click',()=>deleteRecipe(b.dataset.recipeDelete)));
$('recipeList').querySelectorAll('[data-recipe-select]').forEach(b=>b.addEventListener('click',()=>command('/api/recipe/select',{id:b.dataset.recipeSelect})));
const enable=(id,ok)=>$(id).disabled=!ok;enable('btnStart',['IDLE','STOPPED','INTERRUPTED','COMPLETE','FAULT'].includes(s.status)&&s.sensor_ok);{const paused=s.status==='PAUSED',b=$('btnPause'),label=paused?'Recomeçar brassagem':'Pausar brassagem';b.querySelector('.phaseGlyph').textContent=paused?'▶':'Ⅱ';b.setAttribute('aria-label',label);b.title=label;b.dataset.tooltip=label;b.classList.toggle('resume',paused);}enable('btnPause',running||(s.status==='PAUSED'&&s.sensor_ok&&!pending.length&&(s.mode==='simulation'||s.virtual_temperature==null))); $('btnRecover').hidden=s.status!=='RECOVERY_REQUIRED';$('btnBoil').hidden=true;
$('btnWash').hidden=!(running&&s.phase==='WASH_PENDING'&&!pending.length&&contextualPromptDismissed);
$('contextActions').hidden=$('btnRecover').hidden&&$('btnBoil').hidden&&$('btnWash').hidden;enable('btnRecover',s.status==='RECOVERY_REQUIRED');enable('btnBoil',false);enable('btnWash',running&&s.phase==='WASH_PENDING'&&!pending.length);enable('btnNext',['RUNNING','PAUSED','AWAIT_NEXT'].includes(s.status)&&!pending.length&&s.phase!=='WASH_PENDING'&&s.step_index<(s.recipe?.steps?.length||0)-1);enable('btnConclude',['RUNNING','PAUSED','AWAIT_NEXT'].includes(s.status)&&!pending.length);enable('btnInterrupt',['RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'].includes(s.status));
// Sem brassagem em andamento, todos os ícones permanecem neutros.
// PAUSED/AWAIT_NEXT/RECOVERY_REQUIRED pertencem à execução ainda não encerrada.
const processActive=['RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'].includes(s.status);
const stage=processActive?(s.phase==='WASH_PENDING'?'wash':
 s.phase==='WAIT_BOIL_CONFIRM'?'boil':
 step?.kind==='boil'?'boil':
 s.phase==='WAIT_TARGET'?'heat':'mash'):null;
const order=['heat','mash','wash','boil','cool','done'];
document.querySelectorAll('[data-stage]').forEach(x=>{
 const i=order.indexOf(x.dataset.stage),now=order.indexOf(stage);
 x.classList.toggle('active',processActive&&x.dataset.stage===stage);
 x.classList.toggle('completed',processActive&&i>=0&&i<now);
});drawTemperature(s);contextualPrompt(s,pending);}
const diagRow=(label,value)=>`<div class="diagRow"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;
const diagYes=v=>v?'Sim':'Não';
async function loadDiagnostics(){if(active!=='system')return;try{const r=await fetch('/api/diagnostics',{cache:'no-store'}),d=await r.json();if(!r.ok)throw Error(d.error||'Diagnóstico indisponível');const sys=d.system,sen=d.sensor,out=d.outputs,pr=d.process;
$('diagUpdated').textContent='Atualizado às '+new Date().toLocaleTimeString('pt-BR');
$('diagSystem').innerHTML=[diagRow('Versão',d.version),diagRow('Tempo do BeerGoPi',duration(sys.uptime_s)),diagRow('Carga média (1 min)',sys.cpu_load_1m??'Não disponível'),diagRow('Temperatura CPU',sys.cpu_temperature_c==null?'Não disponível':fmt(sys.cpu_temperature_c)+' °C'),diagRow('Memória disponível',sys.memory_available_mb==null?'Não disponível':sys.memory_available_mb+' MB'),diagRow('Disco livre',sys.disk_free_mb==null?'Não disponível':sys.disk_free_mb+' MB'),diagRow('Alimentação',sys.undervoltage==null?'Não monitorada':sys.undervoltage.current?'Subtensão atual':sys.undervoltage.occurred?'Subtensão registrada':'Normal')].join('');
$('diagSensor').innerHTML=[diagRow('Sensor T1 · GPIO',sen.gpio),diagRow('Leitura',sen.ok?'Válida':'Inválida'),diagRow('Leitura bruta',sen.raw_c==null?'Sem leitura real':fmt(sen.raw_c)+' °C'),diagRow('Offset',fmt(sen.offset_c)+' °C'),diagRow('Temperatura corrigida',sen.corrected_c==null?'—':fmt(sen.corrected_c)+' °C'),diagRow('Última leitura real válida',sen.last_ok_age_s==null?'Sem leitura':sen.last_ok_age_s+' s atrás'),diagRow('Erros desde o início',sen.errors),diagRow('Temperatura virtual',diagYes(sen.virtual)),sen.last_error?diagRow('Último erro',ptSensorError(sen.last_error)):''].join('');
$('diagOutputs').innerHTML=[diagRow('Resistência · GPIO',out.heater_gpio),diagRow('Comando de aquecimento',out.heater_command?'Ativo':'Inativo'),diagRow('Comando no GPIO do SSR',out.heater_gpio_command?'Ligado':'Desligado'),diagRow('Saída física SSR habilitada',diagYes(out.heater_enabled)),diagRow('Bomba · GPIO',out.pump_gpio),diagRow('Comando no GPIO da bomba',out.pump_gpio_command?'Ligado':'Desligado'),diagRow('Saída física bomba habilitada',diagYes(out.pump_enabled)),diagRow('Modo da bomba',out.pump_mode),'<p class="muted">Não há realimentação elétrica dos atuadores.</p>'].join('');
$('diagSafety').innerHTML=[diagRow('Estado do processo',ptStatus(pr.status)),diagRow('Fase interna',ptPhase(pr.phase)),diagRow('Confirmações pendentes',pr.pending_count),diagRow('Recuperação manual',pr.recovery_required?'Pendente':'Não pendente'),'<h4>Motivo do estado da resistência</h4><p class="diagReasons">'+out.heater_reasons.map(esc).join('<br>')+'</p><h4>Motivo do estado da bomba</h4><p class="diagReasons">'+out.pump_reasons.map(esc).join('<br>')+'</p>'].join('');
$('diagNetwork').innerHTML=[diagRow('Hostname',sys.hostname),diagRow('Endereço IP',sys.ip||'Não identificado'),diagRow('Servidor web','Porta '+sys.web_port+' · ativo'),diagRow('Interface','Atualização periódica ativa'),diagRow('Clientes conectados','Não monitorado')].join('');
$('diagEvents').innerHTML=d.events.length?d.events.map(e=>`<div class="diagEvent"><time>${esc(e.at||'')}</time><b>${esc(ptEvent(e.type))}</b><span>${esc(e.detail||'')}</span></div>`).join(''):'Nenhum evento registrado nesta execução.';
}catch(e){$('diagUpdated').textContent='Falha ao atualizar diagnóstico: '+e.message}}
/* Informações somente de apresentação; não altera cronômetros do processo. */
function renderBrewClock(s){
 const now=new Date();
 $('brewCurrentDate').textContent=now.toLocaleDateString('pt-BR');
 $('brewCurrentTime').textContent=now.toLocaleTimeString('pt-BR',{hour12:false});
 const started=s.started_at?new Date(s.started_at):null;
 const valid=started&&!Number.isNaN(started.getTime());
 $('brewStartTime').textContent=valid?started.toLocaleTimeString('pt-BR',{hour12:false}):'—';
 const activeRun=['RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'].includes(s.status);
 const elapsed=valid&&activeRun?Math.max(0,Math.floor((now-started)/1000)):null;
 $('brewElapsed').textContent=elapsed===null?'—':
  `${String(Math.floor(elapsed/3600)).padStart(2,'0')}:${String(Math.floor(elapsed%3600/60)).padStart(2,'0')}:${String(elapsed%60).padStart(2,'0')}`;
}
/* Somente apresentação: acompanha a maior altura natural das duas caixas
   inferiores da direita. Não altera dados, comandos ou cronômetros. */
let graphAlignFrame=0;
function scheduleGraphAlignment(){
 if(graphAlignFrame)cancelAnimationFrame(graphAlignFrame);
 graphAlignFrame=requestAnimationFrame(()=>{graphAlignFrame=0;alignGraphBottom()});
}
function alignGraphBottom(){
 const monitor=$('monitor'),card=monitor?.querySelector('.temperatureCard');
 const canvas=$('temperatureChart'),clock=monitor?.querySelector('.brewClockCard');
 const recipe=monitor?.querySelector('.monitorAside > .sideCompact:nth-child(3)');
 if(!card||!canvas||!clock||!recipe)return;
 const wide=window.matchMedia('(min-width:1050px)').matches;
 if(!wide||monitor.classList.contains('hidden')){
   card.style.removeProperty('height');canvas.style.removeProperty('height');
   return;
 }
 /* As duas caixas da direita conservam sua altura natural; o alvo é a
    borda inferior da mais alta, incluindo eventuais mudanças de conteúdo. */
 const target=Math.max(clock.getBoundingClientRect().bottom,recipe.getBoundingClientRect().bottom);
 const top=card.getBoundingClientRect().top;
 const desired=Math.max(190,Math.round(target-top));
 if(Math.abs(card.getBoundingClientRect().height-desired)>1){card.style.height=desired+'px'}
 /* Ajusta a área de desenho ao espaço interno efetivo da caixa. */
 const style=getComputedStyle(card),padding=parseFloat(style.paddingTop)+parseFloat(style.paddingBottom);
 const head=card.querySelector('h3'),legend=card.querySelector('.chartLegend'),hint=card.querySelector('#chartHint');
 const occupied=[head,legend,hint].reduce((sum,el)=>{
   if(!el)return sum;
   const st=getComputedStyle(el);
   return sum+el.getBoundingClientRect().height+parseFloat(st.marginTop)+parseFloat(st.marginBottom);
 },0);
 const available=Math.max(80,Math.floor(desired-padding-occupied));
 if(Math.abs(canvas.getBoundingClientRect().height-available)>1){canvas.style.height=available+'px'}
 if(state)drawTemperature(state);
}
window.addEventListener('resize',scheduleGraphAlignment);
if(typeof ResizeObserver!=='undefined'){
 const graphSideObserver=new ResizeObserver(scheduleGraphAlignment);
 for(const el of document.querySelectorAll('#monitor .monitorAside > .sideCompact'))graphSideObserver.observe(el);
 graphSideObserver.observe(document.querySelector('#monitor .processConsole'));
}
async function refresh(){try{const r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw Error('Sem comunicação com BeerGoPi');const payload=await r.json();render(payload);renderBrewClock(payload);scheduleGraphAlignment();if(active==='system')await loadDiagnostics()}catch(e){message('SEM COMUNICAÇÃO: '+e.message)}}
page('monitor');refresh();setInterval(refresh,1500);

function closeRecipe(){recipeEditorId=null;recipeEditorMode=null;$('recipeEditor').classList.add('hidden');$('recipeEditor').innerHTML=''}
async function openRecipe(id,mode){
 try{const r=await fetch('/api/recipe/detail?id='+encodeURIComponent(id),{cache:'no-store'});const data=await r.json();if(!r.ok)throw Error(data.error||'Falha ao abrir receita');
 recipeEditorId=id;recipeEditorMode=mode;const x=data.recipe;const editor=$('recipeEditor');editor.classList.remove('hidden');
 const stages=(x.steps||[]).map(y=>`<li>${esc(y.name)} — ${y.target==null?'Fervura':esc(y.target)+' °C'} — ${esc(y.minutes)} min</li>`).join('');
 const events=(x.events||[]).map(y=>`<li>${esc(y.name)} — ${esc(y.amount)} — ${esc(ptSource(y.phase))}${y.at_remaining==null?'':' — '+esc(y.at_remaining)+' min restantes'}</li>`).join('');
 editor.innerHTML=`<h3>${mode==='edit'?'Alterar':'Ver'} receita: ${esc(x.name)}</h3><p><b>Volume:</b> ${esc(x.batch_l)} L · <b>Arquivo:</b> ${esc(id)}</p><h4>Etapas</h4><ul>${stages}</ul><h4>Adições</h4>${events?'<ul>'+events+'</ul>':'<p>Sem adições registradas.</p>'}${mode==='edit'?'<p>Edite o BeerXML abaixo. O sistema valida a receita antes de salvar e mantém o arquivo original se houver erro.</p><textarea id="recipeXml" spellcheck="false"></textarea>':'<details><summary>Ver BeerXML original</summary><pre id="recipeXmlView"></pre></details>'}<div class="editorActions">${mode==='edit'?'<button id="saveRecipe">Salvar alterações</button>':''}<button id="closeRecipe">Fechar</button></div>`;
 if(mode==='edit'){$('recipeXml').value=data.xml;$('saveRecipe').addEventListener('click',saveRecipe)}else $('recipeXmlView').textContent=data.xml;
 $('closeRecipe').addEventListener('click',closeRecipe);editor.scrollIntoView({behavior:'smooth',block:'start'});
 }catch(e){message(e.message)}
}
async function saveRecipe(){if(!recipeEditorId)return;const id=recipeEditorId,xml=$('recipeXml').value;await command('/api/recipe/update',{id,xml});if(state?.recipes?.some(r=>r.id===id)){closeRecipe();await openRecipe(id,'view')}}
async function deleteRecipe(id){const r=state?.recipes?.find(x=>x.id===id);if(!r)return;if(await uiConfirm('Excluir receita?','A receita '+r.name+' e seu arquivo BeerXML serão removidos definitivamente.','Excluir','danger')){command('/api/recipe/delete',{id}).then(()=>{if(recipeEditorId===id)closeRecipe()})}}

const phaseColors=['#c47b30','#3e8f8b','#8b6ab8','#c45364','#5378b5','#7c9b49','#b779a6'];
function drawTemperature(s){const canvas=$('temperatureChart');if(!canvas)return;const samples=s.samples||[],legend=$('chartLegend');const phases=s.recipe?.steps||[];legend.innerHTML=phases.map((p,i)=>`<span><span style="display:inline-block;width:12px;height:12px;background:${phaseColors[i%phaseColors.length]};margin-right:5px"></span>${esc(p.name)}</span>`).join('');const width=Math.max(300,canvas.clientWidth||600),height=Math.max(100,canvas.clientHeight||360),dpr=window.devicePixelRatio||1;canvas.width=width*dpr;canvas.height=height*dpr;const c=canvas.getContext('2d');c.scale(dpr,dpr);c.clearRect(0,0,width,height);const L=38,R=12,T=8,B=30,plotW=width-L-R,plotH=height-T-B;c.font='12px sans-serif';c.fillStyle='#777';if(!samples.length){c.fillText('Sem amostras nesta execução',L+15,T+45);return}const ts=samples.map(p=>p.ts),minT=Math.min(...ts),maxT=Math.max(...ts,minT+1),vals=samples.flatMap(p=>[p.temperature,p.target]).filter(Number.isFinite),minV=Math.min(0,...vals)-2,maxV=Math.max(80,...vals)+2,x=t=>L+(t-minT)/(maxT-minT)*plotW,y=v=>T+(maxV-v)/(maxV-minV)*plotH;for(let i=0;i<samples.length;i++){const p=samples[i],next=samples[i+1],left=x(p.ts),right=next?x(next.ts):width-R;c.fillStyle=phaseColors[(p.step_index||0)%phaseColors.length]+'25';c.fillRect(left,T,Math.max(1,right-left),plotH)}c.strokeStyle='#9998';c.fillStyle='#777';for(let j=0;j<=4;j++){const v=minV+(maxV-minV)*j/4,yy=y(v);c.beginPath();c.moveTo(L,yy);c.lineTo(width-R,yy);c.stroke();c.textAlign='right';c.fillText(v.toFixed(0)+'°',L-5,yy+4);c.textAlign='left'}c.strokeStyle='#d59d38';c.lineWidth=1.5;c.setLineDash([5,4]);c.beginPath();let started=false;for(const p of samples){if(!Number.isFinite(p.target)){started=false;continue}if(!started)c.moveTo(x(p.ts),y(p.target));else c.lineTo(x(p.ts),y(p.target));started=true}c.stroke();c.setLineDash([]);c.strokeStyle='#2787b8';c.lineWidth=2;c.beginPath();started=false;for(const p of samples){if(!Number.isFinite(p.temperature)){started=false;continue}if(!started)c.moveTo(x(p.ts),y(p.temperature));else c.lineTo(x(p.ts),y(p.temperature));started=true}c.stroke();
// Eixo X: horários locais HH:MM.SS; intervalo adaptativo medido em pixels.
c.font='11px sans-serif';
const clock=t=>{const d=new Date(t*1000);return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+'.'+String(d.getSeconds()).padStart(2,'0')};
const labelWidth=Math.max(c.measureText('00:00.00').width,52);
const minGap=labelWidth+14;
const maxLabels=Math.max(1,Math.floor(plotW/minGap));
const span=maxT-minT;
const desired=span/Math.max(1,maxLabels-1);
const niceSteps=[1,2,5,10,15,20,30,60,120,300,600,900,1200,1800,3600,7200,14400,21600,43200,86400];
const tickStep=niceSteps.find(v=>v>=desired)||Math.ceil(desired/86400)*86400;
const first=Math.ceil(minT/tickStep)*tickStep;
let lastRight=-Infinity;
c.textAlign='center';c.textBaseline='top';c.fillStyle='#aab9c4';c.strokeStyle='#6b819250';c.lineWidth=1;
for(let t=first;t<=maxT+0.0001;t+=tickStep){
 const px=x(t),label=clock(t),w=c.measureText(label).width;
 if(px-w/2<L||px+w/2>width-R||px-w/2<lastRight+12)continue;
 c.beginPath();c.moveTo(px,height-B);c.lineTo(px,height-B+4);c.stroke();
 c.fillText(label,px,height-B+7);lastRight=px+w/2;
}
c.textAlign='left';c.textBaseline='alphabetic';
}

// Configurações: um formulário por área, sem modificar GPIOs energizados.
const settingGroups=[
 ['Controle de temperatura',[['t1_offset_c','Offset T1 (°C)','number','0.1'],['hysteresis_c','Histerese (°C)','number','0.1'],['pid_enabled','PID experimental na mostura (desligado por padrão)','checkbox'],['pid_kp','PID Kp (%/°C)','number','0.1'],['pid_ki','PID Ki (%/(°C·s))','number','0.001'],['pid_kd','PID Kd (%·s/°C)','number','0.1'],['boil_reference_c','Referência de fervura (°C)','number','0.1'],['boil_power_pct','Potência na fervura (%)','number','1']]],
 ['Bomba de recirculação',[['pump_cycle_enabled','Recirculação cíclica','checkbox'],['pump_on_s','Bomba ligada (s)','number','1'],['pump_off_s','Descanso (s)','number','1'],['pump_during_heat','Ligada no aquecimento (somente Mash-in/Mash-out)','checkbox']]],
 ['Hardware e sensores',[['hardware','Modo e GPIOs: consultar diagnóstico. Alterações físicas exigem parada e reinicialização.','info']]],
 ['Segurança e recuperação',[['safety','Falha do T1 desliga SSR; retomada manual; saídas desligadas na inicialização. Proteções não podem ser desativadas.','info']]],
 ['Histórico e sistema',[['sensor_interval_s','Intervalo de leitura T1 (s)','number','1'],['history_interval_s','Intervalo entre amostras (s)','number','1'],['network','Interface web: porta 18765 (config.json, requer reinicialização).','info']]]];
let currentSettings=null;
async function loadSettings(){try{const r=await fetch('/api/settings',{cache:'no-store'}),d=await r.json();if(!r.ok)throw Error(d.error||'Falha ao ler configurações');currentSettings=d;const el=$('settingsForm');el.innerHTML=settingGroups.map(([group,fields])=>`<fieldset class="settingsGroup"><legend>${esc(group)}</legend>${fields.map(([key,label,type,step])=>type==='info'?`<p class="muted">${esc(label)}${key==='hardware'?`<br>Modo: ${esc(d.hardware.mode)} · T1 GPIO${esc(d.hardware.sensor_gpio)} · SSR GPIO${esc(d.hardware.heater_gpio)} · bomba GPIO${esc(d.hardware.pump_gpio)}`:''}</p>`:`<label class="settingsField">${type==='checkbox'?`<input data-setting="${key}" type="checkbox" ${d.values[key]?'checked':''}> ${esc(label)}`:`${esc(label)}<input data-setting="${key}" type="number" step="${step}" value="${esc(d.values[key])}">`}</label>`).join('')}</fieldset>`).join('');$('settingsFeedback').textContent='';}catch(e){message(e.message)}}
async function saveSettings(){if(!currentSettings)return;const values={...currentSettings.values};for(const input of document.querySelectorAll('[data-setting]')){values[input.dataset.setting]=input.type==='checkbox'?input.checked:Number(input.value);if(input.type==='number'&&!input.value){message('Preencha todos os valores numéricos');return}}try{const r=await fetch('/api/settings/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({values})}),d=await r.json();if(!r.ok)throw Error(d.error||'Falha ao salvar');currentSettings.values=d.values;$('settingsFeedback').textContent='Configurações salvas e parâmetros operacionais aplicados.';await refresh()}catch(e){message(e.message)}}
