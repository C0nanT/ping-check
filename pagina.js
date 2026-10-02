const $=id=>document.getElementById(id);
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(x,d=0)=>x==null?'–':x.toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d});
const avg=a=>{a=a.filter(x=>x!=null);return a.length?a.reduce((s,x)=>s+x,0)/a.length:null};
const caiu=s=>D.status_queda.includes(s)||!(s in ST);   // lista do servidor; status que a página não conhece também é queda
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

const emTeste=(e,J)=>J.some(([a,b])=>e>=a&&e<=b);   // J = D.janelas_teste: o servidor já aplica TESTE_MAX e a folga

let D=null,MIN=60,FAIXA=null;   // FAIXA = {de,ate} (epoch) escolhida em "Escolher datas" ou arrastando; aí MIN não vale
try{MIN=+localStorage.getItem('periodo')||60}catch(e){}
const janela=()=>[D.de,D.ate];   // o servidor devolve o período já ajustado (fim no futuro vira agora)
const dm=e=>new Date(e*1000).toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'});
const mesmoDia=(a,b)=>new Date(a*1000).toDateString()===new Date(b*1000).toDateString();
const limite=()=>Math.max(20,D.passo*2.5);   // distância maior que isso entre pontos = monitor desligado

function prep(cv){const dpr=devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;
  if(cv.width!==Math.round(W*dpr)||cv.height!==Math.round(H*dpr)){cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr)}
  const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,W,H);g.font='12px system-ui,sans-serif';return{g,W,H}}
// período longo ou que não termina hoje leva a data; acima de 8 dias, só a data
function eixoX(g,x0,x1,L,pw,y){const data=x1-x0>36*3600||!mesmoDia(x1,D.agora),soData=x1-x0>8*86400,n=pw<480?2:4;g.fillStyle=css('--muted');
  for(let i=0;i<=n;i++){const e=x0+(x1-x0)*i/n;
    g.textAlign=i===0?'left':i===n?'right':'center';
    g.fillText(soData?dm(e):(data?dm(e)+' ':'')+hm(e),L+pw*i/n,y)}}
function perto(P,e,lim=limite()){let m=null,dm=Infinity;for(const p of P){const d=Math.abs(p.epoch-e);if(d<dm){dm=d;m=p}}return dm<=lim?m:null}
function nice(v){const s=v/4,p=10**Math.floor(Math.log10(s)),m=s/p;return(m<=1?1:m<=2?2:m<=2.5?2.5:m<=5?5:10)*p*4}

