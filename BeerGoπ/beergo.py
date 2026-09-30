#!/usr/bin/env python3
"""BeerGoPi 0.11Beta: parâmetros dinâmicos, fervura e recirculação."""
import json, time, threading, xml.etree.ElementTree as ET, os, signal, io, re, uuid, statistics, socket, shutil
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
BASE=Path(__file__).resolve().parent
CFG=BASE/'config.json'
if not CFG.exists():
 raise SystemExit('config.json ausente; reinstale o pacote preservando a configuração da bancada.')
cfg=json.loads(CFG.read_text(encoding='utf-8'))
if int(cfg['heater_gpio'])==int(cfg['pump_gpio']): raise SystemExit('GPIOs da bomba e SSR não podem coincidir')
# Configurações operacionais persistidas separadamente dos GPIOs da bancada.
SETTINGS_FILE=BASE/'dados'/'configuracoes.json'
SETTINGS_DEFAULTS={'t1_offset_c':0.0,'hysteresis_c':cfg.get('temperature_hysteresis_c',0.5),
 'history_interval_s':5,'boil_reference_c':100.0,'boil_power_pct':70,
 'pump_cycle_enabled':True,'pump_on_s':180,'pump_off_s':60,'pump_during_heat':True,'sensor_interval_s':1,
 'pid_enabled':True,'pid_kp':8.0,'pid_ki':0.03,'pid_kd':0.0}
SETTINGS_LIMITS={'t1_offset_c':(-10,10),'hysteresis_c':(0.1,5),'history_interval_s':(1,60),
 'boil_reference_c':(85,105),'boil_power_pct':(0,100),'pump_on_s':(60,86400),'pump_off_s':(60,86400),'sensor_interval_s':(1,10),
 'pid_kp':(0,100),'pid_ki':(0,5),'pid_kd':(0,500)}
# Valores reservados são persistidos, mas NÃO acionam funcionalidades ainda não portadas.
SETTINGS_RESERVED=set()
def validate_settings(data):
 if not isinstance(data,dict):raise ValueError('Configurações inválidas')
 result={}
 for key,default in SETTINGS_DEFAULTS.items():
  v=data.get(key,default)
  if isinstance(default,bool):
   if type(v) is not bool:raise ValueError('Valor booleano inválido: '+key)
  else:
   if isinstance(v,bool) or not isinstance(v,(int,float)):raise ValueError('Valor numérico inválido: '+key)
   lo,hi=SETTINGS_LIMITS[key]
   if not lo<=v<=hi:raise ValueError('%s deve ficar entre %s e %s'%(key,lo,hi))
   if isinstance(default,int) and not isinstance(default,bool):
    if int(v)!=v:raise ValueError('Informe um inteiro para '+key)
    v=int(v)
  result[key]=v
 return result
def save_settings(data):
 SETTINGS_FILE.parent.mkdir(parents=True,exist_ok=True)
 tmp=SETTINGS_FILE.with_suffix('.tmp')
 with tmp.open('w',encoding='utf-8') as out:
  json.dump(data,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
 os.replace(tmp,SETTINGS_FILE)
settings=validate_settings(json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))) if SETTINGS_FILE.exists() else SETTINGS_DEFAULTS.copy()
# A configuração antiga pode ter limites menores; a validação acima aceita os novos limites.
# Nunca sobrescrever valores personalizados ao atualizar a instalação.
if SETTINGS_FILE.exists() and (all(settings[k]==v for k,v in {'pump_cycle_enabled':False,'pump_on_s':60,'pump_off_s':30,'pump_during_heat':False}.items()) or all(settings[k]==v for k,v in {'pump_cycle_enabled':True,'pump_on_s':10800,'pump_off_s':3600,'pump_during_heat':True}.items())):
 settings.update({'pump_cycle_enabled':True,'pump_on_s':180,'pump_off_s':60,'pump_during_heat':True})
 save_settings(settings)
BOOT_MONOTONIC=time.monotonic()
SENSOR_STATS={"last_ok":None,"errors":0,"last_raw":None,"last_error":None}
lock=threading.RLock(); GPIO=None
if cfg['mode']=='bench':
 try:
  import RPi.GPIO as GPIO
  GPIO.setwarnings(False);GPIO.setmode(GPIO.BCM)
  GPIO.setup(int(cfg['pump_gpio']),GPIO.OUT,initial=GPIO.HIGH)
  GPIO.setup(int(cfg['heater_gpio']),GPIO.OUT,initial=GPIO.LOW)
 except Exception as exc: raise SystemExit('Falha na configuração dos GPIOs: '+str(exc))

def text(node,key,default=''):
 el=node.find(key);return (el.text or '').strip() if el is not None else default

def recipe_load(path):
 root=ET.parse(path).getroot();r=root.find('RECIPE') if root.tag=='RECIPES' else root
 if r is None or r.tag!='RECIPE':raise ValueError('BeerXML sem RECIPE')
 steps=[]
 for x in r.findall('./MASH/MASH_STEPS/MASH_STEP'):
  target=float(text(x,'STEP_TEMP'));minutes=float(text(x,'STEP_TIME'))
  if not 10<=target<=95 or not 0<minutes<=240:raise ValueError('Etapa inválida no BeerXML')
  steps.append({'name':text(x,'NAME','Mostura'),'kind':'mash','target':target,'minutes':minutes})
 boil=float(text(r,'BOIL_TIME','60'))
 if not 0<boil<=240:raise ValueError('Fervura inválida')
 steps.append({'name':'Fervura','kind':'boil','target':None,'minutes':boil})
 events=[]
 for x in r.findall('./MISCS/MISC'):
  if text(x,'TYPE').lower()=='water agent':
   events.append({'id':'salt-'+str(len(events)),'name':text(x,'NAME'),'amount':text(x,'DISPLAY_AMOUNT') or str(float(text(x,'AMOUNT','0'))*1000)+' g','phase':text(x,'USE'),'at_remaining':None})
 for x in r.findall('./HOPS/HOP'):
  if text(x,'USE').lower()=='boil':
   events.append({'id':'boil-'+str(len(events)),'name':text(x,'NAME'),'amount':str(round(float(text(x,'AMOUNT','0'))*1000,2))+' g','phase':'Boil','at_remaining':float(text(x,'TIME','0'))})
 if not text(r,'NAME'):raise ValueError('Receita sem nome')
 return {'name':text(r,'NAME'),'batch_l':float(text(r,'BATCH_SIZE','0')),'steps':steps,'events':events,'source':path.name}

