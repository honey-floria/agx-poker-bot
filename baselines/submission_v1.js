/* AGX six-player NLHE submission. QuickJS compatible, zero dependencies. */

var RANKS = "23456789TJQKA";
var SUITS = "cdhs";
var POSITION_OPEN = {UTG:0.64,HJ:0.59,CO:0.53,BTN:0.46,SB:0.50,BB:0.70};
var memory = { hand:-1, actionCount:0, players:{} };

function rankValue(card) { return RANKS.indexOf(card.charAt(0)) + 2; }
function suitValue(card) { return card.charAt(1); }
function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }
function has(xs, x) { return xs.indexOf(x) >= 0; }

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

function sampleWithoutReplacement(deck,n) {
  var out=[],copy=deck.slice(),i,j,t;
  for(i=0;i<n;i++) { j=i+Math.floor(Math.random()*(copy.length-i)); t=copy[i];copy[i]=copy[j];copy[j]=t;out.push(copy[i]); }
  return out;
}

function estimateEquity(hole,board,opponents,samples) {
  var deck=deckWithout(hole.concat(board)), need=5-board.length, wins=0,ties=0;
  opponents=clamp(opponents,1,5);
  for(var k=0;k<samples;k++) {
    var draw=sampleWithoutReplacement(deck,need+2*opponents), fullBoard=board.concat(draw.slice(0,need));
    var hero=evaluate(hole.concat(fullBoard)), bestCmp=0, tied=1;
    for(var o=0;o<opponents;o++) {
      var opp=evaluate([draw[need+2*o],draw[need+2*o+1]].concat(fullBoard));
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
  if(!memory.players[player]) memory.players[player]={seen:0,vpip:0,raises:0,aggressive:0};
  return memory.players[player];
}

function updateMemory(view) {
  if(view.hand!==memory.hand) { memory.hand=view.hand; memory.actionCount=0; for(var p in memory.players) memory.players[p].seen++; }
  for(var i=memory.actionCount;i<view.actions.length;i++) {
    var a=view.actions[i],st=getStat(a.player);
    if(a.street==="preflop"&&(a.type==="call"||a.type==="bet"||a.type==="raise")) st.vpip++;
    if(a.type==="bet"||a.type==="raise") {st.raises++;st.aggressive++;}
  }
  memory.actionCount=view.actions.length;
}

function tableAdjustment(view) {
  var loose=0,n=0;
  for(var p in memory.players) if(String(p)!==String(view.player)&&memory.players[p].seen>=4) {
    var st=memory.players[p];loose+=st.vpip/Math.max(1,st.seen);n++;
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
  var n=0;for(var i=0;i<view.players.length;i++) if(view.players[i].player!==view.player&&view.players[i].state==="in") n++;
  return Math.max(1,n);
}

function preflopDecision(view) {
  var strength=preflopStrength(view.me.cards), threshold=POSITION_OPEN[view.me.position]||0.60;
  threshold+=tableAdjustment(view);
  var raises=0,callers=0;
  for(var i=0;i<view.actions.length;i++) if(view.actions[i].street==="preflop") {
    if(view.actions[i].type==="raise"||view.actions[i].type==="bet") raises++;
    else if(view.actions[i].type==="call") callers++;
  }
  if(view.toCall===0) {
    if(strength>=threshold&&view.canRaise) {
      var open=Math.max(view.level.bb*2.3,view.level.bb*2.3+callers*view.level.bb);
      var kind=has(view.legal,"raise")?"raise":"bet";
      return targetAction(view,kind,open)||safePassive(view,true);
    }
    return safePassive(view,false);
  }
  var potOdds=view.toCall/Math.max(1,view.pot+view.toCall);
  if(strength>=0.84&&view.canRaise) {
    var base=Math.max(view.minRaiseTo,(view.me.bet+view.toCall)*3.2);
    return targetAction(view,"raise",base)||targetAction(view,"allin")||safePassive(view,true);
  }
  if(strength>=threshold+0.08+raises*0.055||strength>potOdds+0.31) return safePassive(view,true);
  return safePassive(view,false);
}

function postflopDecision(view) {
  var opponents=activeOpponents(view), samples=view.street==="river"?36:(view.street==="turn"?32:24);
  var equity=estimateEquity(view.me.cards,view.board,opponents,samples), tex=boardTexture(view.board,view.me.cards);
  var potOdds=view.toCall/Math.max(1,view.pot+view.toCall), stack=view.me.stack, spr=stack/Math.max(1,view.pot);
  var multiPenalty=(opponents-1)*0.035, value=equity-multiPenalty;
  if(view.toCall===0) {
    if(view.canRaise&&value>(tex.wet?0.62:0.57)) {
      var frac=tex.wet?0.68:0.34;
      if(value>0.82||spr<1.2) frac=0.85;
      var kind=has(view.legal,"bet")?"bet":"raise";
      return targetAction(view,kind,view.me.bet+Math.max(view.level.bb,view.pot*frac))||safePassive(view,false);
    }
    if(view.canRaise&&opponents===1&&!tex.wet&&value>0.40&&Math.random()<0.13)
      return targetAction(view,has(view.legal,"bet")?"bet":"raise",view.me.bet+view.pot*0.30)||safePassive(view,false);
    return safePassive(view,false);
  }
  if(value>0.78&&view.canRaise) {
    if(spr<1.0&&has(view.legal,"allin")) return {type:"allin"};
    return targetAction(view,"raise",Math.max(view.minRaiseTo,view.me.bet+view.toCall+view.pot*0.62))||safePassive(view,true);
  }
  var drawBonus=(tex.flushDraw?0.025:0)+(tex.wet?0.015:0);
  if(value+drawBonus>=potOdds+0.055) return safePassive(view,true);
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

if(typeof module!=="undefined"&&module.exports) module.exports={act:act,evaluate:evaluate,compareScore:compareScore,preflopStrength:preflopStrength};

