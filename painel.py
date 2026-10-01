#!/usr/bin/env python3
"""Painel web da conexão: lê conexao.db (somente leitura) e serve gráficos em http://127.0.0.1:8080"""
import json
import os
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conexao.db")
PORT = int(os.environ.get("PORT", 8080))
MAX_PONTOS = 600
INTERVALO = 5           # mesmo INTERVAL do monitor.py
PARADO_APOS = 60        # s sem amostra nova = monitor parado
CAIU = ("sem_wifi", "falha_lan", "falha_internet", "falha_dns")
CAMPOS = ("gw", "cf", "gg", "gwl", "cfl", "ggl", "dns", "dbm")


def conectar():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args)]


COLUNAS = (("gw_avg_ms", "gw"), ("cf_avg_ms", "cf"), ("gg_avg_ms", "gg"), ("gw_loss_pct", "gwl"),
           ("cf_loss_pct", "cfl"), ("gg_loss_pct", "ggl"), ("dns_ms", "dns"), ("wifi_dbm", "dbm"))
assert tuple(a for _, a in COLUNAS) == CAMPOS


def pontos_do_periodo(c, desde, agora):
    """Pontos do gráfico e o passo (s). Até MAX_PONTOS amostras voltam como estão; acima disso o SQLite
    agrupa em MAX_PONTOS baldes de tempo fixo (média; status = pior do balde). Baldes vazios somem,
    então períodos sem medição continuam aparecendo como buraco."""
    n = c.execute("SELECT COUNT(*) FROM checks WHERE epoch >= ?", (desde,)).fetchone()[0]
    if n <= MAX_PONTOS:
        brutos = ", ".join(f"{col} {nome}" for col, nome in COLUNAS)
        return rows(c, f"SELECT epoch, status, {brutos} FROM checks WHERE epoch >= ? ORDER BY epoch", (desde,)), INTERVALO
    tam = (agora - desde) / MAX_PONTOS
    medias = ", ".join(f"AVG({col}) {nome}" for col, nome in COLUNAS)
    # Regra do SQLite: numa consulta com um único MAX(), as colunas soltas (status) vêm da linha
    # que deu o máximo, ou seja, o status do pior grau do balde.
    campos = ", ".join(("epoch", "status") + CAMPOS)
    return rows(c, f"""SELECT {campos} FROM (
                           SELECT AVG(epoch) epoch, status, {medias},
                                  MAX(CASE status WHEN 'ok' THEN 0 WHEN 'degradado' THEN 1 ELSE 2 END) grau
                           FROM checks WHERE epoch >= ?
                           GROUP BY CAST((epoch - ?) / ? AS INTEGER)) ORDER BY epoch""",
                (desde, desde, tam)), tam


