/* AGX six-player NLHE submission. QuickJS compatible, zero dependencies. */

var RANKS = "23456789TJQKA";
var SUITS = "cdhs";
var POSITION_OPEN = {UTG:0.64,HJ:0.59,CO:0.53,BTN:0.46,SB:0.50,BB:0.70};
var OPEN_RANGES = {
  UTG:"55 66 77 88 99 TT JJ QQ KK AA ATs AJs AQs AKs KJs KQs QJs JTs T9s 98s AQo AKo KQo",
  HJ:"44 55 66 77 88 99 TT JJ QQ KK AA A8s A9s ATs AJs AQs AKs KTs KJs KQs QTs QJs JTs T9s 98s 87s AJo AQo AKo KQo",
  CO:"22 33 44 55 66 77 88 99 TT JJ QQ KK AA A2s A3s A4s A5s A6s A7s A8s A9s ATs AJs AQs AKs K8s K9s KTs KJs KQs Q9s QTs QJs J9s JTs T8s T9s 98s 87s 76s ATo AJo AQo AKo KJo KQo QJo",
  BTN:"22 33 44 55 66 77 88 99 TT JJ QQ KK AA A2s A3s A4s A5s A6s A7s A8s A9s ATs AJs AQs AKs K5s K6s K7s K8s K9s KTs KJs KQs Q7s Q8s Q9s QTs QJs J7s J8s J9s JTs T7s T8s T9s 97s 98s 86s 87s 75s 76s 65s 54s A8o A9o ATo AJo AQo AKo KTo KJo KQo QTo QJo JTo",
  SB:"22 33 44 55 66 77 88 99 TT JJ QQ KK AA A2s A3s A4s A5s A6s A7s A8s A9s ATs AJs AQs AKs K7s K8s K9s KTs KJs KQs Q8s Q9s QTs QJs J8s J9s JTs T8s T9s 98s 87s 76s 65s A9o ATo AJo AQo AKo KTo KJo KQo QJo",
  BB:"22 33 44 55 66 77 88 99 TT JJ QQ KK AA A2s A3s A4s A5s A6s A7s A8s A9s ATs AJs AQs AKs K5s K6s K7s K8s K9s KTs KJs KQs Q7s Q8s Q9s QTs QJs J7s J8s J9s JTs T7s T8s T9s 97s 98s 86s 87s 75s 76s 65s 54s A8o A9o ATo AJo AQo AKo KTo KJo KQo QTo QJo JTo"
};
var DEFEND_EARLY = "66 77 88 99 TT JJ QQ KK AA ATs AJs AQs AKs KQs AQo AKo";
var DEFEND_LATE = "22 33 44 55 66 77 88 99 TT JJ QQ KK AA A8s A9s ATs AJs AQs AKs KTs KJs KQs QTs QJs JTs T9s 98s 87s AJo AQo AKo KQo";
var THREEBET_VALUE = "JJ QQ KK AA AQs AKs AKo";
var FOURBET_VALUE = "QQ KK AA AKs AKo";
var THREEBET_BLUFF = "A5s A4s KTs QTs";
var memory = { handKey:"", actionCount:0, players:{}, flags:{} };

function rankValue(card) { return RANKS.indexOf(card.charAt(0)) + 2; }
function suitValue(card) { return card.charAt(1); }
function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }
function has(xs, x) { return xs.indexOf(x) >= 0; }
function rangeHas(range, code) { return (" "+range+" ").indexOf(" "+code+" ")>=0; }
function handCode(cards) {
  var a=rankValue(cards[0]),b=rankValue(cards[1]),hi=Math.max(a,b),lo=Math.min(a,b);
  if(hi===lo) return RANKS.charAt(hi-2)+RANKS.charAt(lo-2);
  return RANKS.charAt(hi-2)+RANKS.charAt(lo-2)+(suitValue(cards[0])===suitValue(cards[1])?"s":"o");
}
function seededRandom(view) {
  var text=String(view.hand)+":"+String(view.rotation)+":"+String(view.street)+":"+view.me.cards.join("")+":"+view.board.join("")+":"+view.actions.length;
  var seed=2166136261;
  for(var i=0;i<text.length;i++) { seed^=text.charCodeAt(i);seed=Math.imul(seed,16777619); }
  return function() { seed+=0x6D2B79F5;var t=seed;t=Math.imul(t^(t>>>15),t|1);t^=t+Math.imul(t^(t>>>7),t|61);return ((t^(t>>>14))>>>0)/4294967296; };
}

