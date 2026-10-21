/* Mixed loose/aggressive AGX baseline for offline paired evaluation. */
function nrMixedRaise(view,fraction){
  var target=Math.floor(Math.max(view.minRaiseTo,Math.max(view.me.bet,view.me.bet+view.toCall)+view.pot*fraction));
  target=Math.min(view.maxRaiseTo,target);
  return {type:view.legal.indexOf("raise")>=0?"raise":"bet",to:target};
}
function act(view){
  var x=Math.random();
  if(view.canRaise&&x<.18)return nrMixedRaise(view,x<.04?1.1:.45);
  if(view.toCall===0)return x<.70||!view.canRaise?{type:"check"}:nrMixedRaise(view,.35);
  if(x<.67)return {type:"call"};
  return {type:"fold"};
}