def api(minutos):
    agora = time.time()
    desde = agora - minutos * 60
    marcas = ",".join("?" * len(CAIU))
    c = conectar()
    try:
        pontos, passo = pontos_do_periodo(c, desde, agora)
        resumo = rows(c, "SELECT status, COUNT(*) n FROM checks WHERE epoch >= ? GROUP BY status", (desde,))

        atual = rows(c, "SELECT epoch, status FROM checks ORDER BY epoch DESC LIMIT 1")
        atual = atual[0] if atual else None
        parado = not atual or agora - atual["epoch"] > PARADO_APOS
        recentes = [r["status"] for r in rows(c, "SELECT status FROM checks ORDER BY epoch DESC LIMIT 12")]

        # fim de queda sem end_epoch (monitor morto no meio dela) = primeira amostra com outro status
        quedas = rows(c, """SELECT status, start_epoch ini,
                                   COALESCE(end_epoch, (SELECT MIN(k.epoch) FROM checks k
                                                        WHERE k.epoch > o.start_epoch AND k.status != o.status)) fim
                            FROM outages o WHERE end_epoch IS NULL OR end_epoch >= ?
                            ORDER BY start_epoch DESC""", (desde,))
        for q in quedas:
            if q["fim"] is None and parado:
                q["fim"] = atual["epoch"] if atual else q["ini"]
        quedas = [q for q in quedas if q["fim"] is None or q["fim"] >= desde]
        falhas = {"n": len(quedas),
                  "seg": sum((q["fim"] or agora) - max(q["ini"], desde) for q in quedas)}

        ultima = rows(c, f"SELECT epoch FROM checks WHERE status IN ({marcas}) ORDER BY epoch DESC LIMIT 1", CAIU)
        inicio_atual = None
        if atual and atual["status"] in CAIU:
            ant = rows(c, "SELECT epoch FROM checks WHERE status != ? ORDER BY epoch DESC LIMIT 1", (atual["status"],))
            inicio_atual = rows(c, "SELECT MIN(epoch) e FROM checks WHERE epoch > ?",
                                (ant[0]["epoch"] if ant else 0,))[0]["e"]
        wifi = rows(c, "SELECT ssid, freq FROM wifi_info ORDER BY id DESC LIMIT 1")
    finally:
        c.close()
    return {"pontos": pontos, "passo": passo, "resumo": resumo, "quedas": quedas[:30], "falhas": falhas,
            "atual": atual, "recentes": recentes, "ultima_queda": ultima[0]["epoch"] if ultima else None,
            "inicio_atual": inicio_atual, "wifi": wifi[0] if wifi else None, "agora": agora}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            body, tipo = PAGINA.encode(), "text/html; charset=utf-8"
        elif u.path == "/api":
            try:
                m = int(parse_qs(u.query).get("min", ["60"])[0])
                body, tipo = json.dumps(api(max(1, min(m, 60 * 24 * 30)))).encode(), "application/json"
            except Exception as e:
                self.send_error(500, str(e))
                return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


