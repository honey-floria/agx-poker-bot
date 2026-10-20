function act(view) {
  if (view.rules !== "rsi-poker-4.0") throw new Error("unexpected observation rules");
  if (view.toCall === 0 && view.legal.indexOf("check") >= 0) return { type: "check" };
  if (view.legal.indexOf("fold") >= 0) return { type: "fold" };
  return { type: view.legal[0] };
}
