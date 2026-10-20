/* AGX six-player hierarchical replay behavior clone. */

var MODEL=__MODEL_JSON__;
var RANKS="23456789TJQKA";
var STREETS=["preflop","flop","turn","river"];
var POSITIONS=["BTN","SB","BB","UTG","HJ","CO"];
var FAMILY=["fold","check","call","raise","allin"];
var SIZES=[0.33,0.50,0.75,1.00,1.50,2.00];
var COMPETITION_RULES_VERSION="rsi-poker-4.1";
var OBSERVATION_RULES="rsi-poker-4.0";

function clamp(x,lo,hi){return Math.max(lo,Math.min(hi,Number(x)||0));}
function has(xs,x){return xs.indexOf(x)>=0;}
function oneHot(out,value,values){for(var i=0;i<values.length;i++)out.push(value===values[i]?1:0);}
function cardFeatures(out,card,suits){
  if(!card){for(var z=0;z<6;z++)out.push(0);return;}
  var rank=RANKS.indexOf(card.charAt(0))+2,suit=suits[card.charAt(1)];
  out.push(1,rank/14);for(var i=0;i<4;i++)out.push(suit===i?1:0);
}
function legalMask(view){
  return [has(view.legal,"fold"),has(view.legal,"check"),has(view.legal,"call"),has(view.legal,"raise")||has(view.legal,"bet"),has(view.legal,"allin")];
}

function features(view){
  var out=[],hole=view.me.cards||[],board=view.board||[],cards=hole.concat(board).slice(0,7),suits={},nextSuit=0,i,j,item;
  for(i=0;i<cards.length;i++)if(suits[cards[i].charAt(1)]===undefined)suits[cards[i].charAt(1)]=nextSuit++;
  for(i=0;i<7;i++)cardFeatures(out,i<cards.length?cards[i]:null,suits);
  oneHot(out,view.street,STREETS);oneHot(out,view.me.position,POSITIONS);

  var pot=Math.max(0,Number(view.pot)||0),stack=Math.max(0,Number(view.me.stack)||0),toCall=Math.max(0,Number(view.toCall)||0);
  var meBet=Math.max(0,Number(view.me.bet)||0),invested=Math.max(0,Number(view.me.invested)||0);
  var minimum=Math.max(0,Number(view.minRaiseTo)||0),maximum=Math.max(0,Number(view.maxRaiseTo)||0);
  var players=view.players||[],active=0,allin=0,folded=0,maxOpponent=0,heroSeat=Number(view.me.seat);
  for(i=0;i<players.length;i++){
    item=players[i];
    if(item.state==="in"||item.state==="allin"){
      active++;if(Number(item.seat)!==heroSeat)maxOpponent=Math.max(maxOpponent,Math.max(0,Number(item.stack)||0));
    }
    if(item.state==="allin")allin++;if(item.state==="folded")folded++;
  }
  var effective=Math.min(stack,maxOpponent||stack);
  out.push(
    clamp(pot/60000,0,1),clamp(pot/10000,0,1),clamp(stack/10000,0,1),
    clamp(toCall/10000,0,1),clamp(meBet/10000,0,1),clamp(invested/10000,0,1),
    clamp(minimum/10000,0,1),clamp(maximum/10000,0,1),
    clamp(toCall/Math.max(1,pot+toCall),0,1),clamp(stack/Math.max(1,pot)/20,0,1),
    clamp(effective/10000,0,1),clamp(effective/Math.max(1,pot)/20,0,1),
    clamp(active/6,0,1),clamp(allin/6,0,1),clamp(folded/6,0,1),view.canRaise?1:0
  );

  var relative={};
  for(i=0;i<players.length;i++)relative[((Number(players[i].seat)-heroSeat)%6+6)%6]=players[i];
  for(i=0;i<6;i++){
    item=relative[i]||{};
    out.push(
      clamp((Number(item.stack)||0)/10000,0,1),clamp((Number(item.bet)||0)/10000,0,1),
      clamp((Number(item.invested)||0)/10000,0,1),item.state==="in"?1:0,item.state==="folded"?1:0,item.state==="allin"?1:0
    );
  }

  var groups=["fold","check","call","aggressive"],counts={},history=view.actions||[],action,group,key;
  for(i=0;i<STREETS.length;i++)for(j=0;j<groups.length;j++)counts[STREETS[i]+":"+groups[j]]=0;
  for(i=0;i<history.length;i++){
    action=history[i];group=(action.type==="bet"||action.type==="raise"||action.type==="allin")?"aggressive":action.type;
    key=action.street+":"+group;if(counts[key]!==undefined)counts[key]++;
  }
  for(i=0;i<STREETS.length;i++)for(j=0;j<groups.length;j++)out.push(clamp(counts[STREETS[i]+":"+groups[j]]/6,0,1));

  var used=Math.min(6,history.length),padding=6-used,start=history.length-used;
  for(i=0;i<6;i++){
    if(i<padding){for(j=0;j<17;j++)out.push(0);continue;}
    action=history[start+i-padding];
    var actor=((Number(action.seat)-heroSeat)%6+6)%6;
    out.push(1);oneHot(out,action.street,STREETS);
    for(j=0;j<6;j++)out.push(actor===j?1:0);
    out.push(action.type==="fold"?1:0,action.type==="check"?1:0,action.type==="call"?1:0,(action.type==="bet"||action.type==="raise"||action.type==="allin")?1:0,clamp((Number(action.amount)||0)/Math.max(1,pot),0,1),clamp((Number(action.to)||0)/10000,0,1));
  }
  var legal=legalMask(view);for(i=0;i<legal.length;i++)out.push(legal[i]?1:0);
  while(out.length<MODEL.input_size)out.push(0);
  if(out.length!==MODEL.input_size)throw new Error("feature size mismatch");
  return out;
}