PAGINA = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Minha internet</title>
<style>
:root{color-scheme:light;
--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
--s1:#2a78d6;--s2:#eb6834;
--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--nodata:#d6d5cf;
--good-bg:rgba(12,163,12,.08);--warning-bg:rgba(250,178,25,.13);--critical-bg:rgba(208,59,59,.09);--nodata-bg:rgba(137,135,129,.10)}
@media(prefers-color-scheme:dark){:root{color-scheme:dark;
--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--nodata:#3a3a37;
--good-bg:rgba(12,163,12,.15);--warning-bg:rgba(250,178,25,.13);--critical-bg:rgba(208,59,59,.18);--nodata-bg:rgba(137,135,129,.12)}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1000px;margin:0 auto;padding:20px 16px 40px;transition:opacity .2s}
main.carregando{opacity:.6}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin-bottom:16px}
h1{font-size:20px;margin:0}
.upd{color:var(--muted);font-size:13px}
.seg{display:inline-flex;flex-wrap:wrap;gap:2px;background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:3px}
.seg button{font:inherit;font-size:14px;border:0;background:none;color:var(--ink2);padding:6px 12px;border-radius:7px;cursor:pointer}
.seg button:hover{background:var(--nodata-bg)}
.seg button[aria-pressed=true]{background:var(--ink);color:var(--surface);font-weight:600}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:18px;margin-bottom:14px;position:relative}
.hero{display:flex;gap:16px;align-items:flex-start}
.hero .ic{flex:none;width:52px;height:52px}
.hero h2{font-size:24px;line-height:1.2;margin:2px 0 6px}
.hero p{margin:0;color:var(--ink2);max-width:64ch}
.hero .desde{margin-top:10px;font-size:13px;color:var(--ink2)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:14px}
.tile{margin:0}
.tile .lbl{font-size:13px;color:var(--ink2);font-weight:600}
.tile .val{display:flex;align-items:center;gap:8px;font-size:26px;font-weight:700;margin:6px 0 2px}
.tile .val svg{width:22px;height:22px;flex:none}
.tile .sub{font-size:13px;color:var(--muted)}
h3{font-size:16px;margin:0 0 2px}
.cap{font-size:13px;color:var(--muted);margin:0 0 12px;max-width:72ch}
.leg{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--ink2);margin-top:10px}
.leg span{display:inline-flex;align-items:center;gap:6px}
.leg i{display:inline-block;width:12px;height:12px;border-radius:3px}
.leg i.ln{width:16px;height:2px;border-radius:1px}
canvas{display:block;width:100%;touch-action:pan-y}
#tl{height:62px}.chart{height:220px}
.tip{position:absolute;display:none;z-index:2;pointer-events:none;background:var(--surface);border:1px solid var(--ring);border-radius:8px;
box-shadow:0 4px 14px rgba(0,0,0,.14);padding:8px 10px;font-size:13px;white-space:nowrap}
.tip .t{color:var(--muted);margin-bottom:3px}
.tip .r{display:flex;align-items:center;gap:6px;color:var(--ink2)}
.tip .r b{color:var(--ink);font-size:14px}
.tip .r i{display:inline-block;width:12px;height:2px}
.tip .r i.q{height:12px;width:12px;border-radius:3px}
.list{list-style:none;margin:0;padding:0}
.list li{display:flex;gap:12px;align-items:center;padding:10px 0;border-top:1px solid var(--grid)}
.list li:first-child{border-top:0}
.list svg{width:22px;height:22px;flex:none}
.list .o{flex:1;min-width:0}.list .o b{display:block;font-weight:600}.list .o span{color:var(--muted);font-size:13px}
.list .d{color:var(--ink2);font-size:14px;text-align:right}
details summary{cursor:pointer;font-weight:600}
details p{color:var(--ink2);font-size:13px;max-width:80ch}
.tab{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px;font-variant-numeric:tabular-nums}
td,th{text-align:left;padding:5px 8px;border-bottom:1px solid var(--grid)}
th{color:var(--ink2);font-weight:600}td.n,th.n{text-align:right}
code{font-size:13px;background:var(--nodata-bg);padding:1px 5px;border-radius:4px}
</style></head><body><main id="m">
<header>
  <div><h1>Minha internet</h1><div class="upd" id="upd">carregando…</div></div>
  <div class="seg" id="per" role="group" aria-label="Período">
    <button data-min="60">Última hora</button><button data-min="360">6 horas</button><button data-min="1440">24 horas</button><button data-min="10080">7 dias</button>
  </div>
</header>
<section class="card hero" id="hero"></section>
<div class="tiles" id="tiles"></div>
<section class="card"><h3>Como foi o período</h3>
  <p class="cap">Cada cor mostra como a internet estava naquele momento. Passe o mouse para ver o horário.</p>
  <canvas id="tl"></canvas>
  <div class="leg"><span><i style="background:var(--good)"></i>Funcionando</span><span><i style="background:var(--warning)"></i>Instável ou lenta</span><span><i style="background:var(--critical)"></i>Sem conexão</span><span><i style="background:var(--nodata)"></i>Sem medição (monitor desligado)</span></div>
  <div class="tip"></div></section>
<section class="card"><h3>Rapidez</h3>
  <p class="cap">Tempo que um sinal leva para ir e voltar, em milissegundos (ms). Quanto <b>menor</b>, melhor: abaixo de 50 ms é ótimo, acima de 150 ms a internet parece lenta.</p>
  <canvas id="c1" class="chart"></canvas>
  <div class="leg"><span><i class="ln" style="background:var(--s1)"></i>Até a internet</span><span><i class="ln" style="background:var(--s2)"></i>Até o roteador (dentro de casa)</span><span><i style="background:var(--critical-bg);box-shadow:inset 0 0 0 1px var(--critical)"></i>Sem conexão</span></div>
  <div class="tip"></div></section>
<section class="card"><h3>Força do sinal Wi-Fi</h3>
  <p class="cap">Quanto <b>maior</b>, melhor. Abaixo de 35% a conexão pode ficar lenta ou cair: tente ficar mais perto do roteador.</p>
  <canvas id="c2" class="chart"></canvas>
  <div class="tip"></div></section>