function evaluate5(cards) {
  var counts = {}, suits = {}, values = [], i, r, s;
  for (i=0;i<5;i++) {
    r=rankValue(cards[i]); s=suitValue(cards[i]);
    counts[r]=(counts[r]||0)+1; suits[s]=(suits[s]||0)+1; values.push(r);
  }
  values.sort(function(a,b){return b-a;});
  var unique=[];
  for(i=0;i<values.length;i++) if(i===0||values[i]!==values[i-1]) unique.push(values[i]);
  if(unique.indexOf(14)>=0) unique.push(1);
  var straightHigh=0, run=1;
  for(i=1;i<unique.length;i++) {
    if(unique[i-1]-1===unique[i]) { run++; if(run>=5) straightHigh=Math.max(straightHigh,unique[i-4]); }
    else run=1;
  }
  var flush=false;
  for(s in suits) if(suits[s]===5) flush=true;
  var groups=[];
  for(r in counts) groups.push([counts[r],Number(r)]);
  groups.sort(function(a,b){return b[0]-a[0]||b[1]-a[1];});
  if(flush&&straightHigh) return [8,straightHigh];
  if(groups[0][0]===4) return [7,groups[0][1],groups[1][1]];
  if(groups[0][0]===3&&groups[1][0]===2) return [6,groups[0][1],groups[1][1]];
  if(flush) return [5].concat(values);
  if(straightHigh) return [4,straightHigh];
  if(groups[0][0]===3) return [3,groups[0][1],groups[1][1],groups[2][1]];
  if(groups[0][0]===2&&groups[1][0]===2) return [2,Math.max(groups[0][1],groups[1][1]),Math.min(groups[0][1],groups[1][1]),groups[2][1]];
  if(groups[0][0]===2) return [1,groups[0][1],groups[1][1],groups[2][1],groups[3][1]];
  return [0].concat(values);
}

function compareScore(a,b) {
  for(var i=0;i<Math.max(a.length,b.length);i++) {
    var x=a[i]||0,y=b[i]||0;
    if(x!==y) return x>y?1:-1;
  }
  return 0;
}

function evaluate(cards) {
  if(cards.length<5) return [0];
  var best=null,n=cards.length;
  for(var a=0;a<n-4;a++) for(var b=a+1;b<n-3;b++) for(var c=b+1;c<n-2;c++)
    for(var d=c+1;d<n-1;d++) for(var e=d+1;e<n;e++) {
      var sc=evaluate5([cards[a],cards[b],cards[c],cards[d],cards[e]]);
      if(best===null||compareScore(sc,best)>0) best=sc;
    }
  return best;
}

function preflopStrength(cards) {
  var a=rankValue(cards[0]), b=rankValue(cards[1]);
  var hi=Math.max(a,b), lo=Math.min(a,b), suited=suitValue(cards[0])===suitValue(cards[1]);
  if(a===b) return clamp(0.52+(hi-2)*0.037,0,1);
  var score=(hi-2)/12*0.46+(lo-2)/12*0.20;
  if(suited) score+=0.075;
  var gap=hi-lo;
  if(gap===1) score+=0.07; else if(gap===2) score+=0.035; else if(gap>=5) score-=0.055;
  if(hi===14) score+=0.10;
  if(hi>=12&&lo>=10) score+=0.08;
  return clamp(score,0,1);
}

function deckWithout(known) {
  var used={},deck=[],i,j,c;
  for(i=0;i<known.length;i++) used[known[i]]=true;
  for(i=0;i<RANKS.length;i++) for(j=0;j<SUITS.length;j++) {
    c=RANKS.charAt(i)+SUITS.charAt(j); if(!used[c]) deck.push(c);
  }
  return deck;
}

