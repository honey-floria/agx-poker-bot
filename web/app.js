/* AGX-style browser-local six-player 240-hand match. No network calls. */
const RANKS = "23456789TJQKA", SUITS = "cdhs";
const START = 10000, SB = 50, BB = 100, HANDS_PER_ROTATION = 40, ROTATIONS = 6, TOTAL_HANDS = 240;
const AI_DELAY_MS = 90;
const AGENTS = [
  {id:0,name:"你",tag:"HUMAN",style:"human",tight:.54,agg:.58},
  {id:1,name:"Atlas",tag:"TIGHT AGG.",style:"tight",tight:.70,agg:.75},
  {id:2,name:"Nova",tag:"BALANCED",style:"balanced",tight:.56,agg:.58},
  {id:3,name:"Mori",tag:"CALLING",style:"loose",tight:.31,agg:.25},
  {id:4,name:"Vega",tag:"LOOSE AGG.",style:"loose",tight:.38,agg:.82},
  {id:5,name:"Sage",tag:"ADAPTIVE",style:"balanced",tight:.50,agg:.63}
];
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
let MATCH = null, G = null, timer = null, decisionToken = 0;

function cardHTML(c, mini=false, back=false) {
  if (back) return `<span class="${mini?'mini-card':'card'} back"></span>`;
  const red = "dh".includes(c[1]) ? " red" : "", suit = {c:"♣",d:"♦",h:"♥",s:"♠"}[c[1]];
  return mini ? `<span class="mini-card${red}">${c[0]}${suit}</span>` : `<span class="card${red}"><span>${c[0]}${suit}</span><span>${c[0]}${suit}</span></span>`;
}
function shuffle(a) { for (let i=a.length-1;i;i--) { const j=Math.floor(Math.random()*(i+1)); [a[i],a[j]]=[a[j],a[i]]; } return a; }
function freshDeck() { return shuffle([...RANKS].flatMap(r => [...SUITS].map(s => r+s))); }
function money(n) { return `${n>0?"+":""}${n.toLocaleString("zh-CN")}`; }
function chips(n) { return n.toLocaleString("zh-CN"); }
function rv(c) { return RANKS.indexOf(c[0])+2; }
function cmp(a,b) { for(let i=0;i<Math.max(a.length,b.length);i++){const x=a[i]||0,y=b[i]||0;if(x!==y)return x-y;}return 0; }
function eval5(cs) {
  const v=cs.map(rv).sort((a,b)=>b-a),cnt={}; v.forEach(x=>cnt[x]=(cnt[x]||0)+1);
  const gr=Object.entries(cnt).map(([r,n])=>[n,+r]).sort((a,b)=>b[0]-a[0]||b[1]-a[1]);
  const flush=new Set(cs.map(c=>c[1])).size===1,u=[...new Set(v)]; if(u.includes(14))u.push(1);
  let sh=0; for(let i=0;i<=u.length-5;i++)if(u[i]-u[i+4]===4)sh=Math.max(sh,u[i]);
  if(flush&&sh)return[8,sh]; if(gr[0][0]===4)return[7,gr[0][1],gr[1][1]];
  if(gr[0][0]===3&&gr[1][0]===2)return[6,gr[0][1],gr[1][1]]; if(flush)return[5,...v]; if(sh)return[4,sh];
  if(gr[0][0]===3)return[3,gr[0][1],...gr.slice(1).map(x=>x[1])];
  if(gr[0][0]===2&&gr[1][0]===2)return[2,Math.max(gr[0][1],gr[1][1]),Math.min(gr[0][1],gr[1][1]),gr[2][1]];
  if(gr[0][0]===2)return[1,gr[0][1],...gr.slice(1).map(x=>x[1])]; return[0,...v];
}
function evaluate(cs) {
  let best=null;
  for(let a=0;a<cs.length-4;a++)for(let b=a+1;b<cs.length-3;b++)for(let c=b+1;c<cs.length-2;c++)for(let d=c+1;d<cs.length-1;d++)for(let e=d+1;e<cs.length;e++){
    const x=eval5([cs[a],cs[b],cs[c],cs[d],cs[e]]); if(!best||cmp(x,best)>0)best=x;
  }
  return best;
}
const HAND_NAMES=["高牌","一对","两对","三条","顺子","同花","葫芦","四条","同花顺"];
function preStrength(h) {
  const a=rv(h[0]),b=rv(h[1]),hi=Math.max(a,b),lo=Math.min(a,b); if(a===b)return Math.min(1,.52+(hi-2)*.037);
  let s=(hi-2)/12*.46+(lo-2)/12*.2; if(h[0][1]===h[1][1])s+=.075;
  const g=hi-lo; s+=g===1?.07:g===2?.035:g>=5?-.055:0; if(hi===14)s+=.1;if(hi>=12&&lo>=10)s+=.08;
  return Math.max(0,Math.min(1,s));
}
function visibleBoard(){return G.board.slice(0,[0,3,4,5][G.street]);}
function currentBet(){return Math.max(...G.players.map(p=>p.bet));}
function active(){return G.players.filter(p=>!p.folded);}
function canAct(p){return !p.folded&&!p.allin&&p.stack>0;}
function humanSeat(){return G.players.findIndex(p=>p.id===0);}
function seatPos(i){const d=(i-G.button+6)%6;return["BTN","SB","BB","UTG","HJ","CO"][d];}
function log(name,text){const box=$("#actionLog");box.querySelector(".empty-log")?.remove();const row=document.createElement("div");row.className="log-item";row.innerHTML=`<time>${["翻前","翻牌","转牌","河牌"][G.street]}</time><div><b>${name}</b> ${text}</div>`;box.prepend(row);}