<section class="card"><h3>Quando a conexão falhou</h3><p class="cap" id="qcap"></p><ul class="list" id="q"></ul></section>
<section class="card"><details><summary>Detalhes técnicos</summary><div id="tec"></div></details></section>
</main>
<script>
const $=id=>document.getElementById(id);
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(x,d=0)=>x==null?'–':x.toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d});
const avg=a=>{a=a.filter(x=>x!=null);return a.length?a.reduce((s,x)=>s+x,0)/a.length:null};
const caiu=s=>s!=='ok'&&s!=='degradado';
const cat=s=>s==='ok'?'good':s==='degradado'?'warning':'critical';

const ST={
  ok:{nome:'Funcionando',titulo:'Sua internet está funcionando bem',
      texto:'Tudo certo: o Wi-Fi, o roteador e a internet estão respondendo normalmente.'},
  degradado:{nome:'Instável ou lenta',titulo:'Sua internet está instável',
      texto:'Ela funciona, mas com lentidão ou pequenas falhas. Vídeos e chamadas podem travar.'},
  falha_internet:{nome:'Sem internet',dica:'provável problema na operadora',titulo:'Sem internet',
      texto:'O Wi-Fi e o roteador estão funcionando, mas a internet não chega até eles. Normalmente é um problema da operadora. Se durar mais de alguns minutos, reinicie o modem; se continuar, ligue para o provedor.'},
  falha_lan:{nome:'Roteador não respondeu',dica:'problema no Wi-Fi ou no roteador',titulo:'O roteador não está respondendo',
      texto:'O computador está no Wi-Fi, mas não consegue falar com o roteador. Tente chegar mais perto dele ou reiniciá-lo.'},
  sem_wifi:{nome:'Wi-Fi desconectado',dica:'o computador saiu da rede',titulo:'Wi-Fi desconectado',
      texto:'O computador não está conectado a nenhuma rede. Verifique se o Wi-Fi está ligado.'},
  falha_dns:{nome:'Sites não abriam',dica:'falha no DNS',titulo:'Os sites não estão abrindo',
      texto:'A conexão existe, mas o serviço que traduz o nome dos sites (DNS) não respondeu. Costuma passar sozinho; se continuar, reinicie o roteador.'}};
const stNome=s=>(ST[s]||{nome:s}).nome;

const ICON={good:'<path d="M7 12.5l3.2 3.2L17 9"/>',warning:'<path d="M12 7v6M12 16.6v.1"/>',
  critical:'<path d="M8.5 8.5l7 7M15.5 8.5l-7 7"/>',muted:'<path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.5v.3M12 16.6v.1"/>'};
const icon=k=>`<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="var(--${k})"/><g fill="none" stroke="${k==='warning'?'#3a2a00':'#fff'}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${ICON[k]}</g></svg>`;

const hm=e=>new Date(e*1000).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
function quando(e){const d=new Date(e*1000),h=new Date();h.setHours(0,0,0,0);
  const dia=Math.round((h-new Date(d).setHours(0,0,0,0))/864e5);
  return (dia===0?'hoje':dia===1?'ontem':d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'}))+' às '+hm(e)}
function dur(s){s=Math.max(0,Math.round(s));if(s<60)return s+(s===1?' segundo':' segundos');
  const m=Math.round(s/60);if(m<60)return m+' min';const h=Math.floor(m/60),r=m%60;
  return h<48?h+' h'+(r?' '+r+' min':''):Math.round(h/24)+' dias'}

const rapidez=ms=>ms==null?null:ms<50?['Ótima','good']:ms<100?['Boa','good']:ms<150?['Razoável','warning']:['Lenta','critical'];
const estab=p=>p==null?null:p<0.5?['Estável','good']:p<2?['Algumas falhas','warning']:['Instável','critical'];
const pctSinal=dbm=>dbm==null?null:Math.max(0,Math.min(100,2*(dbm+100)));
const sinal=p=>p==null?null:p>=70?['Excelente','good']:p>=50?['Bom','good']:p>=35?['Razoável','warning']:['Fraco','critical'];
const banda=f=>{const m=parseInt(f);return m>=5900?'6 GHz':m>=4900?'5 GHz':'2,4 GHz'};

let D=null,MIN=60;
try{MIN=+localStorage.getItem('periodo')||60}catch(e){}
const janela=()=>[D.agora-MIN*60,D.agora];
const limite=()=>Math.max(20,D.passo*2.5);   // distância maior que isso entre pontos = monitor desligado

function prep(cv){const dpr=devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;
  if(cv.width!==Math.round(W*dpr)||cv.height!==Math.round(H*dpr)){cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr)}
  const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,W,H);g.font='12px system-ui,sans-serif';return{g,W,H}}
