/* Tight-aggressive AGX baseline for offline paired evaluation. */
var NR_RANKS="23456789TJQKA";
function nrRank(card){return NR_RANKS.indexOf(card.charAt(0))+2;}
function nrPreflop(cards){
  var a=nrRank(cards[0]),b=nrRank(cards[1]),hi=Math.max(a,b),lo=Math.min(a,b),s=0;
  if(a===b)return Math.min(1,.52+(hi-2)*.037);
  s=(hi-2)/12*.46+(lo-2)/12*.20;
  if(cards[0].charAt(1)===cards[1].charAt(1))s+=.075;
  var gap=hi-lo;s+=gap===1?.07:gap===2?.035:gap>=5?-.055:0;
  if(hi===14)s+=.10;if(hi>=12&&lo>=10)s+=.08;
  return Math.max(0,Math.min(1,s));
}
function nrMade(cards){
  var count={},suits={},mask={},i,r,s;
  for(i=0;i<cards.length;i++){r=nrRank(cards[i]);s=cards[i].charAt(1);count[r]=(count[r]||0)+1;suits[s]=(suits[s]||0)+1;mask[r]=1;}
  var pairs=0,trips=0,quads=0;for(r in count){if(count[r]===2)pairs++;if(count[r]===3)trips++;if(count[r]===4)quads++;}
  var flush=false;for(s in suits)if(suits[s]>=5)flush=true;
  var run=0,straight=false;for(i=2;i<=14;i++){run=mask[i]?run+1:0;if(run>=5)straight=true;}if(mask[14]&&mask[2]&&mask[3]&&mask[4]&&mask[5])straight=true;
  if(quads)return 1;if(trips&&pairs)return .96;if(flush)return .88;if(straight)return .82;if(trips)return .72;if(pairs>=2)return .62;if(pairs)return .48;
  return nrPreflop(cards.slice(0,2))*.42;
}
function nrRaise(view,fraction){
  var target=Math.floor(Math.max(view.minRaiseTo,Math.max(view.me.bet,view.me.bet+view.toCall)+view.pot*fraction));
  target=Math.min(view.maxRaiseTo,target);
  return {type:view.legal.indexOf("raise")>=0?"raise":"bet",to:target};
}
function act(view){
  var score=view.street==="preflop"?nrPreflop(view.me.cards):nrMade(view.me.cards.concat(view.board));
  var pressure=view.toCall/Math.max(100,view.pot+view.toCall);
  if(view.canRaise&&score>.78+pressure*.18)return nrRaise(view,score>.93?.9:.55);
  if(view.toCall===0)return {type:"check"};
  if(score>.48+pressure*.38)return {type:"call"};
  return {type:"fold"};
}