function drawOne(deck,rng) {
  var i=Math.floor(rng()*deck.length),c=deck[i];deck[i]=deck[deck.length-1];deck.pop();return c;
}

function sampleRangeHand(deck,floor,rng) {
  var bestI=0,bestJ=1,best=-1,i,j,s;
  for(var t=0;t<5;t++) {
    i=Math.floor(rng()*deck.length);j=Math.floor(rng()*(deck.length-1));if(j>=i)j++;
    s=preflopStrength([deck[i],deck[j]]);
    if(s>best) {best=s;bestI=i;bestJ=j;}
    if(s>=floor) {bestI=i;bestJ=j;break;}
  }
  var hi=Math.max(bestI,bestJ),lo=Math.min(bestI,bestJ),a=deck[lo],b=deck[hi];
  deck[hi]=deck[deck.length-1];deck.pop();deck[lo]=deck[deck.length-1];deck.pop();
  return [a,b];
}

function sampleBudget(street,opponents) {
  var total=street==="river"?128:(street==="turn"?112:96);
  return clamp(Math.floor(total/Math.max(1,opponents)),12,48);
}

function estimateEquity(hole,board,rangeFloors,samples,rng) {
  var baseDeck=deckWithout(hole.concat(board)), need=5-board.length, wins=0,ties=0,opponents=rangeFloors.length;
  for(var k=0;k<samples;k++) {
    var deck=baseDeck.slice(),runout=[],o;
    for(o=0;o<need;o++) runout.push(drawOne(deck,rng));
    var fullBoard=board.concat(runout),oppHands=[];
    for(o=0;o<opponents;o++) oppHands.push(sampleRangeHand(deck,rangeFloors[o],rng));
    var hero=evaluate(hole.concat(fullBoard)), bestCmp=0, tied=1;
    for(o=0;o<opponents;o++) {
      var opp=evaluate(oppHands[o].concat(fullBoard));
      var cmp=compareScore(opp,hero);
      if(cmp>0) {bestCmp=1;break;} if(cmp===0) tied++;
    }
    if(bestCmp===0) { if(tied===1) wins++; else ties+=1/tied; }
  }
  return (wins+ties)/samples;
}

function boardTexture(board,hole) {
  var all=board.concat(hole), rankCount={}, suitCount={}, vals=[],i,r,s;
  for(i=0;i<all.length;i++) {r=rankValue(all[i]);s=suitValue(all[i]);rankCount[r]=(rankCount[r]||0)+1;suitCount[s]=(suitCount[s]||0)+1;vals.push(r);}
  var maxSuit=0,pairs=0;
  for(s in suitCount) maxSuit=Math.max(maxSuit,suitCount[s]);
  for(r in rankCount) if(rankCount[r]>=2) pairs++;
  vals.sort(function(a,b){return a-b;});
  var uniq=[];for(i=0;i<vals.length;i++) if(i===0||vals[i]!==vals[i-1]) uniq.push(vals[i]);
  var connected=0;for(i=1;i<uniq.length;i++) if(uniq[i]-uniq[i-1]<=2) connected++;
  return {flushDraw:maxSuit>=4,wet:(maxSuit>=3||connected>=3),paired:pairs>0};
}

function getStat(player) {
  if(!memory.players[player]) memory.players[player]={hands:0,vpipHands:0,pfrHands:0,decisions:0,folds:0,calls:0,raises:0};
  return memory.players[player];
}