function eixoX(g,x0,x1,L,pw,y){const longo=x1-x0>36*3600,n=pw<480?2:4;g.fillStyle=css('--muted');
  for(let i=0;i<=n;i++){const e=x0+(x1-x0)*i/n,d=new Date(e*1000);
    g.textAlign=i===0?'left':i===n?'right':'center';
    g.fillText((longo?d.toLocaleDateString('pt-BR',{weekday:'short'}).replace('.','')+' ':'')+hm(e),L+pw*i/n,y)}}
function perto(P,e){let m=null,dm=Infinity;for(const p of P){const d=Math.abs(p.epoch-e);if(d<dm){dm=d;m=p}}return dm<=limite()?m:null}
function nice(v){const s=v/4,p=10**Math.floor(Math.log10(s)),m=s/p;return(m<=1?1:m<=2?2:m<=2.5?2.5:m<=5?5:10)*p*4}

function hero(){
  const a=D.atual;let k,t,x,desde='';
  if(!a||D.agora-a.epoch>60){k='muted';t='O monitor não está medindo';
    x='Nenhuma medição recente'+(a?' (a última foi '+quando(a.epoch)+')':'')+'. Para voltar a monitorar, rode make start no terminal.'}
  else{let s=a.status;
    if(!caiu(s))s=D.recentes.filter(r=>r==='degradado').length>=3?'degradado':'ok';  // 1 amostra ruim isolada não muda o resumo
    const i=ST[s]||{titulo:s,texto:''};k=cat(s);t=i.titulo;x=i.texto;
    if(caiu(s)&&D.inicio_atual)desde='Começou '+quando(D.inicio_atual)+' · já dura '+dur(D.agora-D.inicio_atual);
    else if(D.ultima_queda)desde='Última falha: '+quando(D.ultima_queda)+' (há '+dur(D.agora-D.ultima_queda)+')';
    else desde='Nenhuma falha registrada até agora.'}
  const bg=k==='muted'?'nodata':k;
  $('hero').style.background=`linear-gradient(var(--${bg}-bg),var(--${bg}-bg)),var(--surface)`;
  $('hero').innerHTML=`<div class="ic">${icon(k)}</div><div><h2>${esc(t)}</h2><p>${esc(x)}</p>${desde?`<div class="desde">${esc(desde)}</div>`:''}</div>`}

function tiles(){
  const P=D.pontos,tot=D.resumo.reduce((s,r)=>s+r.n,0),bad=D.resumo.filter(r=>caiu(r.status)).reduce((s,r)=>s+r.n,0);
  const up=tot?100*(tot-bad)/tot:null,f=D.falhas,w=D.wifi;
  const inet=avg(P.map(p=>p.inet)),perda=avg(P.map(p=>p.perda)),sn=avg(P.map(p=>p.sinal));
  const T=[
    ['Conexão funcionando',up==null?null:[num(up,up===100?0:1)+'%',up>=99?'good':up>=95?'warning':'critical'],
      up==null?'sem medições no período':'do tempo · '+(f.n?`fora do ar ${f.n} ${f.n===1?'vez':'vezes'}, ${dur(f.seg)} no total`:'nenhuma queda')],
    ['Rapidez',rapidez(inet),inet==null?'':`resposta média de ${num(inet)} ms`],
    ['Estabilidade',estab(perda),perda==null?'':`${num(perda,1)}% dos dados se perderam no caminho`],
    ['Sinal do Wi-Fi',sinal(sn),sn==null?'':`${num(sn)}%`+(w&&w.ssid?` · rede “${w.ssid}”`+(w.freq?' · '+banda(w.freq):''):'')]];
  $('tiles').innerHTML=T.map(([l,v,s])=>`<div class="card tile"><div class="lbl">${l}</div><div class="val">${v?icon(v[1])+esc(v[0]):'–'}</div><div class="sub">${esc(s)}</div></div>`).join('')}