function createMatch(){
  clearTimeout(timer); decisionToken++;
  const offset=Math.floor(Math.random()*6);
  MATCH={rotation:0,rotationHand:0,globalHand:1,cumulative:Array(6).fill(0),baseDeals:Array.from({length:40},freshDeck),baseButtons:Array.from({length:40},(_,i)=>(i+offset)%6),completed:false};
  startHand();
}
function startHand(){
  clearTimeout(timer); decisionToken++;
  const r=MATCH.rotation,h=MATCH.rotationHand,deck=MATCH.baseDeals[h].slice(),button=MATCH.baseButtons[h];
  const players=Array.from({length:6},(_,seat)=>{
    const agent=AGENTS[(seat+r)%6];
    return {...agent,seat,hole:deck.slice(seat*2,seat*2+2),stack:START,bet:0,invested:0,folded:false,allin:false,acted:false,show:false};
  });
  G={deck,button,street:0,board:deck.slice(12,17),turn:(button+3)%6,pot:0,lastRaise:BB,ended:false,scored:false,players};
  $("#actionLog").innerHTML=""; $("#startBtn").style.display="none"; $("#resultModal").classList.remove("show"); $("#resultModal").setAttribute("aria-hidden","true");
  postBlind((button+1)%6,SB,"小盲"); postBlind((button+2)%6,BB,"大盲"); G.turn=(button+3)%6;
  log("牌桌",`第 ${MATCH.globalHand} / 240 手 · 阶段 ${r+1} / 6 · 按钮位 ${G.players[button].name}`);
  render(); runTurn();
}
function nextMatchHand(){
  if(MATCH.completed)return createMatch();
  if(MATCH.rotationHand===HANDS_PER_ROTATION-1){MATCH.rotation++;MATCH.rotationHand=0;}else MATCH.rotationHand++;
  MATCH.globalHand=MATCH.rotation*HANDS_PER_ROTATION+MATCH.rotationHand+1; startHand();
}
function postBlind(i,amount,label){const p=G.players[i],x=Math.min(amount,p.stack);p.stack-=x;p.bet+=x;p.invested+=x;G.pot+=x;log(p.name,`${label} ${chips(x)}`);}
function nextSeat(from){for(let n=1;n<=6;n++){const i=(from+n)%6;if(canAct(G.players[i]))return i;}return-1;}
function everyoneSettled(){const mx=currentBet();return active().every(p=>!canAct(p)||(p.acted&&p.bet===mx));}
function awardSingle(){const p=active()[0],amount=G.pot;p.stack+=amount;finish(`${p.name} 赢得本手`,`${p.name} 成为唯一未弃牌玩家，获得 ${chips(amount)} 筹码。`,[p]);}
function advance(){
  if(G.ended)return; if(active().length===1)return awardSingle();
  if(everyoneSettled()){
    if(G.street===3)return showdown();
    G.street++; G.players.forEach(p=>{p.bet=0;p.acted=false;}); G.lastRaise=BB; G.turn=nextSeat(G.button);
    log("牌桌",`进入${["","翻牌圈","转牌圈","河牌圈"][G.street]}`); render();
    if(G.turn<0){ if(G.street===3)return showdown(); return setTimeout(advance,AI_DELAY_MS); }
    return runTurn();
  }
  G.turn=nextSeat(G.turn); if(G.turn<0)return advance(); render(); runTurn();
}
function commit(i,type,to=0){
  if(G.ended||i<0)return; const p=G.players[i],mx=currentBet(),call=Math.max(0,mx-p.bet);
  if(type==="fold"){p.folded=true;p.acted=true;log(p.name,"弃牌");}
  else if(type==="check"){p.acted=true;log(p.name,"过牌");}
  else if(type==="call"){
    const x=Math.min(call,p.stack);p.stack-=x;p.bet+=x;p.invested+=x;G.pot+=x;p.acted=true;if(!p.stack)p.allin=true;log(p.name,`${p.allin?"全下跟注":"跟注"} ${chips(x)}`);
  } else {
    const target=Math.min(p.bet+p.stack,Math.max(to,mx+G.lastRaise)),x=target-p.bet,raise=target-mx;
    p.stack-=x;p.bet=target;p.invested+=x;G.pot+=x;p.acted=true;if(!p.stack)p.allin=true;
    if(raise>=G.lastRaise){G.lastRaise=raise;G.players.forEach((q,j)=>{if(j!==i&&canAct(q))q.acted=false;});}
    log(p.name,`${p.allin?"全下至":"加注至"} ${chips(target)}`);
  }
  render(); clearTimeout(timer); timer=setTimeout(advance,AI_DELAY_MS);
}
function chooseAiAction(i){
  const p=G.players[i],mx=currentBet(),call=mx-p.bet,board=visibleBoard();
  const made=G.street===0?preStrength(p.hole):(evaluate([...p.hole,...board])[0]/8+.06*Math.random());
  const potOdds=call/Math.max(1,G.pot+call),pressure=call/Math.max(1,p.stack),threshold=p.tight+(G.street?-.2:0);
  let type="fold",to=0;
  if(call===0){if(made>threshold&&Math.random()<p.agg){type="raise";to=Math.max(mx+G.lastRaise,Math.round((G.pot*(.35+p.agg*.3))/50)*50);}else type="check";}
  else if(made>threshold+.16&&Math.random()<p.agg){type="raise";to=Math.max(mx+G.lastRaise,Math.round((mx*2.5+G.pot*.3)/50)*50);}
  else if(made+(.16*(1-pressure))>Math.max(threshold-.16,potOdds+.08)||(p.style==="loose"&&Math.random()<.28))type="call";
  if(to>=p.bet+p.stack*.82){type="raise";to=p.bet+p.stack;} return{type,to};
}
function safeAiAction(i){
  try{return chooseAiAction(i);}catch(_){const p=G.players[i],call=currentBet()-p.bet;return call===0?{type:"check",to:0}:call<p.stack*.12?{type:"call",to:0}:{type:"fold",to:0};}
}
function aiAction(i){
  const token=decisionToken,choice=safeAiAction(i); log("系统",`${G.players[i].name} 计算完成`);
  clearTimeout(timer);timer=setTimeout(()=>{if(token!==decisionToken||!G||G.ended||G.turn!==i)return;commit(i,choice.type,choice.to);},AI_DELAY_MS);
}
function runTurn(){
  if(G.ended)return;if(active().length===1)return awardSingle();const p=G.players[G.turn];
  if(!p||!canAct(p)){G.turn=nextSeat(G.turn);if(G.turn<0)return advance();return runTurn();}
  render();if(p.id===0)enableHuman();else{disableHuman();aiAction(G.turn);}
}
function enableHuman(){
  const i=humanSeat(),p=G.players[i],mx=currentBet(),call=Math.max(0,mx-p.bet),min=Math.min(p.bet+p.stack,mx+G.lastRaise),max=p.bet+p.stack;
  $("#turnTitle").textContent=`轮到你行动 · ${seatPos(i)}`;$("#turnHint").textContent=call?`跟注需要 ${chips(Math.min(call,p.stack))}`:"当前无人下注，可以过牌";
  $("#foldBtn").disabled=false;$("#callBtn").disabled=false;$("#callBtn").textContent=call?`跟注 ${chips(Math.min(call,p.stack))}`:"过牌";$("#raiseBtn").textContent=mx?"加注":"下注";
  $("#raiseRange").min=min;$("#raiseRange").max=max;$("#raiseRange").value=Math.min(max,Math.max(min,Math.round((mx+G.pot*.65)/50)*50));
  $("#raiseRange").disabled=max<=mx;$("#raiseBtn").disabled=max<=mx;$("#allinBtn").disabled=false;$$('.quick button').forEach(b=>b.disabled=max<=mx);updateRaise();
}
function disableHuman(){["#foldBtn","#callBtn","#raiseBtn","#allinBtn","#raiseRange"].forEach(s=>$(s).disabled=true);$$('.quick button').forEach(b=>b.disabled=true);if(G&&!G.ended){const p=G.players[G.turn];$("#turnTitle").textContent=p?`${p.name} 正在行动`:"自动发牌";$("#turnHint").textContent=p?`${p.tag} · 固定预算本地策略`:"全员全下，直接摊牌";}}
function sidePots(){
  const levels=[...new Set(G.players.filter(p=>p.invested>0).map(p=>p.invested))].sort((a,b)=>a-b);let prev=0,pots=[];
  for(const level of levels){const contributors=G.players.filter(p=>p.invested>=level),amount=(level-prev)*contributors.length,eligible=contributors.filter(p=>!p.folded);if(amount&&eligible.length)pots.push({amount,eligible});prev=level;}return pots;
}
function showdown(){
  const board=visibleBoard(),awards=new Map();
  for(const pot of sidePots()){
    let best=null,w=[];for(const p of pot.eligible){const sc=evaluate([...p.hole,...board]);if(!best||cmp(sc,best)>0){best=sc;w=[p];}else if(cmp(sc,best)===0)w.push(p);}
    w.sort((a,b)=>((a.seat-G.button+6)%6)-((b.seat-G.button+6)%6));const share=Math.floor(pot.amount/w.length),rem=pot.amount-share*w.length;
    w.forEach((p,i)=>awards.set(p,(awards.get(p)||0)+share+(i<rem?1:0)));
  }
  awards.forEach((x,p)=>p.stack+=x);const winners=[...awards.keys()].sort((a,b)=>awards.get(b)-awards.get(a));
  finish(winners.some(p=>p.id===0)?"你赢得本手！":`${winners[0].name} 赢得本手`,winners.map(p=>`${p.name} 以${HAND_NAMES[evaluate([...p.hole,...board])[0]]}获得 ${chips(awards.get(p))}`).join("；"),winners);
}
function standingsHTML(){
  return AGENTS.map(a=>({a,net:MATCH.cumulative[a.id]})).sort((x,y)=>y.net-x.net).map((x,i)=>`<div class="standing-row${x.a.id===0?' you':''}"><span>#${i+1}</span><b>${x.a.name}</b><span class="${x.net>0?'positive':x.net<0?'negative':''}">${money(x.net)}</span></div>`).join("");
}
function scoreHand(){if(G.scored)return;G.scored=true;G.players.forEach(p=>MATCH.cumulative[p.id]+=p.stack-START);}
function finish(title,text,winners){
  G.ended=true;clearTimeout(timer);decisionToken++;G.players.forEach(p=>{if(!p.folded)p.show=true;});scoreHand();
  MATCH.completed=MATCH.globalHand===TOTAL_HANDS;disableHuman();render();$("#turnTitle").textContent=MATCH.completed?"比赛完成":"本手结束";$("#turnHint").textContent=MATCH.completed?"查看最终累计净额排名":"查看结算，然后继续下一手";
  $("#resultEyebrow").textContent=MATCH.completed?"MATCH COMPLETE":`HAND ${MATCH.globalHand} / ${TOTAL_HANDS}`;$("#resultTitle").textContent=MATCH.completed?"六阶段比赛完成":title;$("#resultText").textContent=MATCH.completed?"240手全部完成。最终名次按累计真实净额从高到低排列。":text;
  $("#resultCards").innerHTML=winners.map(p=>`<div class="result-hand"><small>${p.name}</small><div class="cards">${p.hole.map(c=>cardHTML(c)).join("")}</div></div>`).join("");$("#modalStandings").innerHTML=standingsHTML();
  $("#playAgain").textContent=MATCH.completed?"开始新比赛":MATCH.rotationHand===39?`进入阶段 ${MATCH.rotation+2}`:`继续第 ${MATCH.globalHand+1} 手`;
  $("#resultModal").classList.add("show");$("#resultModal").setAttribute("aria-hidden","false");$("#gameStatus").textContent=MATCH.completed?"比赛完成":`第 ${MATCH.globalHand} 手结束`;
}
function updateRaise(){if(G)$("#raiseValue").textContent=chips(+$(`#raiseRange`).value);}
function renderProfiles(){
  if(!MATCH){$("#agentProfiles").innerHTML=AGENTS.map(a=>`<div class="profile"><span class="avatar">${a.name[0]}</span><div><strong>${a.name}</strong><small>${a.tag}</small></div><i class="dot ${a.style}"></i></div>`).join("");return;}
  $("#agentProfiles").innerHTML=AGENTS.map(a=>{const seat=G?G.players.findIndex(p=>p.id===a.id):-1,net=MATCH.cumulative[a.id];return`<div class="profile${a.id===0?' current-player':''}"><span class="avatar">${a.name[0]}</span><div><strong>${a.name}</strong><small>${seat>=0?`座位 ${seat} · ${seatPos(seat)}`:a.tag}</small></div><small class="profile-net ${net>0?'positive':net<0?'negative':''}">${money(net)}</small></div>`;}).join("");
}
function render(){
  renderProfiles();if(!G)return;const done=MATCH.globalHand-(G.ended?0:1);$("#pot").textContent=chips(G.pot);$("#streetLabel").textContent=["PRE-FLOP","FLOP","TURN","RIVER"][G.street];$("#board").innerHTML=visibleBoard().map(c=>cardHTML(c)).join("");$("#buttonSeat").textContent=G.players[G.button].name;
  $("#matchProgressText").textContent=`${done} / ${TOTAL_HANDS}`;$("#progressBar").style.width=`${done/TOTAL_HANDS*100}%`;$("#rotationValue").textContent=`${MATCH.rotation+1} / 6`;$("#rotationHandValue").textContent=`${MATCH.rotationHand+1} / 40`;
  $("#gameStatus").textContent=G.ended?`第 ${MATCH.globalHand} 手结束`:`第 ${MATCH.globalHand} 手 · ${["翻前","翻牌","转牌","河牌"][G.street]} · ${G.players[G.turn]?.name||"自动"}行动`;
  $("#seats").innerHTML=G.players.map((p,i)=>`<div class="seat seat-${i}${G.turn===i&&!G.ended?' turn':''}${p.folded?' folded':''}"><div class="seat-top"><span class="seat-name">${p.name}${i===G.button?'<i class="dealer">D</i>':''}</span><span class="seat-pos">${seatPos(i)}</span></div><div class="seat-stack">${p.allin?'ALL-IN':chips(p.stack)}</div><div class="hole-mini">${p.hole.map(c=>cardHTML(c,true,p.id!==0&&!p.show)).join("")}</div>${p.bet?`<span class="seat-bet">● ${chips(p.bet)}</span>`:""}</div>`).join("");
}
function setup(){
  renderProfiles();$("#startBtn").onclick=createMatch;$("#newHandTop").textContent="重新比赛";$("#newHandTop").onclick=createMatch;$("#playAgain").onclick=nextMatchHand;
  $("#foldBtn").onclick=()=>commit(humanSeat(),"fold");$("#callBtn").onclick=()=>{const i=humanSeat();commit(i,currentBet()===G.players[i].bet?"check":"call");};
  $("#raiseBtn").onclick=()=>commit(humanSeat(),"raise",+$("#raiseRange").value);$("#allinBtn").onclick=()=>{const i=humanSeat();commit(i,"raise",G.players[i].bet+G.players[i].stack);};$("#raiseRange").oninput=updateRaise;
  $$('.quick button').forEach(b=>b.onclick=()=>{$("#raiseRange").value=Math.min(+$(`#raiseRange`).max,Math.max(+$(`#raiseRange`).min,Math.round((currentBet()+G.pot*(+b.dataset.pot))/50)*50));updateRaise();});
  $("#clearLog").onclick=()=>$("#actionLog").innerHTML='<div class="empty-log">记录已清空</div>';
  document.addEventListener("keydown",e=>{if(!G||G.ended||G.players[G.turn]?.id!==0)return;if(e.key.toLowerCase()==="f")$("#foldBtn").click();if(e.key.toLowerCase()==="c")$("#callBtn").click();if(e.key.toLowerCase()==="r")$("#raiseBtn").click();});
}
setup();
