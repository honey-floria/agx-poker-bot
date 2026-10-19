/* AGX six-player neural policy. Generated weights are embedded below. */

var MODEL = __MODEL_JSON__;
var RANKS = "23456789TJQKA";
var RULES_VERSION = "rsi-poker-4.1";
var POSITIONS = ["BTN","SB","BB","UTG","HJ","CO"];

function rankValue(card) { return RANKS.indexOf(card.charAt(0))+2; }
function clamp(x,lo,hi) { return Math.max(lo,Math.min(hi,x)); }
function has(xs,x) { return xs.indexOf(x)>=0; }

function evaluate5(cards) {
  var counts={},suits={},values=[],i,r,s;
  for(i=0;i<5;i++) {
    r=rankValue(cards[i]);s=cards[i].charAt(1);
    counts[r]=(counts[r]||0)+1;suits[s]=(suits[s]||0)+1;values.push(r);
  }
  values.sort(function(a,b){return b-a;});
  var unique=[];
  for(i=0;i<values.length;i++) if(i===0||values[i]!==values[i-1]) unique.push(values[i]);
  if(unique.indexOf(14)>=0) unique.push(1);
  var straightHigh=0;
  for(i=0;i<=unique.length-5;i++) if(unique[i]-unique[i+4]===4) straightHigh=Math.max(straightHigh,unique[i]);
  var flush=false;for(s in suits) if(suits[s]===5) flush=true;
  var groups=[];for(r in counts) groups.push([counts[r],Number(r)]);
  groups.sort(function(a,b){return b[0]-a[0]||b[1]-a[1];});
  if(flush&&straightHigh)return[8,straightHigh];
  if(groups[0][0]===4)return[7,groups[0][1],groups[1][1]];
  if(groups[0][0]===3&&groups[1][0]===2)return[6,groups[0][1],groups[1][1]];
  if(flush)return[5].concat(values);
  if(straightHigh)return[4,straightHigh];
  if(groups[0][0]===3)return[3,groups[0][1],groups[1][1],groups[2][1]];
  if(groups[0][0]===2&&groups[1][0]===2)return[2,Math.max(groups[0][1],groups[1][1]),Math.min(groups[0][1],groups[1][1]),groups[2][1]];
  if(groups[0][0]===2)return[1,groups[0][1],groups[1][1],groups[2][1],groups[3][1]];
  return[0].concat(values);
}

function compareScore(a,b) {
  for(var i=0;i<Math.max(a.length,b.length);i++) {
    var x=a[i]||0,y=b[i]||0;if(x!==y)return x-y;
  }
  return 0;
}

function evaluate(cards) {
  if(cards.length<5)return[0];
  var best=null,n=cards.length;
  for(var a=0;a<n-4;a++)for(var b=a+1;b<n-3;b++)for(var c=b+1;c<n-2;c++)
    for(var d=c+1;d<n-1;d++)for(var e=d+1;e<n;e++) {
      var score=evaluate5([cards[a],cards[b],cards[c],cards[d],cards[e]]);
      if(best===null||compareScore(score,best)>0)best=score;
    }
  return best;
}

function texture(board,hole) {
  var cards=board.concat(hole),suits={},ranks={},values=[],i,r,s;
  for(i=0;i<cards.length;i++) {
    r=rankValue(cards[i]);s=cards[i].charAt(1);
    ranks[r]=(ranks[r]||0)+1;suits[s]=(suits[s]||0)+1;values.push(r);
  }
  var maxSuit=0,paired=false;
  for(s in suits)maxSuit=Math.max(maxSuit,suits[s]);
  for(r in ranks)if(ranks[r]>=2)paired=true;
  values.sort(function(a,b){return a-b;});
  var unique=[];for(i=0;i<values.length;i++)if(i===0||values[i]!==values[i-1])unique.push(values[i]);
  var connected=0;for(i=1;i<unique.length;i++)if(unique[i]-unique[i-1]<=2)connected++;
  return{flushDraw:maxSuit>=4,wet:maxSuit>=3||connected>=3,paired:paired};
}

function streetIndex(street) {
  return street==="preflop"?0:(street==="flop"?1:(street==="turn"?2:3));
}

function activeOpponents(view) {
  var count=0;
  for(var i=0;i<view.players.length;i++)
    if(view.players[i].player!==view.player&&(view.players[i].state==="in"||view.players[i].state==="allin"))count++;
  return Math.max(1,count);
}