function dense(input,weights,bias,relu){
  var output=[],i,j,sum;
  for(i=0;i<weights.length;i++){
    sum=bias[i];for(j=0;j<input.length;j++)sum+=weights[i][j]*input[j];
    output.push(relu?Math.max(0,sum):sum);
  }
  return output;
}
function predict(input,legal){
  var hidden1=dense(input,MODEL.trunk_w1,MODEL.trunk_b1,true);
  var hidden2=dense(hidden1,MODEL.trunk_w2,MODEL.trunk_b2,true);
  var family=dense(hidden2,MODEL.family_w,MODEL.family_b,false),sizes=dense(hidden2,MODEL.size_w,MODEL.size_b,false),i;
  var familyIndex=-1;
  for(i=0;i<family.length;i++)if(legal[i]&&(familyIndex<0||family[i]>family[familyIndex]))familyIndex=i;
  if(familyIndex<0)throw new Error("no legal family");
  var sizeIndex=0;for(i=1;i<sizes.length;i++)if(sizes[i]>sizes[sizeIndex])sizeIndex=i;
  return{family:familyIndex,size:sizeIndex,familyLogits:family,sizeLogits:sizes};
}
function safePassive(view){
  if(view.toCall===0&&has(view.legal,"check"))return{type:"check"};
  if(has(view.legal,"fold"))return{type:"fold"};
  if(has(view.legal,"call"))return{type:"call"};
  if(has(view.legal,"allin"))return{type:"allin"};
  return{type:view.legal[0]};
}
function decide(view){
  var prediction=predict(features(view),legalMask(view)),family=FAMILY[prediction.family];
  if(family!=="raise")return{type:family};
  var kind=has(view.legal,"bet")?"bet":(has(view.legal,"raise")?"raise":null);
  if(!kind||!view.canRaise)return safePassive(view);
  var target=Number(view.me.bet)+SIZES[prediction.size]*(Number(view.pot)+Number(view.toCall));
  target=Math.floor(clamp(target,Math.max(1,Number(view.minRaiseTo)||1),Number(view.maxRaiseTo)));
  if(target>=Number(view.maxRaiseTo)&&has(view.legal,"allin"))return{type:"allin"};
  return{type:kind,to:target};
}
function act(view){
  try{
    if(!view||!view.me||!Array.isArray(view.legal)||!view.legal.length)throw new Error("bad view");
    if(view.rules&&view.rules!==OBSERVATION_RULES)return safePassive(view);
    var action=decide(view);if(!action||!has(view.legal,action.type))return safePassive(view);return action;
  }catch(error){return view&&view.legal&&view.legal.length?safePassive(view):{type:"fold"};}
}

if(typeof module!=="undefined"&&module.exports)module.exports={act:act,decide:decide,features:features,predict:predict,legalMask:legalMask};