function hero(){
  const a=D.atual;let k,t,x,desde='';
  if(!a||D.agora-a.epoch>D.parado_apos){k='muted';t='O monitor não está medindo';
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
  const up=tot?100*(tot-bad)/tot:null,f=D.falhas,w=D.wifi,vu=D.velocidade_ultimo;
  const inet=avg(P.map(p=>p.inet)),perda=avg(P.map(p=>p.perda)),sn=avg(P.map(p=>p.sinal));
  const T=[
    ['Conexão funcionando',up==null?null:[num(up,up===100?0:1)+'%',upCat(up)],
      up==null?'sem medições no período':'do tempo · '+(f.n?`fora do ar ${f.n} ${f.n===1?'vez':'vezes'}, ${dur(f.seg)} no total`:'nenhuma queda')],
    ['Rapidez',rapidez(inet),inet==null?'':`resposta média de ${num(inet)} ms`],
    ['Estabilidade',estab(perda),perda==null?'':`${num(perda,1)}% dos dados se perderam no caminho`],
    ['Sinal do Wi-Fi',sinal(sn),sn==null?'':`${num(sn)}%`+(w&&w.ssid?` · rede “${w.ssid}”`+(w.freq?' · '+banda(w.freq):''):'')],
    ['Velocidade',vu?[`${num(vu.down)} / ${num(vu.up)} Mbps`,null]:null,
      vu?`Baixar (download) / Enviar (upload) · medido há ${dur(D.agora-(vu.fim||vu.epoch))}`:'nenhum teste de velocidade ainda']];
  $('tiles').innerHTML=T.map(([l,v,s])=>`<div class="card tile"><div class="lbl">${l}</div><div class="val">${v?(v[1]?icon(v[1]):'')+esc(v[0]):'–'}</div><div class="sub">${esc(s)}</div></div>`).join('')}

function timeline(){
  const cv=$('tl'),P=D.pontos,{g,W,H}=prep(cv),T=2,ph=H-T-22,[x0,x1]=janela(),lim=limite(),xs=e=>(e-x0)/(x1-x0)*W;
  g.save();g.beginPath();g.roundRect(0,T,W,ph,6);g.clip();
  g.fillStyle=css('--nodata');g.fillRect(0,T,W,ph);
  P.forEach((p,i)=>{const n=P[i+1],fim=n&&n.epoch-p.epoch<=lim?n.epoch:p.epoch+Math.min(D.passo,lim);
    const a=xs(p.epoch),b=xs(fim);g.fillStyle=css('--'+cat(p.status));g.fillRect(a,T,Math.max(b-a,p.status==='ok'?.5:2),ph)});
  g.restore();
  eixoX(g,x0,x1,0,W,H-4);
  cv._base=timeline;
  cv._x2e=x=>Math.max(x0,Math.min(x1,x0+x/W*(x1-x0)));cv._faixaY=[T,T+ph];   // escala e altura para o arrasto()
  cv._h=x=>{const e=cv._x2e(x),p=perto(P,e);
    const st=p?`<div class="r"><i class="q" style="background:var(--${cat(p.status)})"></i><b>${esc(stNome(p.status))}</b></div>`
              :`<div class="r"><i class="q" style="background:var(--nodata)"></i><b>Sem medição</b></div>`;
    return{x,html:`<div class="t">${esc(quando(p?p.epoch:e))}</div>${st}`}};
  cv._mark=h=>{g.strokeStyle=css('--ink');g.lineWidth=1.5;g.beginPath();g.moveTo(Math.round(h.x)+.5,0);g.lineTo(Math.round(h.x)+.5,T+ph+2);g.stroke()}}

// o: un, max, faixas (quedas em vermelho), P (pontos; padrão D.pontos), lim (maior distância ligada por linha),
//    marcas (bolinha em cada ponto, para séries esparsas), janelas ([[ini,fim]] desenhadas como faixa --band),
//    esq (margem esquerda para os rótulos do eixo Y)
function lineChart(cv,series,o={}){
  const {un='',max=null,faixas=false,P=D.pontos,lim=limite(),marcas=false,janelas=[],esq=52}=o;
  const {g,W,H}=prep(cv),L=esq,R=10,T=8,B=24,pw=W-L-R,ph=H-T-B,[x0,x1]=janela();
  const xs=e=>L+(e-x0)/(x1-x0)*pw;
  const vals=series.flatMap(s=>P.map(p=>p[s.k])).filter(v=>v!=null).sort((a,b)=>a-b);
  // escala pelo percentil 98: um pico isolado não achata o resto do gráfico (ele sai pelo topo)
  const hi=max??nice(Math.max(1,(vals[Math.floor(.98*(vals.length-1))]||1)*1.15)),ys=v=>T+ph-Math.min(v,hi*1.02)/hi*ph;
  g.lineWidth=1;g.strokeStyle=css('--grid');g.fillStyle=css('--muted');g.textAlign='right';
  for(let i=1;i<=4;i++){const v=hi*i/4,y=Math.round(ys(v))+.5;g.beginPath();g.moveTo(L,y);g.lineTo(W-R,y);g.stroke();g.fillText(num(v)+un,L-8,y+4)}
  g.fillText('0'+un,L-8,T+ph+4);
  if(janelas.length){g.fillStyle=css('--band');
    for(const [a,b] of janelas){const xa=Math.max(L,xs(a)),xb=Math.min(W-R,xs(b));if(xb+2>xa)g.fillRect(xa,T,Math.max(xb-xa,2),ph)}}
  if(faixas){g.fillStyle=css('--critical-bg');
    P.forEach((p,i)=>{if(!caiu(p.status))return;const n=P[i+1],fim=n&&n.epoch-p.epoch<=lim?n.epoch:p.epoch+D.passo;
      const a=xs(p.epoch);g.fillRect(a,T,Math.max(xs(fim)-a,2),ph)})}
  g.strokeStyle=css('--axis');g.beginPath();g.moveTo(L,T+ph+.5);g.lineTo(W-R,T+ph+.5);g.stroke();
  g.save();g.beginPath();g.rect(L,0,pw,T+ph);g.clip();
  g.lineWidth=2;g.lineJoin='round';g.lineCap='round';
  for(const s of [...series].reverse()){g.strokeStyle=css(s.c);g.beginPath();let ant=null;
    for(const p of P){const v=p[s.k];if(v==null){ant=null;continue}const x=xs(p.epoch),y=ys(v);
      ant&&p.epoch-ant.epoch<=lim?g.lineTo(x,y):g.moveTo(x,y);ant=p}g.stroke();
    if(marcas){g.fillStyle=css(s.c);for(const p of P){const v=p[s.k];if(v==null)continue;g.beginPath();g.arc(xs(p.epoch),ys(v),3,0,7);g.fill()}}}
  g.restore();
  eixoX(g,x0,x1,L,pw,H-6);
  cv._base=()=>lineChart(cv,series,o);
  cv._h=x=>{const p=perto(P,x0+(x-L)/pw*(x1-x0),lim);if(!p)return null;
    let html=`<div class="t">${esc(quando(p.epoch))}</div>`;
    for(const s of series)html+=`<div class="r"><i style="background:var(${s.c})"></i><b>${p[s.k]==null?'–':num(p[s.k])+un}</b>${esc(s.n)}</div>`;
    if(caiu(p.status))html+=`<div class="r"><i class="q" style="background:var(--critical)"></i>${esc(stNome(p.status))}</div>`;
    if(emTeste(p.epoch,janelas))html+=`<div class="r"><i class="q" style="background:var(--band);box-shadow:inset 0 0 0 1px var(--axis)"></i>teste de velocidade rodando</div>`;
    return{x:xs(p.epoch),p,html}};
  cv._mark=h=>{g.strokeStyle=css('--axis');g.lineWidth=1;g.beginPath();g.moveTo(Math.round(h.x)+.5,T);g.lineTo(Math.round(h.x)+.5,T+ph);g.stroke();
    for(const s of series){const v=h.p[s.k];if(v==null)continue;g.beginPath();g.arc(h.x,ys(v),5,0,7);g.fillStyle=css(s.c);g.fill();
      g.lineWidth=2;g.strokeStyle=css('--surface');g.stroke()}}}

function fraseCarga(n){
  const quem=n.fase==='up'?'Quando alguém envia algo (fotos, vídeos, backup)':'Quando alguém baixa algo';
  if(n.acrescimo<1)return quem+', a resposta não fica mais lenta: ótimo para chamadas de vídeo e jogos.';
  const fim={Ótimo:'nem dá para perceber.',Bom:'quase não se nota.',Razoável:'chamadas de vídeo podem travar.',
    Ruim:'chamadas de vídeo e jogos ficam bem ruins.'}[n.nome];
  return `${quem}, a resposta fica ${num(n.acrescimo)} ms mais lenta: ${fim}`}

let PLANO={down:null,up:null};
try{PLANO=Object.assign(PLANO,JSON.parse(localStorage.getItem('plano')||'{}'))}catch(e){}
const lerMbps=v=>{const n=parseFloat(String(v).replace(',','.'));return n>0?n:null};
// faixas da Anatel: média >= 80% do contratado é o esperado; instantânea abaixo de 40% é descumprimento
const planoCat=r=>r>=.8?'good':r>=.4?'warning':'critical';
function plano(){
  // só o teste completo serve para conferir o plano: o rápido (25 MB) mede a arrancada e costuma dar bem menos
  const el=$('plres'),C=(D.velocidade||[]).filter(t=>t.completo&&(t.down!=null||t.up!=null)),vc=D.velocidade_completo;
  const lin=(nome,k,cont,aprox)=>{if(!cont)return '';
    const v=C.map(t=>t[k]).filter(x=>x!=null),ult=vc&&vc[k]!=null?vc[k]:null;
    if(!v.length&&ult==null)return '';
    const med=v.length?v.reduce((a,b)=>a+b)/v.length:null,ref=med!=null?med:ult,r=ref/cont,cat=planoCat(r);
    const txt=r>=.8?'dentro do esperado':r>=.4?'abaixo do esperado':'muito abaixo do contratado';
    return `<div class="carga">${icon(cat)}<div><b>${nome}: ${num(100*r)}% do plano (${txt})${aprox?' · aproximado':''}</b>`+
      `<div class="sub">Contratado ${num(cont,cont%1?1:0)} Mbps · `+(med!=null?(v.length===1?`teste completo ${num(med)} Mbps`:
        `média de ${v.length} testes completos no período ${num(med)} Mbps (melhor ${num(Math.max(...v))}, pior ${num(Math.min(...v))})`)
        :`último teste completo ${num(ult)} Mbps, ${esc(quando(vc.fim||vc.epoch))}`)+`</div></div></div>`};
  const h=lin('Baixar (download)','down',PLANO.down,false)+lin('Enviar (upload)','up',PLANO.up,true);
  el.innerHTML=h||((PLANO.down||PLANO.up)?'<p class="vazio">Ainda não há teste completo para comparar com o plano. Ele roda 3 vezes por dia (normalmente às 9h, 15h e 21h).</p>':'');
  if(h)el.insertAdjacentHTML('beforeend','<p class="vazio">Usa só o teste completo (3 vezes por dia, download maior): o teste rápido do gráfico costuma marcar menos que a velocidade real. O envio (upload) ainda é medido com pouco volume, então é aproximado. O esperado é receber pelo menos 80% do contratado, em média (regra da Anatel).</p>')}
let PEDINDO=false;
function botaoTeste(){
  const b=$('btest'),s=$('tstat'),r=D.velocidade_rodando,fora=D.atual&&caiu(D.atual.status);
  const apos=D.teste_manual_apos,T=D.velocidade||[],ult=T[T.length-1],lim=ult&&ult.erro&&ult.erro.includes('429');
  b.disabled=PEDINDO||!!r||D.teste_pedido||!!apos;
  s.textContent=r?`Teste ${r.completo?'completo':'rápido'} rodando (começou há ${dur(D.agora-r.epoch)}). O resultado aparece aqui quando terminar.`
    :D.teste_pedido?(fora?'Pedido feito. O teste espera a internet voltar.':'Pedido feito. O teste começa em alguns segundos.')
    :(lim?'O último teste falhou porque o servidor de teste limitou o uso (muitos testes seguidos). Ele libera em até 1 hora. ':'')+
    (apos?`Para não ser bloqueado pelo servidor de teste, o próximo teste completo pode ser pedido a partir das ${hm(apos)}.`
      :'Leva cerca de 30 segundos e baixa por volta de 1 GB. Dá para pedir 1 por hora.')}
$('btest').onclick=async()=>{PEDINDO=true;$('btest').disabled=true;
  try{const r=await fetch('/teste-completo',{method:'POST',headers:{'X-Pedido':'1'}});if(!r.ok)throw 0;await load()}
  catch(e){$('tstat').textContent='Não foi possível pedir o teste. Tente de novo.'}
  finally{PEDINDO=false;if(D)botaoTeste()}};
$('pdown').value=PLANO.down||'';$('pup').value=PLANO.up||'';
[['pdown','down'],['pup','up']].forEach(([id,k])=>$(id).oninput=e=>{PLANO[k]=lerMbps(e.target.value);
  try{localStorage.setItem('plano',JSON.stringify(PLANO))}catch(x){}if(D)plano()});
function velocidade(){
  const V=(D.velocidade||[]).filter(t=>t.down!=null||t.up!=null).map(t=>({epoch:t.fim||t.epoch,down:t.down,up:t.up,status:'ok'}));
  const dif=V.slice(1).map((p,i)=>p.epoch-V[i].epoch).sort((a,b)=>a-b),med=dif.length?dif[dif.length>>1]:0;
  const vazio=$('vvazio'),vu=D.velocidade_ultimo;
  vazio.hidden=!!V.length;
  vazio.textContent=vu?'Nenhum teste de velocidade neste período. O último foi '+quando(vu.fim||vu.epoch)+'.'
    :'Ainda não há nenhum teste de velocidade. O primeiro roda cerca de 1 minuto depois de o monitor iniciar.';
  // liga só testes consecutivos: lacuna maior que ~2 intervalos fica sem linha
  lineChart($('c3'),[{k:'down',c:'--s1',n:'baixar (download)'},{k:'up',c:'--s2',n:'enviar (upload)'}],
    {un:' Mbps',P:V,lim:med?2.5*med:3600,marcas:true,esq:76});
  const c=vu&&vu.carga,n=c&&c.nota,el=$('carga');
  el.hidden=!n;
  if(n)el.innerHTML=`${icon(n.cat)}<div><b>Quando a internet está em uso: ${esc(n.nome)}</b><p>${esc(fraseCarga(n))}</p>`+
    `<div class="sub">Resposta parada ${num(c.ocioso)} ms · baixando ${num(c.down)} ms · enviando ${num(c.up)} ms · teste ${esc(quando(vu.fim||vu.epoch))}</div></div>`}

const CAMINHO_ABERTO=new Set();   // "ver caminho" abertos sobrevivem à atualização a cada 5 s
function caminho(q){const r=q.rota;if(!r)return '';
  let h=r.frase?`<span class="rota">${esc(r.frase)}</span>`:'';
  if(r.saltos&&r.saltos.length)h+=`<details data-id="${q.id}"${CAMINHO_ABERTO.has(q.id)?' open':''}><summary>ver caminho</summary>`+
    `<div class="tab"><table><tr><th class="n">Ponto</th><th>Endereço (IP)</th><th class="n">Tempo</th></tr>${r.saltos.map(s=>
      `<tr><td class="n">${s.n}${s.n===1?' (roteador)':''}</td><td>${s.ip?`<code>${esc(s.ip)}</code>`:'sem resposta'}</td><td class="n">${s.ms==null?'–':num(s.ms,1)+' ms'}</td></tr>`).join('')}</table></div></details>`;
  return h}
function quedas(){
  const Q=D.quedas,f=D.falhas;
  $('qcap').textContent=f.n?`${f.n} ${f.n===1?'falha':'falhas'} no período, somando ${dur(f.seg)} sem conexão.`+(f.n>Q.length?` Mostrando as ${Q.length} mais recentes.`:''):'';
  $('q').innerHTML=Q.length?Q.map(q=>{const i=ST[q.status]||{nome:q.status},agora=q.fim==null;
      return `<li>${icon('critical')}<div class="o"><b>${esc(i.nome)}</b><span>${esc(quando(q.ini))}${i.dica?' · '+esc(i.dica):''}</span>${caminho(q)}</div>`+
        `<div class="d">${agora?'<b>acontecendo agora</b><br>há '+esc(dur(D.agora-q.ini)):'durou '+esc(dur(q.fim-q.ini))}</div></li>`}).join('')
    :`<li>${icon('good')}<div class="o"><b>Nenhuma falha neste período</b></div></li>`}

const DIA_ST={good:'Funcionou bem',warning:'Algumas falhas',critical:'Muitas falhas',nodata:'Sem medição'};
const upCat=up=>up>=99?'good':up>=95?'warning':'critical';   // mesmas faixas do tile "Conexão funcionando"
function horas(s){return s<3600?Math.round(s/60)+' min':num(s/3600,s<36000?1:0)+' h'}
function diaInfo(d){const [a,m,dd]=d.dia.split('-').map(Number),dt=new Date(a,m-1,dd),hoje=d===D.dias[D.dias.length-1];
  const nome=hoje?'Hoje':dt.toLocaleDateString('pt-BR',{weekday:'long',day:'2-digit',month:'2-digit'});
  if(!d.n)return{k:'nodata',nome,linhas:['Nenhuma medição neste dia']};
  const up=100*(d.n-d.fora)/d.n,k=upCat(up),med=d.n*D.intervalo,
    total=hoje?Math.max(med,D.agora-dt.getTime()/1000):86400;
  return{k,nome,linhas:[`${num(up,up===100?0:1)}% do tempo funcionando`,
    d.quedas?`Caiu ${d.quedas} ${d.quedas===1?'vez':'vezes'} · ${dur(d.fora*D.intervalo)} fora do ar`:(d.fora?`${dur(d.fora*D.intervalo)} fora do ar`:'Nenhuma queda'),
    `Medido ${horas(med)} de ${horas(total)}`+(hoje?' até agora':'')]}}
function dias(){
  const el=$('dias'),X=D.dias.map(diaInfo);
  el.style.gridTemplateColumns=`repeat(${D.n_dias},minmax(0,1fr))`;$('dias-t').textContent=`Últimos ${D.n_dias} dias`;
  el.innerHTML=X.map((x,i)=>`<i data-i="${i}" style="background:var(--${x.k})" aria-label="${esc(x.nome+': '+DIA_ST[x.k]+'. '+x.linhas.join('. '))}"></i>`).join('');
  const f=d=>{const [a,m,dd]=d.split('-');return dd+'/'+m};
  $('dias0').textContent=f(D.dias[0].dia);$('dias1').textContent='hoje';
  const card=el.parentElement,tip=card.querySelector('.tip');
  el.onpointermove=ev=>{const q=ev.target.closest('i[data-i]');if(!q){tip.style.display='none';return}
    const x=X[+q.dataset.i];
    tip.innerHTML=`<div class="t">${esc(x.nome)}</div><div class="r"><i class="q" style="background:var(--${x.k})"></i><b>${esc(DIA_ST[x.k])}</b></div>`+
      x.linhas.map(l=>`<div class="r">${esc(l)}</div>`).join('');
    tip.style.display='block';
    const cr=card.getBoundingClientRect(),r=q.getBoundingClientRect(),tw=tip.offsetWidth;
    let left=r.left-cr.left+r.width/2-tw/2;left=Math.max(8,Math.min(left,card.clientWidth-tw-8));
    tip.style.left=left+'px';tip.style.top=(r.bottom-cr.top+6)+'px'};
  el.onpointerleave=()=>{tip.style.display='none'}}

function tecnico(){
  const P=D.pontos,a=k=>avg(P.map(p=>p[k])),tot=D.resumo.reduce((s,r)=>s+r.n,0)||1;
  const M=[['Resposta do roteador (gateway)',a('gw'),' ms'],['Resposta da Cloudflare (1.1.1.1)',a('cf'),' ms'],['Resposta do Google (8.8.8.8)',a('gg'),' ms'],
    ['Perda de pacotes até o roteador',a('gwl'),' %',2],['Perda de pacotes até a Cloudflare',a('cfl'),' %',2],['Perda de pacotes até o Google',a('ggl'),' %',2],
    ['Tempo de resposta do DNS',a('dns'),' ms'],['Sinal Wi-Fi',a('dbm'),' dBm']];
  const vu=D.velocidade_ultimo,c=vu&&vu.carga;
  if(vu)M.push(['Último teste: baixar (download)',vu.down,' Mbps'],['Último teste: enviar (upload)',vu.up,' Mbps']);
  if(c)M.push(['Último teste: resposta parada (mediana)',c.ocioso,' ms'],['Último teste: resposta baixando (mediana)',c.down,' ms'],
    ['Último teste: resposta enviando (mediana)',c.up,' ms']);
  $('tec').innerHTML=`<p>A cada ${D.intervalo} segundos o monitor envia sinais (ping) para o roteador e para dois servidores na internet (Cloudflare e Google), testa o DNS e lê a força do sinal Wi-Fi.
    Se o roteador não responde, o problema está dentro de casa; se o roteador responde mas a internet não, o problema é da operadora.
    “Instável” significa que algum pacote se perdeu ou que a internet demorou mais de 150 ms nos dois servidores (Cloudflare e Google); se só um deles estiver lento, a internet não é considerada instável.</p>
    <div class="tab"><table><tr><th>Medição (média no período)</th><th class="n">Valor</th></tr>${M.map(([l,v,u,d])=>`<tr><td>${l}</td><td class="n">${num(v,d||1)}${u}</td></tr>`).join('')}</table></div>
    <div class="tab"><table><tr><th>Situação</th><th>Código</th><th class="n">Medições</th><th class="n">% do tempo</th></tr>${[...D.resumo].sort((x,y)=>y.n-x.n).map(r=>
      `<tr><td>${esc(stNome(r.status))}</td><td><code>${esc(r.status)}</code></td><td class="n">${num(r.n)}</td><td class="n">${num(100*r.n/tot,2)}%</td></tr>`).join('')}</table></div>`}

function tamanho(b){const f=(v,d)=>v.toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d});
  return b<1048576?f(b/1024,0)+' KB':b<1073741824?f(b/1048576,1)+' MB':f(b/1073741824,2)+' GB'}