function timeline(){
  const cv=$('tl'),P=D.pontos,{g,W,H}=prep(cv),T=2,ph=H-T-22,[x0,x1]=janela(),lim=limite(),xs=e=>(e-x0)/(x1-x0)*W;
  g.save();g.beginPath();g.roundRect(0,T,W,ph,6);g.clip();
  g.fillStyle=css('--nodata');g.fillRect(0,T,W,ph);
  P.forEach((p,i)=>{const n=P[i+1],fim=n&&n.epoch-p.epoch<=lim?n.epoch:p.epoch+Math.min(D.passo,lim);
    const a=xs(p.epoch),b=xs(fim);g.fillStyle=css('--'+cat(p.status));g.fillRect(a,T,Math.max(b-a,p.status==='ok'?.5:2),ph)});
  g.restore();
  eixoX(g,x0,x1,0,W,H-4);
  cv._base=timeline;
  cv._h=x=>{const e=x0+x/W*(x1-x0),p=perto(P,e);
    const st=p?`<div class="r"><i class="q" style="background:var(--${cat(p.status)})"></i><b>${esc(stNome(p.status))}</b></div>`
              :`<div class="r"><i class="q" style="background:var(--nodata)"></i><b>Sem medição</b></div>`;
    return{x,html:`<div class="t">${esc(quando(p?p.epoch:e))}</div>${st}`}};
  cv._mark=h=>{g.strokeStyle=css('--ink');g.lineWidth=1.5;g.beginPath();g.moveTo(Math.round(h.x)+.5,0);g.lineTo(Math.round(h.x)+.5,T+ph+2);g.stroke()}}

