#!/usr/bin/env python3
"""Download explicitly supplied public replay URLs without credentials."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description="下载公开 AGX 回放到 raw-replays")
    parser.add_argument("--url", action="append", default=[], help="可重复提供公开回放 JSON URL")
    parser.add_argument("--url-file", type=Path, help="每行一个公开回放 URL")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    urls = list(args.url)
    if args.url_file:
        urls.extend(line.strip() for line in args.url_file.read_text(encoding="utf-8").splitlines() if line.strip())
    if not urls:
        raise SystemExit("至少提供一个 --url 或 --url-file")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, url in enumerate(urls, start=1):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "agx.cool":
            raise SystemExit(f"只允许公开 HTTPS agx.cool URL：{url}")
        request = Request(url, headers={"User-Agent": "agx-poker-bot-replay-fetcher/1"})
        with urlopen(request, timeout=args.timeout) as response:
            payload = response.read()
        json.loads(payload.decode("utf-8"))
        digest = hashlib.sha256(payload).hexdigest()
        target = args.output_dir / f"replay_{index:04d}_{digest[:12]}.json"
        target.write_bytes(payload)
        manifest.append({"url": url, "file": target.name, "bytes": len(payload), "sha256": digest})
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"downloaded {len(manifest)} public replays")


if __name__ == "__main__":
    main()