function textoBanco(b){if(!b)return '';
  return ' · Banco: '+tamanho(b.bytes)+(b.por_dia==null?'':' · cresce ~'+tamanho(b.por_dia)+'/dia')}

function draw(){
  if(!D)return;
  D.pontos.forEach(p=>{const v=[p.cf,p.gg].filter(x=>x!=null);p.inet=v.length?v.reduce((s,x)=>s+x)/v.length:null;
    p.perda=Math.max(p.gwl||0,p.cfl||0,p.ggl||0);p.sinal=pctSinal(p.dbm)});
  document.querySelectorAll('.tip').forEach(t=>t.style.display='none');
  hero();tiles();timeline();dias();
  lineChart($('c1'),[{k:'inet',c:'--s1',n:'até a internet'},{k:'gw',c:'--s2',n:'até o roteador'}],{un:' ms',faixas:true,janelas:D.janelas_teste});
  velocidade();plano();botaoTeste();
  lineChart($('c2'),[{k:'sinal',c:'--s1',n:'sinal'}],{un:'%',max:100});
  quedas();tecnico();
  document.querySelectorAll('canvas').forEach(c=>c._sobre&&c._sobre());   // arrasto em andamento sobrevive à atualização
  $('upd').textContent=(FAIXA?'Mostrando de '+dm(D.de)+' '+hm(D.de)+' até '+(mesmoDia(D.de,D.ate)?'':dm(D.ate)+' ')+hm(D.ate)+' · ':'')+
    'Atualizado às '+new Date().toLocaleTimeString('pt-BR')+' · atualiza sozinho a cada 5 s'+textoBanco(D.banco)}