function lineChart(cv,series,{un='',max=null,faixas=false}={}){
  const P=D.pontos,{g,W,H}=prep(cv),L=52,R=10,T=8,B=24,pw=W-L-R,ph=H-T-B,[x0,x1]=janela(),lim=limite();
  const xs=e=>L+(e-x0)/(x1-x0)*pw;
  const vals=series.flatMap(s=>P.map(p=>p[s.k])).filter(v=>v!=null).sort((a,b)=>a-b);
  // escala pelo percentil 98: um pico isolado não achata o resto do gráfico (ele sai pelo topo)
  const hi=max??nice(Math.max(1,(vals[Math.floor(.98*(vals.length-1))]||1)*1.15)),ys=v=>T+ph-Math.min(v,hi*1.02)/hi*ph;
  g.lineWidth=1;g.strokeStyle=css('--grid');g.fillStyle=css('--muted');g.textAlign='right';
  for(let i=1;i<=4;i++){const v=hi*i/4,y=Math.round(ys(v))+.5;g.beginPath();g.moveTo(L,y);g.lineTo(W-R,y);g.stroke();g.fillText(num(v)+un,L-8,y+4)}
  g.fillText('0'+un,L-8,T+ph+4);
  if(faixas){g.fillStyle=css('--critical-bg');
    P.forEach((p,i)=>{if(!caiu(p.status))return;const n=P[i+1],fim=n&&n.epoch-p.epoch<=lim?n.epoch:p.epoch+D.passo;
      const a=xs(p.epoch);g.fillRect(a,T,Math.max(xs(fim)-a,2),ph)})}
  g.strokeStyle=css('--axis');g.beginPath();g.moveTo(L,T+ph+.5);g.lineTo(W-R,T+ph+.5);g.stroke();
  g.save();g.beginPath();g.rect(L,0,pw,T+ph);g.clip();
  g.lineWidth=2;g.lineJoin='round';g.lineCap='round';
  for(const s of [...series].reverse()){g.strokeStyle=css(s.c);g.beginPath();let ant=null;
    for(const p of P){const v=p[s.k];if(v==null){ant=null;continue}const x=xs(p.epoch),y=ys(v);
      ant&&p.epoch-ant.epoch<=lim?g.lineTo(x,y):g.moveTo(x,y);ant=p}g.stroke()}
  g.restore();
  eixoX(g,x0,x1,L,pw,H-6);
  cv._base=()=>lineChart(cv,series,{un,max,faixas});
  cv._h=x=>{const p=perto(P,x0+(x-L)/pw*(x1-x0));if(!p)return null;
    let html=`<div class="t">${esc(quando(p.epoch))}</div>`;
    for(const s of series)html+=`<div class="r"><i style="background:var(${s.c})"></i><b>${p[s.k]==null?'–':num(p[s.k])+un}</b>${esc(s.n)}</div>`;
    if(caiu(p.status))html+=`<div class="r"><i class="q" style="background:var(--critical)"></i>${esc(stNome(p.status))}</div>`;
    return{x:xs(p.epoch),p,html}};
  cv._mark=h=>{g.strokeStyle=css('--axis');g.lineWidth=1;g.beginPath();g.moveTo(Math.round(h.x)+.5,T);g.lineTo(Math.round(h.x)+.5,T+ph);g.stroke();
    for(const s of series){const v=h.p[s.k];if(v==null)continue;g.beginPath();g.arc(h.x,ys(v),5,0,7);g.fillStyle=css(s.c);g.fill();
      g.lineWidth=2;g.strokeStyle=css('--surface');g.stroke()}}}

function quedas(){
  const Q=D.quedas,f=D.falhas;
  $('qcap').textContent=f.n?`${f.n} ${f.n===1?'falha':'falhas'} no período, somando ${dur(f.seg)} sem conexão.`+(f.n>Q.length?` Mostrando as ${Q.length} mais recentes.`:''):'';
  $('q').innerHTML=Q.length?Q.map(q=>{const i=ST[q.status]||{nome:q.status},agora=q.fim==null;
      return `<li>${icon('critical')}<div class="o"><b>${esc(i.nome)}</b><span>${esc(quando(q.ini))}${i.dica?' · '+esc(i.dica):''}</span></div>`+
        `<div class="d">${agora?'<b>acontecendo agora</b><br>há '+esc(dur(D.agora-q.ini)):'durou '+esc(dur(q.fim-q.ini))}</div></li>`}).join('')
    :`<li>${icon('good')}<div class="o"><b>Nenhuma falha neste período</b></div></li>`}

