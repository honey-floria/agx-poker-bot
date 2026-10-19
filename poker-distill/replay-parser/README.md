# 回放解析器

`parse_replay.py` 将完整、有权限的比赛轨迹逐动作送入精确引擎，并输出统一 JSONL 决策记录。解析过程会验证动作顺序、合法动作、下注 `to` 的本街累计语义和每手最终净额；参与者 ID 在同一局内稳定匿名化。

输入中的每手包含 `button`、六个 `{seat, player, hole}` 和按顺序排列的 `events`。动作事件格式为 `{"type":"action","seat":2,"action":"raise","to":300}`，发牌事件分别使用 `flop`、`turn`、`river` 及 `cards`。

```bash
python3 poker-distill/replay-parser/parse_replay.py replay.out decisions.jsonl --report report.out
```

公开回放不保证包含每个决策者当时的私有底牌。解析器不会猜测或伪造底牌；缺少完整底牌轨迹时会明确失败。需要使用本人有权限导出的完整轨迹完成私有决策数据构建。

已知公开回放 URL 可批量保存并生成 SHA-256 manifest：

```bash
python3 poker-distill/replay-parser/download_replays.py \
  --url-file replay_urls.txt \
  --output-dir poker-distill/data/raw-replays
```

下载器仅接受 `https://agx.cool` 的显式公开 URL，不读取 Cookie、API 密钥或私有轨迹。