function hover(cv){const card=cv.parentElement,tip=card.querySelector('.tip');
  cv.onpointermove=ev=>{if(!cv._h||cv._arrastando)return;const r=cv.getBoundingClientRect(),h=cv._h(ev.clientX-r.left);cv._base();
    if(!h){tip.style.display='none';return}cv._mark(h);tip.innerHTML=h.html;tip.style.display='block';
    const cr=card.getBoundingClientRect(),ox=r.left-cr.left,tw=tip.offsetWidth;let left=ox+h.x+14;
    if(left+tw>card.clientWidth-8)left=ox+h.x-14-tw;
    tip.style.left=Math.max(8,left)+'px';tip.style.top=(r.top-cr.top+(cv.id==='tl'?cv.clientHeight+4:8))+'px'};
  cv.onpointerleave=()=>{if(cv._arrastando)return;tip.style.display='none';cv._base&&cv._base()}}

// Clicar, segurar e arrastar seleciona um trecho; ao soltar chama escolhe(de, ate) com o trecho arredondado ao
// minuto. Só usa a escala que o gráfico expõe (cv._x2e: x em px → epoch, já limitado à janela; cv._faixaY:
// [topo, base] da faixa, opcional). Arrasto curto (< 6 px ou < 60 s) é clique e não faz nada; Esc cancela.
// Com o touch-action:pan-y do canvas, no toque o arrasto vertical continua rolando a página (pointercancel).
const ARRASTO_MIN_PX=6,ARRASTO_MIN_S=60;
function arrasto(cv,escolhe){const card=cv.parentElement,tip=card.querySelector('.tip');let a=null;   // a = {id, x0, x}
  const trecho=()=>{const [e0,e1]=[cv._x2e(a.x0),cv._x2e(a.x)].sort((p,q)=>p-q),[j0,j1]=[cv._x2e(0),cv._x2e(cv.clientWidth)];
    return{de:Math.max(j0,Math.floor(e0/60)*60),ate:Math.min(j1,Math.ceil(e1/60)*60),curto:Math.abs(a.x-a.x0)<ARRASTO_MIN_PX||e1-e0<ARRASTO_MIN_S}};
  const pinta=()=>{cv._base();const g=cv.getContext('2d'),[y0,y1]=cv._faixaY||[0,cv.clientHeight];
    const xa=Math.min(a.x0,a.x),xb=Math.max(a.x0,a.x);
    g.fillStyle=css('--band');g.fillRect(xa,y0,xb-xa,y1-y0);
    g.strokeStyle=css('--axis');g.lineWidth=1;g.strokeRect(Math.round(xa)+.5,y0+.5,Math.max(0,Math.round(xb-xa)-1),y1-y0-1);
    const {de,ate}=trecho(),dia=!mesmoDia(de,ate),f=e=>(dia?dm(e)+' ':'')+hm(e);
    tip.innerHTML=`<div class="r"><b>De ${esc(f(de))} até ${esc(f(ate))}</b></div>`;tip.style.display='block';
    const r=cv.getBoundingClientRect(),cr=card.getBoundingClientRect(),tw=tip.offsetWidth;
    tip.style.left=Math.max(8,Math.min(r.left-cr.left+(xa+xb)/2-tw/2,card.clientWidth-tw-8))+'px';
    tip.style.top=(r.top-cr.top+cv.clientHeight+4)+'px'};
  const fim=ev=>{if(!a||(ev&&ev.pointerId!==a.id))return null;const t=trecho();
    try{cv.releasePointerCapture(a.id)}catch(e){}a=null;cv._arrastando=false;cv._sobre=null;tip.style.display='none';cv._base&&cv._base();return t};
  const px=ev=>{const r=cv.getBoundingClientRect();return Math.max(0,Math.min(r.width,ev.clientX-r.left))};
  cv.addEventListener('pointerdown',ev=>{if(!cv._x2e||ev.button!==0||a)return;
    a={id:ev.pointerId,x0:px(ev),x:px(ev)};cv.setPointerCapture(ev.pointerId);if(ev.pointerType==='mouse')ev.preventDefault()});
  cv.addEventListener('pointermove',ev=>{if(!a||ev.pointerId!==a.id)return;a.x=px(ev);
    if(!cv._arrastando&&Math.abs(a.x-a.x0)<ARRASTO_MIN_PX)return;   // ainda pode ser um clique: o hover segue
    cv._arrastando=true;cv._sobre=pinta;pinta()});
  cv.addEventListener('pointerup',ev=>{const t=fim(ev);if(t&&!t.curto)escolhe(t.de,t.ate)});
  cv.addEventListener('pointercancel',fim);
  addEventListener('keydown',ev=>{if(ev.key==='Escape'&&a)fim()})}