function features(view) {
  var out=[],street=streetIndex(view.street),position=Math.max(0,POSITIONS.indexOf(view.me.position));
  var a=rankValue(view.me.cards[0]),b=rankValue(view.me.cards[1]),high=Math.max(a,b),low=Math.min(a,b);
  var info=texture(view.board,view.me.cards),category=view.board.length>=3?evaluate(view.me.cards.concat(view.board))[0]:0;
  var potOdds=view.toCall/Math.max(1,view.pot+view.toCall),spr=view.me.stack/Math.max(1,view.pot);
  var preflopRaises=0,streetRaises=0,callers=0,actions=view.actions||[];
  for(var i=0;i<actions.length;i++) {
    var action=actions[i];
    if(action.street==="preflop"&&(action.type==="raise"||action.type==="bet"))preflopRaises++;
    if(action.street===view.street&&(action.type==="raise"||action.type==="bet"))streetRaises++;
    if(action.street==="preflop"&&action.type==="call")callers++;
  }
  for(i=0;i<4;i++)out.push(street===i?1:0);
  for(i=0;i<6;i++)out.push(position===i?1:0);
  out.push(
    high/14,
    low/14,
    high===low?1:0,
    view.me.cards[0].charAt(1)===view.me.cards[1].charAt(1)?1:0,
    (high-low)/12,
    category/8,
    info.flushDraw?1:0,
    info.wet?1:0,
    info.paired?1:0,
    Math.min(1,view.pot/20000),
    Math.min(1,view.toCall/10000),
    Math.min(1,view.me.stack/10000),
    potOdds,
    Math.min(1,spr/10),
    activeOpponents(view)/5,
    Math.min(1,preflopRaises/4),
    Math.min(1,streetRaises/4),
    Math.min(1,callers/5),
    view.canRaise?1:0,
    view.toCall===0?1:0,
    Math.min(1,view.me.invested/10000),
    view.board.length?Math.max.apply(null,view.board.map(rankValue))/14:0
  );
  return out;
}

function predict(input) {
  var hidden1=[],hidden2=[],i,j,sum;
  for(i=0;i<MODEL.hidden1_size;i++) {
    sum=MODEL.b1[i];
    for(j=0;j<MODEL.input_size;j++)sum+=MODEL.w1[i][j]*input[j];
    hidden1.push(Math.max(0,sum));
  }
  for(i=0;i<MODEL.hidden2_size;i++) {
    sum=MODEL.b2[i];
    for(j=0;j<MODEL.hidden1_size;j++)sum+=MODEL.w2[i][j]*hidden1[j];
    hidden2.push(Math.max(0,sum));
  }
  var logits=[];
  for(i=0;i<MODEL.output_size;i++) {
    sum=MODEL.b3[i];
    for(j=0;j<MODEL.hidden2_size;j++)sum+=MODEL.w3[i][j]*hidden2[j];
    logits.push(sum);
  }
  var best=0;for(i=1;i<logits.length;i++)if(logits[i]>logits[best])best=i;
  return best;
}

function safePassive(view,allowCall) {
  if(view.toCall===0&&has(view.legal,"check"))return{type:"check"};
  if(allowCall&&has(view.legal,"call"))return{type:"call"};
  if(has(view.legal,"fold"))return{type:"fold"};
  if(has(view.legal,"check"))return{type:"check"};
  if(has(view.legal,"call"))return{type:"call"};
  if(has(view.legal,"allin"))return{type:"allin"};
  return{type:view.legal[0]};
}

function aggressive(view,fraction,big) {
  if(big&&view.me.stack/Math.max(1,view.pot)<0.85&&has(view.legal,"allin"))return{type:"allin"};
  var kind=has(view.legal,"bet")?"bet":(has(view.legal,"raise")?"raise":null);
  if(!kind||!view.canRaise)return safePassive(view,true);
  var minimum=Math.max(1,view.minRaiseTo||1),maximum=view.maxRaiseTo;
  var target=view.me.bet+Math.max(view.level.bb*2.3,view.pot*fraction);
  return{type:kind,to:Math.floor(clamp(target,minimum,maximum))};
}

function decide(view) {
  var label=predict(features(view));
  if(label===0)return safePassive(view,false);
  if(label===1)return safePassive(view,true);
  if(label===2)return aggressive(view,0.42,false);
  return aggressive(view,0.82,true);
}

function act(view) {
  try {
    if(!view||!view.me||!Array.isArray(view.legal)||view.legal.length===0)throw new Error("bad view");
    if(view.rules&&view.rules!==RULES_VERSION)return safePassive(view,false);
    var action=decide(view);
    if(!action||!has(view.legal,action.type))return safePassive(view,false);
    return action;
  } catch(e) {
    if(view&&Array.isArray(view.legal)&&view.legal.length)return safePassive(view,false);
    return{type:"fold"};
  }
}

if(typeof module!=="undefined"&&module.exports)module.exports={act:act,features:features,predict:predict,evaluate:evaluate};