RECIPES=BASE/'receitas';RECIPES.mkdir(exist_ok=True)
HISTORY=BASE/'dados'/'historico.jsonl';HISTORY.parent.mkdir(exist_ok=True)
recipes={}
for p in RECIPES.glob('*.xml'):
 try: recipes[p.name]=recipe_load(p)
 except Exception as exc: print('Receita ignorada',p.name,exc)
if not recipes:raise SystemExit('Nenhum BeerXML válido em receitas/')
first=next(iter(recipes))
s={'version':'0.11Beta CONTROLE DINÂMICO','mode':cfg['mode'],'temperature':None,'sensor_ok':False,'sensor_fault_test':False,'virtual_temperature':None,'pump':False,'heater':False,'heater_requested':False,'heater_physical_enabled':bool(cfg['mode']=='bench' and cfg.get('enable_heater_gpio_test')),'pump_physical_enabled':bool(cfg['mode']=='bench' and cfg.get('enable_pump_test')),'heater_gpio':int(cfg['heater_gpio']),'pump_gpio':int(cfg['pump_gpio']),'hysteresis_c':settings['hysteresis_c'],'recipe_id':first,'recipe':recipes[first],'status':'IDLE','step_index':0,'remaining_s':0,'phase':'','pending_events':[],'confirmed_events':[],'test_speed':1,'message':'Pronto para teste de bancada','history_written':False,'run_id':None,'started_at':None,'samples':[],'phase_log':[],'event_log':[],'pump_manual':None,'pump_cycle_epoch':time.monotonic(),'boil_window_epoch':time.monotonic(),'boil_confirmed':False,'heater_manual_enabled':True,'wash_confirmed':False}
last_tick=time.monotonic()
CHECKPOINT=BASE/'dados'/'processo.json'