function marcaPeriodo(){document.querySelectorAll('#per button[data-min]').forEach(b=>b.setAttribute('aria-pressed',!FAIXA&&+b.dataset.min===MIN));
  $('bdatas').setAttribute('aria-pressed',!!FAIXA)}
async function load(){
  try{const r=await fetch(FAIXA?`/api?de=${FAIXA.de}&ate=${FAIXA.ate}`:'/api?min='+MIN);if(!r.ok)throw 0;D=await r.json();draw()}
  catch(e){$('upd').textContent='Não foi possível carregar os dados. O painel ainda está rodando?'}
  finally{$('m').classList.remove('carregando')}}
function trocaPeriodo(){marcaPeriodo();$('m').classList.add('carregando');load()}
function abreDatas(abrir){$('datas').hidden=!abrir;$('bdatas').setAttribute('aria-expanded',abrir)}
// período escolhido em "Escolher datas" ou arrastando no "Como foi o período"; os botões de período o limpam
function escolheFaixa(de,ate){FAIXA={de,ate};abreDatas(false);trocaPeriodo()}
document.querySelectorAll('#per button[data-min]').forEach(b=>b.onclick=()=>{MIN=+b.dataset.min;FAIXA=null;try{localStorage.setItem('periodo',MIN)}catch(e){}
  abreDatas(false);trocaPeriodo()});