function updateMemory(view) {
  var key=String(view.rotation)+":"+String(view.hand);
  if(key!==memory.handKey) {
    memory.handKey=key;memory.actionCount=0;memory.flags={};
    for(var p=0;p<view.players.length;p++) getStat(view.players[p].player).hands++;
  }
  if(view.actions.length<memory.actionCount) memory.actionCount=0;
  for(var i=memory.actionCount;i<view.actions.length;i++) {
    var a=view.actions[i],st=getStat(a.player),vp="v:"+a.player,pf="p:"+a.player;
    st.decisions++;
    if(a.street==="preflop"&&(a.type==="call"||a.type==="bet"||a.type==="raise")&&!memory.flags[vp]) {st.vpipHands++;memory.flags[vp]=true;}
    if(a.street==="preflop"&&(a.type==="bet"||a.type==="raise")&&!memory.flags[pf]) {st.pfrHands++;memory.flags[pf]=true;}
    if(a.type==="bet"||a.type==="raise") st.raises++;
    else if(a.type==="call") st.calls++;
    else if(a.type==="fold") st.folds++;
  }
  memory.actionCount=view.actions.length;
}

function tableAdjustment(view) {
  var loose=0,n=0;
  for(var p in memory.players) if(String(p)!==String(view.player)&&memory.players[p].hands>=4) {
    var st=memory.players[p];loose+=(st.vpipHands+2)/(st.hands+6);n++;
  }
  if(!n) return 0;
  var avg=loose/n;
  return avg>0.48?0.025:(avg<0.24?-0.02:0);
}

function targetAction(view,type,target) {
  if(!has(view.legal,type)) return null;
  if(type==="bet"||type==="raise") {
    if(!view.canRaise) return null;
    var lo=Math.max(1,view.minRaiseTo||1),hi=view.maxRaiseTo;
    target=Math.floor(clamp(target,lo,hi));
    return {type:type,to:target};
  }
  return {type:type};
}

function safePassive(view,allowCall) {
  if(view.toCall===0&&has(view.legal,"check")) return {type:"check"};
  if(allowCall&&has(view.legal,"call")) return {type:"call"};
  if(has(view.legal,"fold")) return {type:"fold"};
  if(has(view.legal,"check")) return {type:"check"};
  if(has(view.legal,"call")) return {type:"call"};
  if(has(view.legal,"allin")) return {type:"allin"};
  return {type:view.legal[0]};
}

function activeOpponents(view) {
  var out=[];for(var i=0;i<view.players.length;i++) if(view.players[i].player!==view.player&&(view.players[i].state==="in"||view.players[i].state==="allin")) out.push(view.players[i].player);
  return out;
}

function opponentRangeFloor(view,player) {
  var floor=0.10,raises=0;
  for(var i=0;i<view.actions.length;i++) if(String(view.actions[i].player)===String(player)) {
    var a=view.actions[i];
    if(a.street==="preflop"&&(a.type==="bet"||a.type==="raise")) {raises++;floor=Math.max(floor,raises>1?0.66:0.46);}
    else if(a.street==="preflop"&&a.type==="call") floor=Math.max(floor,0.27);
    else if(a.street!=="preflop"&&(a.type==="bet"||a.type==="raise")) floor=Math.max(floor,0.50);
  }
  var st=getStat(player),vp=(st.vpipHands+2)/(st.hands+6);
  return clamp(floor+(0.34-vp)*0.18,0.08,0.72);
}

function aggregateFoldEquity(view,fraction,opponents) {
  var all=1;
  for(var i=0;i<opponents.length;i++) {
    var st=getStat(opponents[i]),rate=(st.folds+2)/(st.decisions+7);
    rate=clamp(rate+(fraction-0.5)*0.18,0.10,0.68);all*=rate;
  }
  return clamp(all,0.02,0.72);
}

