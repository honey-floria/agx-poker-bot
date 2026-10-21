/* Deterministic AGX calling-station baseline for offline paired evaluation. */
function act(view) {
  if (view.legal.indexOf("check") >= 0) return {type:"check"};
  if (view.legal.indexOf("call") >= 0) return {type:"call"};
  return {type:view.legal[0]};
}