def save_checkpoint():
 # Gravação atômica; nenhuma saída física é restaurada após reinicialização.
 snapshot={k:s[k] for k in ('recipe_id','status','step_index','remaining_s','phase','confirmed_events','pending_events','test_speed','history_written','run_id','started_at','samples','phase_log','event_log','boil_confirmed','wash_confirmed')}
 temp=CHECKPOINT.with_suffix('.tmp')
 with temp.open('w',encoding='utf-8') as f:
  json.dump(snapshot,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
 os.replace(temp,CHECKPOINT)

def restore_checkpoint():
 if not CHECKPOINT.exists():return
 try:
  old=json.loads(CHECKPOINT.read_text(encoding='utf-8'))
  if old.get('recipe_id') not in recipes:return
  s['recipe_id']=old['recipe_id'];s['recipe']=recipes[old['recipe_id']]
  s['step_index']=max(0,min(int(old['step_index']),len(s['recipe']['steps'])-1))
  s['remaining_s']=max(0,float(old['remaining_s']))
  s['confirmed_events']=[e for e in old.get('confirmed_events',[]) if isinstance(e,str)]
  s['test_speed']=1;s['history_written']=bool(old.get('history_written',False))
  for k in ('run_id','started_at','samples','phase_log','event_log'):s[k]=old.get(k,[] if k.endswith('log') or k=='samples' else None)
  s['boil_confirmed']=bool(old.get('boil_confirmed',False))
  s['wash_confirmed']=bool(old.get('wash_confirmed',False))
  s['samples']=s['samples'][-30000:]
  s['status']='RECOVERY_REQUIRED' if old.get('status') in ('RUNNING','PAUSED','AWAIT_NEXT') else old.get('status','IDLE')
  s['phase']='RECOVERY_REQUIRED' if s['status']=='RECOVERY_REQUIRED' else old.get('phase','')
  # Reconstrói os avisos somente a partir da receita selecionada; não confia no conteúdo serializado.
  valid={e['id']:e for e in s['recipe']['events']}
  pending_ids=old.get('pending_events',[])
  s['pending_events']=[valid[e['id']] for e in pending_ids if isinstance(e,dict) and e.get('id') in valid and e['id'] not in s['confirmed_events']]
  s['message']='Processo interrompido: saídas desligadas. Revise os avisos pendentes antes de retomar.' if s['status']=='RECOVERY_REQUIRED' else s['message']
 except (ValueError,KeyError,TypeError,OSError) as exc:print('Checkpoint inválido:',exc)
restore_checkpoint()

def heat(on):
 # Temperatura virtual e falha bloqueiam SEMPRE a saída física.
 allowed=cfg['mode']=='bench' and cfg.get('enable_heater_gpio_test',False) and s['sensor_ok'] and not s['sensor_fault_test'] and s['virtual_temperature'] is None
 physical=bool(on and allowed and s['heater_manual_enabled'])
 if GPIO is not None:GPIO.output(int(cfg['heater_gpio']),GPIO.HIGH if physical else GPIO.LOW)
 s['heater']=physical;s['heater_requested']=bool(on and s['heater_manual_enabled'])

def pump(on):
 actual=bool(on and cfg['mode']=='bench' and cfg.get('enable_pump_test',False) and s['sensor_ok'] and not s['sensor_fault_test'] and s['virtual_temperature'] is None)
 if GPIO is not None:GPIO.output(int(cfg['pump_gpio']),GPIO.LOW if actual else GPIO.HIGH)
 s['pump']=actual

def history(reason):
 if s['history_written']:return
 record={'id':s['run_id'] or uuid.uuid4().hex,'timestamp':s['started_at'] or time.strftime('%Y-%m-%dT%H:%M:%S%z'),'finished_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'recipe':s['recipe']['name'],'recipe_id':s['recipe_id'],'result':reason,'confirmed_events':list(s['confirmed_events']),'test_speed':s['test_speed'],'samples':list(s['samples']),'phase_log':list(s['phase_log']),'event_log':list(s['event_log'])}
 with HISTORY.open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
 s['history_written']=True

def mark_event(kind,detail=''):
 s['event_log'].append({'at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'type':kind,'detail':detail})

def history_records():
 if not HISTORY.exists():return []
 result=[]
 for line in HISTORY.read_text(encoding='utf-8').splitlines():
  try:
   r=json.loads(line)
   if isinstance(r,dict):result.append(r)
  except ValueError:pass
 return result

def sample():
 if not s['run_id'] or s['history_written'] or s['status'] not in ('RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'):return
 now=time.time()
 if s['samples'] and now-s['samples'][-1]['ts']<settings['history_interval_s']:return
 step=s['recipe']['steps'][s['step_index']]
 s['samples'].append({'ts':round(now,1),'phase':step['name'],'step_index':s['step_index'],'temperature':s['temperature'],'target':settings['boil_reference_c'] if step['kind']=='boil' else step['target'],'sensor_ok':s['sensor_ok'],'heater':s['heater'],'heater_requested':s['heater_requested'],'pump':s['pump'],'status':s['status']})
 s['samples']=s['samples'][-30000:]
 save_checkpoint()

def step_start():
 s['pump_manual']=None;s['heater_manual_enabled']=True;s['pump_cycle_epoch']=time.monotonic();s['boil_window_epoch']=time.monotonic();s['boil_confirmed']=False
 step=s['recipe']['steps'][s['step_index']]
 s['phase_log'].append({'at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'step_index':s['step_index'],'name':step['name']});mark_event('PHASE_START',step['name'])
 s['remaining_s']=step['minutes']*60;s['phase']='WAIT_TARGET' if step['kind']=='mash' else 'WAIT_BOIL_CONFIRM';s['status']='RUNNING';s['pending_events']=[]
 if s['step_index']==0:
  for e in s['recipe']['events']:
   if e['phase'].lower()=='mash' and e['id'] not in s['confirmed_events']:s['pending_events'].append(e)

def last_mash_step():
 steps=s['recipe']['steps']
 return s['step_index']<len(steps)-1 and steps[s['step_index']]['kind']=='mash' and steps[s['step_index']+1]['kind']=='boil'

def begin_wash():
 # A lavagem é uma confirmação operacional, não uma fase BeerXML adicional.
 # O pré-aquecimento inicia imediatamente; a bomba permanece desligada.
 s['phase']='WASH_PENDING';s['status']='RUNNING';s['wash_confirmed']=False
 s['remaining_s']=0;s['pump_manual']=None;pump(False)
 mark_event('WASH_STARTED','Aguardando confirmação do término da lavagem; pré-aquecimento da fervura iniciado')

def pump_phase_allowed():
 step=s['recipe']['steps'][s['step_index']]
 # Mash-in, its rests, and mash-out are the mash stages. Never allow the pump in wash/boil or later.
 return step['kind']=='mash' and s['status']=='RUNNING' and s['phase'] in ('WAIT_TARGET','COUNTDOWN')

BOIL_WINDOW_S=10.0  # SSR por janela de tempo, nunca PWM de alta frequência.
# PID experimental: exclusivamente mostura; desativado por padrão.
# Kp [%/°C], Ki [%/(°C.s)], Kd [%.s/°C]. Sem autotuning.
PID={'integral':0.0,'last_temp':None,'last_time':None,'target':None,'power_pct':0.0,'window_epoch':time.monotonic()}
def pid_reset():
 PID.update(integral=0.0,last_temp=None,last_time=None,target=None,power_pct=0.0,window_epoch=time.monotonic())
def pid_heat(target):
 now=time.monotonic();temp=s['temperature']
 if PID['target']!=target or PID['last_time'] is None:
  pid_reset();PID['target']=target;PID['last_time']=now;PID['last_temp']=temp
 dt=min(5.0,max(0.0,now-PID['last_time']))
 error=target-temp
 # Corte independente do PID para evitar aquecimento em sobretemperatura.
 if temp>=target+1.5:
  PID['integral']=min(0.0,PID['integral']);PID['power_pct']=0.0
 else:
  derivative=0.0 if not dt else -(temp-PID['last_temp'])/dt
  candidate=PID['integral']+error*dt
  raw=settings['pid_kp']*error+settings['pid_ki']*candidate+settings['pid_kd']*derivative
  # Integração condicional: não acumular quando saturado na direção do erro.
  if not ((raw>100 and error>0) or (raw<0 and error<0)):
   PID['integral']=max(-10000.0,min(10000.0,candidate))
  raw=settings['pid_kp']*error+settings['pid_ki']*PID['integral']+settings['pid_kd']*derivative
  PID['power_pct']=max(0.0,min(100.0,raw))
 PID['last_time']=now;PID['last_temp']=temp
 duty=PID['power_pct']/100.0
 heat(duty>0 and (now-PID['window_epoch'])%BOIL_WINDOW_S < BOIL_WINDOW_S*duty)

def update(dt):
 if not s['sensor_ok'] or s['temperature'] is None:
  pid_reset();heat(False);pump(False)
  if s['status']=='RUNNING':s['status']='FAULT';s['phase']='FAULT';history('FAULT')
  return
 if s['status']!='RUNNING':pid_reset();heat(False);pump(False);return
 step=s['recipe']['steps'][s['step_index']]
 if s['phase']=='WASH_PENDING':
  pid_reset();pump(False)
  if s['pending_events']:heat(False);return
  # Pré-aquecimento controlado por histerese até a referência de fervura.
  target=settings['boil_reference_c']
  if s['temperature']>=target:s['heater_requested']=False
  elif s['temperature']<=target-s['hysteresis_c']:s['heater_requested']=True
  heat(s['heater_requested']);return
 if s['pending_events']:
  pid_reset();heat(False);pump(False);return
 if step['kind']=='boil' and s['phase']=='WAIT_BOIL_CONFIRM':
  # A referência definida pelo usuário dispara automaticamente o cronômetro.
  # Não debitar dt do ciclo de aquecimento que atingiu o alvo.
  if s['temperature']>=settings['boil_reference_c']:
   s['phase']='COUNTDOWN';s['boil_confirmed']=True;s['boil_window_epoch']=time.monotonic()
   mark_event('BOIL_STARTED','Temperatura configurada atingida; cronômetro iniciado')
 if s['phase']=='WAIT_TARGET':
  if s['temperature']>=step['target']:s['phase']='COUNTDOWN'
 elif s['phase']=='COUNTDOWN':
  previous=s['remaining_s'];s['remaining_s']=max(0,previous-dt*s['test_speed'])
  if step['kind']=='boil':
   for e in s['recipe']['events']:
    if e['phase'].lower()=='boil' and e['id'] not in s['confirmed_events'] and previous>e['at_remaining']*60>=s['remaining_s']:s['pending_events'].append(e)
  if s['remaining_s']==0:
   if last_mash_step():
    begin_wash();return
   # Rampas consecutivas de mostura (incluindo Mash In -> Mash Out) avançam
   # automaticamente ao concluir a contagem, sem confirmação do operador.
   following=s['step_index']+1
   if step['kind']=='mash' and following<len(s['recipe']['steps']) and s['recipe']['steps'][following]['kind']=='mash':
    heat(False);pump(False);s['step_index']=following;step_start();return
   s['phase']='AWAIT_NEXT' if s['step_index']<len(s['recipe']['steps'])-1 else 'COMPLETE';s['status']='AWAIT_NEXT' if s['phase']=='AWAIT_NEXT' else 'COMPLETE'
   heat(False);pump(False)
   if s['status']=='COMPLETE':history('COMPLETE')
   return
 if s['pending_events']:
  pid_reset();heat(False);pump(False);return
 if step['kind']=='mash' and s['phase'] in ('WAIT_TARGET','COUNTDOWN'):
  if settings['pid_enabled'] and s['heater_manual_enabled']:
   pid_heat(step['target'])
  else:
   pid_reset()
   if s['temperature']>=step['target']:s['heater_requested']=False
   elif s['temperature']<=step['target']-s['hysteresis_c']:s['heater_requested']=True
   heat(s['heater_requested'])
 elif step['kind']=='boil' and s['phase']=='WAIT_BOIL_CONFIRM':
  # Aquecer até a referência antes de iniciar a contagem.
  pid_reset();s['heater_requested']=s['heater_manual_enabled']
  heat(s['heater_manual_enabled'])
 elif step['kind']=='boil' and s['phase']=='COUNTDOWN' and s['boil_confirmed']:
  pid_reset()
  # Temperatura de referência é um limite inferior para solicitar potência,
  # não um gatilho para ligar a resistência acima da referência configurada.
  power=settings['boil_power_pct'] if s['temperature']<=settings['boil_reference_c'] else 0
  heat(power>0 and (time.monotonic()-s['boil_window_epoch'])%BOIL_WINDOW_S < BOIL_WINDOW_S*power/100)
 else:pid_reset();heat(False)
 # O bloqueio por fase prevalece também sobre o comando manual.
 if not pump_phase_allowed():pump(False);return
 if s['pump_manual'] is not None:pump(s['pump_manual']);return
 allowed_phase=(pump_phase_allowed() and (s['phase']=='COUNTDOWN' or (s['phase']=='WAIT_TARGET' and settings['pump_during_heat'])))
 if allowed_phase and settings['pump_cycle_enabled']:
  period=settings['pump_on_s']+settings['pump_off_s']
  pump((time.monotonic()-s['pump_cycle_epoch'])%period<settings['pump_on_s'])
 else:pump(False)

def sensor_loop():
 global last_tick
 while True:
  with lock:
   if s['sensor_fault_test']:s['temperature']=None;s['sensor_ok']=False
   elif s['virtual_temperature'] is not None:s['temperature']=s['virtual_temperature'];s['sensor_ok']=True
   elif cfg['mode']=='simulation':s['temperature']=round(24+2*((time.monotonic()/30)%1),2);s['sensor_ok']=True
   else:
    try:
     files=list(Path('/sys/bus/w1/devices').glob('28-*/w1_slave'))
     if len(files)!=1:raise ValueError('Esperado exatamente um DS18B20')
     raw=files[0].read_text();lines=raw.splitlines()
     if not lines or not lines[0].endswith('YES'):raise ValueError('CRC inválido')
     value=float(lines[-1].split('t=')[-1])/1000
     if not -10<=value<=110:raise ValueError('Leitura fora da faixa')
     s['temperature']=round(value+settings['t1_offset_c'],2);s['sensor_ok']=True;SENSOR_STATS.update(last_ok=time.time(),last_raw=value,last_error=None)
    except Exception as exc:s['temperature']=None;s['sensor_ok']=False;s['message']=str(exc);SENSOR_STATS['errors']+=1;SENSOR_STATS['last_error']=str(exc)
   now=time.monotonic();old=(s['status'],s['phase'],int(s['remaining_s']));update(min(now-last_tick,3));last_tick=now
   sample()
   if old!=(s['status'],s['phase'],int(s['remaining_s'])):save_checkpoint()
  time.sleep(settings['sensor_interval_s'])

def _read_system():
 data={'uptime_s':round(time.monotonic()-BOOT_MONOTONIC),'cpu_percent':None,'cpu_temperature_c':None,'memory_available_mb':None,'disk_free_mb':None,'undervoltage':None,'ip':None,'hostname':socket.gethostname(),'web_port':cfg.get('port',18765)}
 try:
  raw=Path('/sys/class/thermal/thermal_zone0/temp').read_text().strip();data['cpu_temperature_c']=round(int(raw)/1000,1)
 except (OSError,ValueError):pass
 try:
  for line in Path('/proc/meminfo').read_text().splitlines():
   if line.startswith('MemAvailable:'):data['memory_available_mb']=round(int(line.split()[1])/1024);break
 except (OSError,ValueError,IndexError):pass
 try:data['disk_free_mb']=round(shutil.disk_usage(BASE).free/1048576)
 except OSError:pass
 try:
  load=os.getloadavg()[0];data['cpu_load_1m']=round(load,2)
 except (OSError,AttributeError):data['cpu_load_1m']=None
 try:
  import subprocess
  v=subprocess.run(['vcgencmd','get_throttled'],capture_output=True,text=True,timeout=1)
  if v.returncode==0:
   code=int(v.stdout.strip().split('=')[-1],16);data['undervoltage']={'current':bool(code&1),'occurred':bool(code&(1<<16))}
 except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):pass
 try:
  sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.settimeout(.2);sock.connect(('192.0.2.1',9));data['ip']=sock.getsockname()[0];sock.close()
 except OSError:pass
 return data

def _diagnostic_reasons():
 reasons=[]
 if s['status']=='RECOVERY_REQUIRED':reasons.append('Recuperação manual pendente após reinicialização')
 if s['status']=='PAUSED':reasons.append('Processo pausado')
 if s['status'] not in ('RUNNING','PAUSED'):reasons.append('Processo não está em execução')
 if not s['sensor_ok']:reasons.append('Sensor T1 sem leitura válida')
 if s['sensor_fault_test']:reasons.append('Falha de sensor simulada')
 if s['virtual_temperature'] is not None:reasons.append('Temperatura virtual: saída física bloqueada')
 if not cfg.get('enable_heater_gpio_test'):reasons.append('Saída física da resistência desabilitada')
 if not s['heater_manual_enabled']:reasons.append('Aquecimento bloqueado manualmente')
 if s['pending_events']:reasons.append('Confirmação de adição pendente')
 if s['phase']=='WASH_PENDING':reasons.append('Lavagem pendente: pré-aquecimento da fervura permitido')
 if s['phase']=='WAIT_BOIL_CONFIRM':reasons.append('Aquecendo até a temperatura configurada para início da fervura')
 if s['heater_requested'] and not s['heater'] and not reasons:reasons.append('Controle térmico: SSR no intervalo desligado')
 if not reasons:reasons.append('Sem bloqueios de segurança identificados')
 pump_reasons=[]
 if not pump_phase_allowed():pump_reasons.append('Bomba bloqueada fora da mostura ou com processo parado')
 if not s['sensor_ok']:pump_reasons.append('Sensor T1 inválido')
 if not cfg.get('enable_pump_test'):pump_reasons.append('Saída física da bomba desabilitada')
 if s['virtual_temperature'] is not None:pump_reasons.append('Temperatura virtual: saída física bloqueada')
 if not pump_reasons:pump_reasons.append('Comando manual' if s['pump_manual'] is not None else 'Controle cíclico / fase de aquecimento')
 return reasons,pump_reasons

def diagnostic_snapshot():
 hr,pr=_diagnostic_reasons()
 return {'system':_read_system(),'version':s['version'],'mode':cfg['mode'],'process':{'status':s['status'],'phase':s['phase'],'recipe':s['recipe']['name'],'pending_count':len(s['pending_events']),'recovery_required':s['status']=='RECOVERY_REQUIRED'},'sensor':{'gpio':cfg['sensor_gpio'],'ok':s['sensor_ok'],'raw_c':SENSOR_STATS['last_raw'],'corrected_c':s['temperature'],'offset_c':settings['t1_offset_c'],'last_ok_age_s':None if SENSOR_STATS['last_ok'] is None else round(time.time()-SENSOR_STATS['last_ok'],1),'errors':SENSOR_STATS['errors'],'last_error':SENSOR_STATS['last_error'],'virtual':s['virtual_temperature'] is not None},'outputs':{'heater_gpio':cfg['heater_gpio'],'pump_gpio':cfg['pump_gpio'],'heater_enabled':s['heater_physical_enabled'],'pump_enabled':s['pump_physical_enabled'],'heater_command':s['heater_requested'],'heater_gpio_command':s['heater'],'pump_gpio_command':s['pump'],'pump_mode':'Manual' if s['pump_manual'] is not None else 'Cíclico' if settings['pump_cycle_enabled'] else 'Sem ciclo','heater_reasons':hr,'pump_reasons':pr,'pid_enabled':settings['pid_enabled'],'pid_power_pct':round(PID['power_pct'],1),'pid_kp':settings['pid_kp'],'pid_ki':settings['pid_ki'],'pid_kd':settings['pid_kd']},'events':list(s['event_log'][-8:])[::-1]}

class Handler(BaseHTTPRequestHandler):
 def reply(self,data,status=200):
  raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  p=urlparse(self.path).path
  if p=='/api/mobile/state':
   # Telemetria apenas de leitura, sem parâmetros de configuração ou comandos.
   with lock:
    steps=s['recipe']['steps'];index=s['step_index']
    step=steps[index] if 0<=index<len(steps) else None
    following=steps[index+1] if 0<=index+1<len(steps) else None
    self.reply({'version':'0.11Beta','recipe':s['recipe']['name'],
     'status':s['status'],'phase':s['phase'],
     'step':None if step is None else {'name':step['name'],'kind':step['kind'],'target':step.get('target')},
     'next_step':None if following is None else {'name':following['name'],'target':following.get('target')},
     'temperature':s['temperature'] if s['sensor_ok'] else None,'sensor_ok':s['sensor_ok'],
     'target':settings['boil_reference_c'] if step and step['kind']=='boil' else step.get('target') if step else None,
     'remaining_s':s['remaining_s'],'pump':bool(s['pump']),'heater':bool(s['heater']),
     'pid_enabled':settings['pid_enabled'],'pid_power_pct':round(PID['power_pct'],1),
     'heater_power_pct':(round(PID['power_pct'],1) if s['status']=='RUNNING' and step and step['kind']=='mash' and settings['pid_enabled'] and s['heater_manual_enabled'] and not s['pending_events']
       else (100 if s['status']=='RUNNING' and step and step['kind']=='mash' and s['heater_requested'] and not s['pending_events'] else 0) if step and step['kind']=='mash'
       else (100 if s['status']=='RUNNING' and s['phase']=='WAIT_BOIL_CONFIRM' and s['heater_manual_enabled'] and not s['pending_events']
       else settings['boil_power_pct'] if s['status']=='RUNNING' and s['phase']=='COUNTDOWN' and s['boil_confirmed'] and s['temperature'] is not None and s['temperature']<=settings['boil_reference_c'] and not s['pending_events']
       else 0) if step and step['kind']=='boil' else 0),
     'pending_events':[{'id':e.get('id'),'name':e.get('name'),'amount':e.get('amount'),'phase':e.get('phase')} for e in s['pending_events']],
     'message':s.get('message',''),
     'samples':[{'ts':a.get('ts'),'temperature':a.get('temperature'),'target':a.get('target')} for a in s['samples'][-240:]]});return
  if p=='/api/state':
   with lock:self.reply(dict(s,pump_phase_allowed=pump_phase_allowed(),pump_cycle_enabled=settings['pump_cycle_enabled'],pump_on_s=settings['pump_on_s'],pump_off_s=settings['pump_off_s'],boil_power_pct=settings['boil_power_pct'],boil_reference_c=settings['boil_reference_c'],pid_enabled=settings['pid_enabled'],pid_power_pct=round(PID['power_pct'],1),pid_kp=settings['pid_kp'],pid_ki=settings['pid_ki'],pid_kd=settings['pid_kd'],pump_next_s=(None if not pump_phase_allowed() or s['pump_manual'] is not None or not settings['pump_cycle_enabled'] else max(0, (settings['pump_on_s'] if s['pump'] else settings['pump_on_s']+settings['pump_off_s'])-(time.monotonic()-s['pump_cycle_epoch'])%(settings['pump_on_s']+settings['pump_off_s']))),current_target_c=(settings['boil_reference_c'] if s['phase']=='WASH_PENDING' or s['recipe']['steps'][s['step_index']]['kind']=='boil' else s['recipe']['steps'][s['step_index']]['target']),recipes=[{'id':k,'name':v['name']} for k,v in recipes.items()]));return
  if p=='/api/diagnostics':
   with lock:self.reply(diagnostic_snapshot());return
  if p=='/api/settings':
   with lock:self.reply({'values':settings,'reserved':sorted(SETTINGS_RESERVED),'hardware':{'mode':cfg['mode'],'sensor_gpio':cfg['sensor_gpio'],'heater_gpio':cfg['heater_gpio'],'pump_gpio':cfg['pump_gpio'],'enable_heater_gpio_test':cfg['enable_heater_gpio_test'],'enable_pump_test':cfg['enable_pump_test']},'safety':{'sensor_failure_heater_off':True,'automatic_restart':False,'recovery_confirmation':True}});return
  if p=='/api/recipe/detail':
   from urllib.parse import parse_qs
   key=parse_qs(urlparse(self.path).query).get('id',[''])[0]
   with lock:
    if key not in recipes:self.reply({'error':'Receita não encontrada'},404);return
    self.reply({'id':key,'recipe':recipes[key],'xml':(RECIPES/key).read_text(encoding='utf-8')});return
  if p=='/api/history':
   self.reply([{k:v for k,v in r.items() if k not in ('samples','phase_log','event_log')} for r in history_records()]);return
  if p=='/api/history/detail':
   from urllib.parse import parse_qs
   key=parse_qs(urlparse(self.path).query).get('id',[''])[0]
   record=next((r for r in history_records() if r.get('id')==key),None)
   if record is None:self.reply({'error':'Registro não encontrado'},404);return
   self.reply(record);return
  if p in ('/mobile','/mobile/','/mobile.html','/mobile.css','/mobile.js'):
   name='mobile.html' if p in ('/mobile','/mobile/') else p.lstrip('/')
   file=BASE/'web'/name;raw=file.read_bytes();self.send_response(200)
   self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8'}[file.suffix[1:]])
   self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
  if p in ('/','/index.html','/app.js','/app.css','/beergo-logo-color.png','/beergo-logo-color.svg','/beergo-pi-logo-lupulo.png','/mobile-setup-aprovado.png'):
   name='index.html' if p=='/' else p.lstrip('/');file=BASE/'web'/name
   raw=file.read_bytes();self.send_response(200);self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','png':'image/png','svg':'image/svg+xml'}[file.suffix[1:]]);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
  self.reply({'error':'Não encontrado'},404)
 def do_POST(self):
  p=urlparse(self.path).path
  try:
   n=int(self.headers.get('Content-Length','0'))
   if n>300000:raise ValueError('Requisição muito grande')
   body=json.loads(self.rfile.read(n)) if n else {}
   with lock:
    if p=='/api/settings/save':
     new=validate_settings(body.get('values'))
     # Gravação primeiro; depois aplica todos os parâmetros operacionais sob o mesmo lock.
     old_settings=settings.copy();save_settings(new);settings.update(new);s['hysteresis_c']=settings['hysteresis_c']
     if any(old_settings[k]!=new[k] for k in ('pid_enabled','pid_kp','pid_ki','pid_kd')):pid_reset()
     if old_settings['pump_cycle_enabled']!=new['pump_cycle_enabled'] or old_settings['pump_on_s']!=new['pump_on_s'] or old_settings['pump_off_s']!=new['pump_off_s']:s['pump_cycle_epoch']=time.monotonic()
     if old_settings['boil_power_pct']!=new['boil_power_pct']:s['boil_window_epoch']=time.monotonic()
     if s['run_id'] and s['status'] in ('RUNNING','PAUSED','AWAIT_NEXT'):
      
      for k in new:
       if old_settings[k]!=new[k]:mark_event('SETTING_CHANGED',json.dumps({'key':k,'old':old_settings[k],'new':new[k]},ensure_ascii=False))
     self.reply({'ok':True,'values':settings,'reserved':sorted(SETTINGS_RESERVED)});return
    if p=='/api/history/delete':
     key=str(body.get('id',''))
     records=history_records()
     if not any(r.get('id')==key for r in records):raise ValueError('Registro não encontrado ou legado sem identificador')
     temp=HISTORY.with_suffix('.tmp')
     with temp.open('w',encoding='utf-8') as f:
      for r in records:
       if r.get('id')!=key:f.write(json.dumps(r,ensure_ascii=False)+'\n')
      f.flush();os.fsync(f.fileno())
     os.replace(temp,HISTORY)
    elif p=='/api/recipe/select':
     if s['status'] in ('RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'):raise ValueError('Encerre o processo antes de trocar receita')
     key=body['id'];s['recipe']=recipes[key];s['recipe_id']=key;s['status']='IDLE';s['step_index']=0;s['confirmed_events']=[];s['history_written']=False
    elif p=='/api/recipe/import':
     if s['status'] in ('RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'):raise ValueError('Encerre o processo antes de importar')
     name=str(body.get('filename',''))
     if not name.lower().endswith('.xml') or '/' in name or '\\' in name or name.startswith('.'):raise ValueError('Nome de arquivo BeerXML inválido')
     xml=str(body.get('xml',''))
     if len(xml.encode('utf-8'))>250000:raise ValueError('BeerXML excede 250 kB')
     import io
     ET.parse(io.StringIO(xml))
     tmp=RECIPES/(name+'.tmp');tmp.write_text(xml,encoding='utf-8')
     try:recipe=recipe_load(tmp)
     except Exception:tmp.unlink(missing_ok=True);raise
     dest=RECIPES/name
     if dest.exists():tmp.unlink(missing_ok=True);raise ValueError('Já existe receita com este nome')
     tmp.replace(dest);recipe['source']=name;recipes[name]=recipe
     s['message']='BeerXML importado: '+recipe['name']
    elif p=='/api/recipe/update':
     if s['status'] in ('RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'):raise ValueError('Encerre o processo antes de alterar receitas')
     key=body.get('id','');xml=body.get('xml','')
     if key not in recipes:raise ValueError('Receita não encontrada')
     if not isinstance(xml,str) or len(xml.encode('utf-8'))>250000:raise ValueError('BeerXML inválido ou excede 250 kB')
     ET.parse(io.StringIO(xml))
     tmp=RECIPES/(key+'.tmp');tmp.write_text(xml,encoding='utf-8')
     try:recipe=recipe_load(tmp)
     except Exception:tmp.unlink(missing_ok=True);raise
     dest=RECIPES/key;os.replace(tmp,dest);recipe['source']=key;recipes[key]=recipe
     if s['recipe_id']==key:s['recipe']=recipe;s['step_index']=0;s['remaining_s']=0;s['phase']='';s['status']='IDLE';s['confirmed_events']=[];s['pending_events']=[];s['history_written']=False
     s['message']='Receita alterada: '+recipe['name']
    elif p=='/api/recipe/delete':
     if s['status'] in ('RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'):raise ValueError('Encerre o processo antes de excluir receitas')
     key=body.get('id','')
     if key not in recipes:raise ValueError('Receita não encontrada')
     if key==s['recipe_id']:raise ValueError('Selecione outra receita antes de excluir a receita atual')
     if len(recipes)<=1:raise ValueError('É necessário manter ao menos uma receita')
     (RECIPES/key).unlink();del recipes[key];s['message']='Receita excluída'
    elif p=='/api/process/recover':
     if s['status']!='RECOVERY_REQUIRED':raise ValueError('Não há processo para recuperar')
     if not s['sensor_ok'] or s['virtual_temperature'] is not None:raise ValueError('Recuperação requer sensor real válido')
     s['status']='PAUSED';s['phase']='WAIT_TARGET' if s['recipe']['steps'][s['step_index']]['kind']=='mash' else 'WAIT_BOIL_CONFIRM';s['message']='Processo recuperado PAUSADO; confira avisos antes de retomar';heat(False);pump(False)
    elif p=='/api/test/virtual':
     val=body.get('temperature')
     if val is not None and (isinstance(val,bool) or not isinstance(val,(int,float)) or not 10<=val<=100):raise ValueError('Temperatura virtual 10–100 °C')
     heat(False);s['virtual_temperature']=val;s['message']='Temperatura virtual: saída SSR fisicamente bloqueada' if val is not None else 'Leitura real restaurada'
    elif p=='/api/test/fault':
     s['sensor_fault_test']=bool(body['on'])
     if s['sensor_fault_test']:s['sensor_ok']=False;s['temperature']=None;update(0)
    elif p=='/api/test/speed':
     val=int(body['speed'])
     if val not in (1,10,60):raise ValueError('Velocidade deve ser 1, 10 ou 60')
     s['test_speed']=val
    elif p=='/api/process/start':
     if s['status'] in ('RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'):raise ValueError('Processo em andamento')
     if not s['sensor_ok']:raise ValueError('Sensor inválido')
     s['step_index']=0;s['confirmed_events']=[];s['history_written']=False;s['run_id']=uuid.uuid4().hex;s['started_at']=time.strftime('%Y-%m-%dT%H:%M:%S%z');s['samples']=[];s['phase_log']=[];s['event_log']=[];step_start()
    elif p=='/api/process/confirm-event':
     key=body['id'];pending=next((e for e in s['pending_events'] if e['id']==key),None)
     if pending is None:raise ValueError('Aviso não está pendente')
     mark_event('ADDITION_CONFIRMED',pending['name']);s['confirmed_events'].append(key);s['pending_events']=[e for e in s['pending_events'] if e['id']!=key]
    elif p=='/api/process/boil-confirm':
     if s['phase']!='WAIT_BOIL_CONFIRM':raise ValueError('Fervura não aguarda confirmação')
     raise ValueError('Confirmação manual desativada; a fervura inicia ao atingir a temperatura configurada')
    elif p=='/api/process/wash-confirm':
     if s['phase']!='WASH_PENDING' or s['status']!='RUNNING':raise ValueError('Não há confirmação de lavagem pendente')
     if s['pending_events']:raise ValueError('Confirme as adições pendentes antes de concluir a lavagem')
     s['wash_confirmed']=True;mark_event('WASH_CONFIRMED','Término de lavagem confirmado')
     # Passa à fase de fervura; o cronômetro inicia automaticamente na referência.
     heat(False);s['step_index']+=1;step_start()
    elif p=='/api/process/next':
     if s['status'] not in ('RUNNING','PAUSED','AWAIT_NEXT'):raise ValueError('Não há fase ativa para avançar')
     if s['pending_events']:raise ValueError('Confirme as adições pendentes antes de avançar')
     if s['phase']=='WASH_PENDING':raise ValueError('Confirme o término da lavagem antes de avançar')
     if s['step_index']>= len(s['recipe']['steps'])-1:raise ValueError('Esta é a última fase da receita')
     if last_mash_step():begin_wash()
     else:heat(False);s['step_index']+=1;step_start()
    elif p=='/api/process/pause':
     if s['status']!='RUNNING':raise ValueError('Processo não está em execução')
     mark_event('PAUSED');s['status']='PAUSED';heat(False)
    elif p=='/api/process/resume':
     if s['status']!='PAUSED' or not s['sensor_ok'] or (cfg['mode']=='bench' and s['virtual_temperature'] is not None):raise ValueError('Retomada requer sensor válido; em bancada, sensor real')
     if s['pending_events']:raise ValueError('Confirme os avisos pendentes antes de retomar')
     mark_event('RESUMED');s['status']='RUNNING'
    elif p=='/api/process/finalize':
     if s['status'] not in ('RUNNING','PAUSED','AWAIT_NEXT'):raise ValueError('Não há brassagem ativa para finalizar')
     if s['pending_events']:raise ValueError('Confirme as adições pendentes antes de finalizar')
     mark_event('FINALIZED_BY_OPERATOR');heat(False);pump(False);history('COMPLETE');s['status']='COMPLETE';s['phase']='COMPLETE'
    elif p=='/api/process/stop':
     if s['status'] not in ('RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'):raise ValueError('Não há brassagem ativa para parar')
     mark_event('STOPPED_BY_OPERATOR');heat(False);pump(False);history('STOPPED');s['status']='STOPPED';s['phase']='STOPPED';s['pending_events']=[]
    elif p=='/api/process/interrupt':
     if s['status'] not in ('RUNNING','PAUSED','AWAIT_NEXT','RECOVERY_REQUIRED'):raise ValueError('Não há brassagem ativa para interromper')
     mark_event('INTERRUPTED_BY_OPERATOR');heat(False);pump(False);history('INTERRUPTED');s['status']='INTERRUPTED';s['phase']='INTERRUPTED';s['pending_events']=[];s['message']='Brassagem interrompida pelo operador'
    elif p=='/api/heater/enable':
     enable=bool(body.get('on'))
     if enable and (not s['sensor_ok'] or not cfg.get('enable_heater_gpio_test') or s['status'] not in ('RUNNING','PAUSED','AWAIT_NEXT')):raise ValueError('Aquecimento indisponível: verifique sensor, habilitação e estado do processo')
     s['heater_manual_enabled']=enable
     if not enable:heat(False)
     mark_event('HEATER_MANUAL_ENABLE' if enable else 'HEATER_MANUAL_DISABLE')
    elif p=='/api/pump':
     if body.get('on') and not pump_phase_allowed():raise ValueError('Bomba permitida somente durante Mash-in e Mash-out com brassagem em execução')
     if body.get('on') and (not s['sensor_ok'] or not cfg.get('enable_pump_test')):raise ValueError('Bomba não habilitada ou sensor inválido')
     s['pump_manual']=bool(body['on']);pump(s['pump_manual'])
    else:self.reply({'error':'Não encontrado'},404);return
    update(0);save_checkpoint();self.reply({'ok':True})
  except (ValueError,KeyError,TypeError,IndexError) as exc:self.reply({'error':str(exc)},400)
 def log_message(self,fmt,*args):print(fmt%args)

if __name__=='__main__':
 print('BeerGoPi 0.11Beta CONTROLE DINÂMICO | SSR GPIO%d | bomba GPIO%d'%(cfg['heater_gpio'],cfg['pump_gpio']))
 threading.Thread(target=sensor_loop,daemon=True).start()
 try:ThreadingHTTPServer((cfg['host'],int(cfg['port'])),Handler).serve_forever()
 finally:
  heat(False);pump(False);save_checkpoint()
  if GPIO is not None:GPIO.cleanup()