function preflopDecision(view) {
  var strength=preflopStrength(view.me.cards),code=handCode(view.me.cards),position=view.me.position,threshold=POSITION_OPEN[position]||0.60;
  threshold+=tableAdjustment(view);
  var raises=0,callers=0;
  for(var i=0;i<view.actions.length;i++) if(view.actions[i].street==="preflop") {
    if(view.actions[i].type==="raise"||view.actions[i].type==="bet") raises++;
    else if(view.actions[i].type==="call") callers++;
  }
  if(view.toCall===0) {
    if((rangeHas(OPEN_RANGES[position]||OPEN_RANGES.UTG,code)||strength>=threshold)&&view.canRaise) {
      var open=Math.max(view.level.bb*2.3,view.level.bb*2.3+callers*view.level.bb);
      var kind=has(view.legal,"raise")?"raise":"bet";
      return targetAction(view,kind,open)||safePassive(view,true);
    }
    return safePassive(view,false);
  }
  var potOdds=view.toCall/Math.max(1,view.pot+view.toCall);
  var valueRange=raises>1?FOURBET_VALUE:THREEBET_VALUE;
  if(rangeHas(valueRange,code)&&view.canRaise) {
    var base=Math.max(view.minRaiseTo,(view.me.bet+view.toCall)*3.2);
    return targetAction(view,"raise",base)||targetAction(view,"allin")||safePassive(view,true);
  }
  var rng=seededRandom(view);
  if(raises===1&&view.canRaise&&rangeHas(THREEBET_BLUFF,code)&&rng()<0.34)
    return targetAction(view,"raise",Math.max(view.minRaiseTo,(view.me.bet+view.toCall)*3.1))||safePassive(view,false);
  var defend=(position==="BTN"||position==="SB"||position==="BB")?DEFEND_LATE:DEFEND_EARLY;
  if(raises<=1&&rangeHas(defend,code)) return safePassive(view,true);
  if(strength>=threshold+0.10+raises*0.06&&strength>potOdds+0.22) return safePassive(view,true);
  return safePassive(view,false);
}

function postflopDecision(view) {
  var opponents=activeOpponents(view),floors=[],rng=seededRandom(view);
  for(var i=0;i<opponents.length;i++) floors.push(opponentRangeFloor(view,opponents[i]));
  if(!floors.length) floors=[0.10];
  var samples=sampleBudget(view.street,floors.length),equity=estimateEquity(view.me.cards,view.board,floors,samples,rng),tex=boardTexture(view.board,view.me.cards);
  var potOdds=view.toCall/Math.max(1,view.pot+view.toCall), stack=view.me.stack, spr=stack/Math.max(1,view.pot);
  var value=clamp(equity-(floors.length-1)*0.015,0,1),callEV=value*(view.pot+view.toCall)-view.toCall;
  if(view.toCall===0) {
    var betThreshold=tex.wet?0.68:0.63;
    if(view.canRaise&&value>=betThreshold) {
      var fraction=tex.wet?0.62:0.36;
      if(value>0.84||spr<1.05) fraction=0.82;
      return targetAction(view,has(view.legal,"bet")?"bet":"raise",view.me.bet+Math.max(view.level.bb,view.pot*fraction))||safePassive(view,false);
    }
    if(view.canRaise&&opponents.length===1&&!tex.wet&&aggregateFoldEquity(view,0.30,opponents)>0.42&&rng()<0.055)
      return targetAction(view,has(view.legal,"bet")?"bet":"raise",view.me.bet+view.pot*0.30)||safePassive(view,false);
    return safePassive(view,false);
  }
  if(value>0.82&&view.canRaise) {
    if(spr<0.80&&has(view.legal,"allin")) return {type:"allin"};
    return targetAction(view,"raise",Math.max(view.minRaiseTo,view.me.bet+view.toCall+view.pot*0.58))||safePassive(view,true);
  }
  if(callEV>=0&&value>=potOdds+0.035) return safePassive(view,true);
  return safePassive(view,false);
}

function decide(view) {
  updateMemory(view);
  if(view.street==="preflop") return preflopDecision(view);
  return postflopDecision(view);
}

function act(view) {
  try {
    if(!view||!view.me||!Array.isArray(view.legal)||view.legal.length===0) throw new Error("bad view");
    var action=decide(view);
    if(!action||!has(view.legal,action.type)) return safePassive(view,false);
    return action;
  } catch (e) {
    if(view&&Array.isArray(view.legal)&&view.legal.length) return safePassive(view,false);
    return {type:"fold"};
  }
}

if(typeof module!=="undefined"&&module.exports) module.exports={act:act,evaluate:evaluate,compareScore:compareScore,preflopStrength:preflopStrength,handCode:handCode,rangeHas:rangeHas,sampleBudget:sampleBudget};