// "Escolher datas": abre já preenchido com o período que está na tela. A escolha não fica salva:
// quem reabre o painel dias depois volta para um período "até agora", não para uma data velha.
// A hora é um campo de texto HH:MM, não datetime-local: esse o navegador desenha no idioma dele,
// e em inglês aparece 2:30 PM. Datas e horas são montadas em hora local (toISOString() daria UTC).
const p2=n=>String(n).padStart(2,'0');
const dataLocal=e=>{const d=new Date(e*1000);return `${d.getFullYear()}-${p2(d.getMonth()+1)}-${p2(d.getDate())}`};
const horaLocal=e=>{const d=new Date(e*1000);return `${p2(d.getHours())}:${p2(d.getMinutes())}`};
const HORA=/^([01]?\d|2[0-3]):([0-5]\d)$/;
// "9:05" → "09:05"; null se não for uma hora válida
function hora24(t){const h=HORA.exec(t.trim());return h&&`${p2(+h[1])}:${h[2]}`}
// "AAAA-MM-DD" + "HH:MM" → epoch (hora local)
function epochLocal(data,hora){const [a,m,d]=data.split('-').map(Number),[h,min]=hora.split(':').map(Number);
  return new Date(a,m-1,d,h,min).getTime()/1000}
$('bdatas').onclick=()=>{const abrir=$('datas').hidden;abreDatas(abrir);if(!abrir)return;
  const agora=Date.now()/1000;$('dde').max=dataLocal(agora);$('derro').textContent='';
  if(D){$('dde').value=dataLocal(D.de);$('hde').value=horaLocal(D.de);$('date').value=dataLocal(D.ate);$('hate').value=horaLocal(D.ate)}
  $('dde').focus()};
