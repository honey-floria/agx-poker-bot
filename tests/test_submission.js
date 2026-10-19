"use strict";
const assert = require("assert");
const bot = require("../submission.js");

function baseView(overrides={}) {
  const players=Array.from({length:6},(_,i)=>({seat:i,player:i,stack:i===0?9950:9900,bet:i===0?50:100,invested:i===0?50:100,state:"in",position:["SB","BB","UTG","HJ","CO","BTN"][i]}));
  return Object.assign({rules:"poker-v4",hand:1,rotation:0,rotationHand:1,handsPerRotation:40,seat:0,player:0,street:"preflop",board:[],button:5,pot:150,level:{sb:50,bb:100},me:{seat:0,player:0,cards:["As","Ks"],stack:9950,bet:50,invested:50,position:"SB"},players,actions:[],recent:[],toCall:50,minRaiseTo:200,maxRaiseTo:10000,canRaise:true,legal:["fold","call","raise","allin"],startingStack:10000},overrides);
}

assert(bot.compareScore(bot.evaluate(["As","Ks","Qs","Js","Ts","2c","3d"]),bot.evaluate(["Ah","Ad","Ac","As","2c","3d","4h"]))>0);
assert(bot.compareScore(bot.evaluate(["Ah","2d","3c","4s","5h","Kd","Qc"]),bot.evaluate(["Kh","Kd","8c","7s","5d","3h","2c"]))>0);
assert(bot.preflopStrength(["As","Ah"])>bot.preflopStrength(["7c","2d"]));
assert.strictEqual(bot.handCode(["As","Ks"]),"AKs");
assert.strictEqual(bot.handCode(["Ah","Kd"]),"AKo");
assert.strictEqual(bot.handCode(["Tc","Td"]),"TT");
assert.strictEqual(bot.sampleBudget("flop",5),19);
assert.strictEqual(bot.sampleBudget("river",1),48);

const premium=baseView();
premium.me.cards=["As","Ah"];
premium.actions=[{player:2,street:"preflop",type:"raise"}];
premium.toCall=250;premium.pot=450;premium.minRaiseTo=700;
assert.strictEqual(bot.act(premium).type,"raise");

const trash=baseView();
trash.me.cards=["7c","2d"];trash.me.position="UTG";
trash.actions=[{player:2,street:"preflop",type:"raise"}];
trash.toCall=250;trash.pot=450;trash.minRaiseTo=700;
assert.strictEqual(bot.act(trash).type,"fold");

const nuts=baseView({street:"river",board:["Qs","Js","Ts","2d","3c"],pot:1800,toCall:0,minRaiseTo:100,maxRaiseTo:9950,legal:["check","bet","allin"]});
nuts.me.cards=["As","Ks"];
assert(["bet","allin"].includes(bot.act(nuts).type));

const started=Date.now();
for(let i=0;i<300;i++) {
  const v=baseView();
  if(i%3===1) Object.assign(v,{street:"flop",board:["Qh","Jh","2c"],pot:550,toCall:0,minRaiseTo:100,maxRaiseTo:9950,legal:["check","bet","allin"]});
  if(i%3===2) Object.assign(v,{street:"river",board:["Qh","Jh","2c","7s","3d"],pot:1400,toCall:400,minRaiseTo:1200,maxRaiseTo:9550,legal:["fold","call","raise","allin"]});
  const a=bot.act(v);
  assert(a&&typeof a==="object");
  assert(v.legal.includes(a.type),JSON.stringify(a));
  if(a.type==="raise"||a.type==="bet") assert(Number.isInteger(a.to)&&a.to>=v.minRaiseTo&&a.to<=v.maxRaiseTo);
}
const elapsed=Date.now()-started;
assert(elapsed<5000,`decision smoke test too slow: ${elapsed}ms`);

console.log(`submission tests: ok (${elapsed}ms for 300 decisions)`);