function tecnico(){
  const P=D.pontos,a=k=>avg(P.map(p=>p[k])),tot=D.resumo.reduce((s,r)=>s+r.n,0)||1;
  const M=[['Resposta do roteador (gateway)',a('gw'),' ms'],['Resposta da Cloudflare (1.1.1.1)',a('cf'),' ms'],['Resposta do Google (8.8.8.8)',a('gg'),' ms'],
    ['Perda de pacotes até o roteador',a('gwl'),' %',2],['Perda de pacotes até a Cloudflare',a('cfl'),' %',2],['Perda de pacotes até o Google',a('ggl'),' %',2],
    ['Tempo de resposta do DNS',a('dns'),' ms'],['Sinal Wi-Fi',a('dbm'),' dBm']];
  $('tec').innerHTML=`<p>A cada 5 segundos o monitor envia sinais (ping) para o roteador e para dois servidores na internet (Cloudflare e Google), testa o DNS e lê a força do sinal Wi-Fi.
    Se o roteador não responde, o problema está dentro de casa; se o roteador responde mas a internet não, o problema é da operadora.
    “Instável” significa que algum pacote se perdeu ou que a internet demorou mais de 150 ms nos dois servidores (Cloudflare e Google); se só um deles estiver lento, a internet não é considerada instável.</p>
    <div class="tab"><table><tr><th>Medição (média no período)</th><th class="n">Valor</th></tr>${M.map(([l,v,u,d])=>`<tr><td>${l}</td><td class="n">${num(v,d||1)}${u}</td></tr>`).join('')}</table></div>
    <div class="tab"><table><tr><th>Situação</th><th>Código</th><th class="n">Medições</th><th class="n">% do tempo</th></tr>${[...D.resumo].sort((x,y)=>y.n-x.n).map(r=>
      `<tr><td>${esc(stNome(r.status))}</td><td><code>${esc(r.status)}</code></td><td class="n">${num(r.n)}</td><td class="n">${num(100*r.n/tot,2)}%</td></tr>`).join('')}</table></div>`}

function draw(){
  if(!D)return;
  D.pontos.forEach(p=>{const v=[p.cf,p.gg].filter(x=>x!=null);p.inet=v.length?v.reduce((s,x)=>s+x)/v.length:null;
    p.perda=Math.max(p.gwl||0,p.cfl||0,p.ggl||0);p.sinal=pctSinal(p.dbm)});
  document.querySelectorAll('.tip').forEach(t=>t.style.display='none');
  hero();tiles();timeline();
  lineChart($('c1'),[{k:'inet',c:'--s1',n:'até a internet'},{k:'gw',c:'--s2',n:'até o roteador'}],{un:' ms',faixas:true});
  lineChart($('c2'),[{k:'sinal',c:'--s1',n:'sinal'}],{un:'%',max:100});
  quedas();tecnico();
  $('upd').textContent='Atualizado às '+new Date().toLocaleTimeString('pt-BR')+' · atualiza sozinho a cada 5 s'}

function hover(cv){const card=cv.parentElement,tip=card.querySelector('.tip');
  cv.onpointermove=ev=>{if(!cv._h)return;const r=cv.getBoundingClientRect(),h=cv._h(ev.clientX-r.left);cv._base();
    if(!h){tip.style.display='none';return}cv._mark(h);tip.innerHTML=h.html;tip.style.display='block';
    const cr=card.getBoundingClientRect(),ox=r.left-cr.left,tw=tip.offsetWidth;let left=ox+h.x+14;
    if(left+tw>card.clientWidth-8)left=ox+h.x-14-tw;
    tip.style.left=Math.max(8,left)+'px';tip.style.top=(r.top-cr.top+(cv.id==='tl'?cv.clientHeight+4:8))+'px'};
  cv.onpointerleave=()=>{tip.style.display='none';cv._base&&cv._base()}}

function marcaPeriodo(){document.querySelectorAll('#per button').forEach(b=>b.setAttribute('aria-pressed',+b.dataset.min===MIN))}
async function load(){
  try{const r=await fetch('/api?min='+MIN);if(!r.ok)throw 0;D=await r.json();draw()}
  catch(e){$('upd').textContent='Não foi possível carregar os dados. O painel ainda está rodando?'}
  finally{$('m').classList.remove('carregando')}}
document.querySelectorAll('#per button').forEach(b=>b.onclick=()=>{MIN=+b.dataset.min;try{localStorage.setItem('periodo',MIN)}catch(e){}
  marcaPeriodo();$('m').classList.add('carregando');load()});
['tl','c1','c2'].forEach(id=>hover($(id)));
addEventListener('resize',draw);matchMedia('(prefers-color-scheme:dark)').onchange=draw;
if(![60,360,1440,10080].includes(MIN))MIN=60;
marcaPeriodo();load();setInterval(load,5000);
</script></body></html>"""

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"Painel em http://127.0.0.1:{PORT}", file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
