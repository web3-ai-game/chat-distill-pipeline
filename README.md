# Cloud Distill ☁️🧪

从 OneDrive / Google Drive / 本地目录 拉取文件 → 解析 → AI蒸馏 → 脱敏 → 向量种子导出（可入库）

## Quick Start

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 运行完整流水线（默认读取 config.yaml 里的 sources.local_dirs）
python main.py
```

### TXT -> 向量库模式（xAI Grok）

默认配置已设置：
- `sources.local_dirs = ../TXT`
- `distill.provider = grok`
- `distill.grok.model = grok-4-0709`
- `distill.temperature = 0.1`（低温剪切）
- `distill.budget_usd = 10`
- `export.vector.enabled = true`

直接执行：

```bash
python main.py run
```

仅跑解析（检查输入规模）：

```bash
python main.py parse ../TXT
```

产物：
- `output/vectors/persona_knowledge.jsonl`
- `output/vectors/tech_stack_knowledge.jsonl`
- `output/vectors/timeline_knowledge.jsonl`
- `output/vectors/all_knowledge.jsonl`
- `output/vectors/manifest.json`

## 流程

```
OneDrive ─┐
           ├─→ 本地 raw/ ─→ 解析 ─→ 蒸馏 ─→ 脱敏 ─→ output/
Google ───┘                                          ├─→ GitHub
                                                     ├─→ Notion
                                                     └─→ 本地 MD
```

## 目录结构

```
cloud-distill/
├── raw/                  # 拉取的原始文件 (gitignored)
│   ├── onedrive/
│   └── gdrive/
├── parsed/               # 解析后的纯文本 JSON
├── distilled/            # 蒸馏后的摘要
├── output/               # 最终输出
│   ├── markdown/         # MD 文档包 (可选)
│   └── vectors/          # 向量库种子 JSONL
├── scripts/
│   ├── setup-remotes.sh  # rclone 配置
│   └── pull.sh           # 拉取文件
├── src/
│   ├── parser.py         # 文档解析 (DOCX/PDF/PPT/XLSX/图片)
│   ├── distiller.py      # AI 蒸馏 (Gemini/Grok)
│   ├── sanitizer.py      # 脱敏处理
│   └── exporter.py       # 导出 (Notion/GitHub/MD)
├── config.yaml           # 统一配置
├── main.py               # 主流水线
└── requirements.txt
```

## 脱敏规则

- 电话号码 → `[PHONE]`
- 邮箱地址 → `[EMAIL]`
- 身份证号 → `[ID_NUMBER]`
- 银行卡号 → `[CARD_NUMBER]`
- 物理地址 → `[ADDRESS]`
- 人名 (可配置白名单) → `[PERSON]`

## 环境变量

```bash
# .env
GROK_API_KEY=xai-...           # xAI Grok (蒸馏用)
# 或使用 XAI_API_KEY（会自动兼容到 GROK_API_KEY）
GEMINI_API_KEY=AIza...         # Google Gemini (备用蒸馏)
NOTION_API_KEY=ntn_...         # Notion Integration Token
GITHUB_TOKEN=ghp_...           # GitHub PAT
```
