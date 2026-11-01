# chat-distill-pipeline

[繁體中文](#zh) · [English](#en)

<a id="zh"></a>

## 繁體中文

把本機匯出的文字整理成 Markdown。解析、脫敏、蒸餾、匯出分成四步。公開副本用不含私人對話的樣例就能跑。

### 免設定演示

```bash
python3 main.py demo
# or
python3 main.py --demo
```

樣例在 `demo_sample.txt`。主機名是 `DO SGP1`。位址是 RFC 5737。不讀 API key，不連向量庫，不拉雲端硬碟。

完整流程需要你自己的匯出檔與 `.env`。不要把聊天紀錄提交進 git。PDF 解析使用 `pypdf`。

<a id="en"></a>

## English

Turn a local text export into Markdown. Parse, sanitize, distill, and export are separate steps. The public copy runs on a sample that is not a private chat.

### Demo without configuration

```bash
python3 main.py demo
# or
python3 main.py --demo
```

The sample is `demo_sample.txt`. The host label is `DO SGP1`. Addresses are RFC 5737. The demo reads no API key, no vector database, and no cloud drive.

The full pipeline needs your own export and a local `.env`. Do not commit chat logs. PDF parsing uses `pypdf`.

## License

MIT. See [LICENSE](LICENSE) and [SECURITY.md](SECURITY.md).