$('datas').onsubmit=ev=>{ev.preventDefault();
  const hde=hora24($('hde').value),hate=hora24($('hate').value);
  if(hde)$('hde').value=hde;if(hate)$('hate').value=hate;
  const vazia=!$('dde').value||!$('date').value,de=epochLocal($('dde').value,hde||''),ate=epochLocal($('date').value,hate||''),agora=Date.now()/1000;
  const erro=vazia?'Preencha as duas datas.':!hde||!hate?'Hora inválida: use o formato 14:30.'
    :isNaN(de)||isNaN(ate)?'Preencha as duas datas.':de>=agora?'O início precisa ser antes de agora.'
    :de>=ate?'O início precisa ser antes do fim.':ate-de>D.periodo_max?`Escolha no máximo ${D.periodo_max/86400} dias.`:'';
  $('derro').textContent=erro;if(erro)return;
  escolheFaixa(de,ate)};
['tl','c1','c2','c3'].forEach(id=>hover($(id)));
arrasto($('tl'),escolheFaixa);
$('q').addEventListener('toggle',ev=>{const id=+ev.target.dataset.id;if(!id)return;
  ev.target.open?CAMINHO_ABERTO.add(id):CAMINHO_ABERTO.delete(id)},true);
addEventListener('resize',draw);matchMedia('(prefers-color-scheme:dark)').onchange=draw;
if(![60,360,1440,10080].includes(MIN))MIN=60;
marcaPeriodo();load();setInterval(load,5000);
