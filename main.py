#!/usr/bin/env python3
"""
Cloud Distill - Main Pipeline
Pull/Local Source -> Parse -> Distill -> Sanitize -> Export
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
try:
    import yaml  # type: ignore
except ModuleNotFoundError:
    yaml = None

from src.parser import DocumentParser
from src.distiller import Distiller
from src.sanitizer import Sanitizer
from src.exporter import (
    MarkdownExporter,
    NotionExporter,
    GitHubExporter,
    VectorExporter,
)


BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw"
PARSED_DIR = BASE_DIR / "parsed"
DISTILLED_DIR = BASE_DIR / "distilled"
OUTPUT_DIR = BASE_DIR / "output"


def load_env_chain() -> list[Path]:
    """Load env files in priority order without overriding existing process env."""
    candidates = [
        BASE_DIR / ".env",
        BASE_DIR.parent / "deepweay-me" / ".env",
        BASE_DIR.parent / "deepweay-me" / ".env.local",
        BASE_DIR.parent / "deepweay-me" / ".env.production",
    ]
    loaded = []

    for env_file in candidates:
        if env_file.exists():
            load_dotenv(env_file, override=False)
            loaded.append(env_file)

    # xAI compatibility: map XAI_API_KEY -> GROK_API_KEY if needed.
    if os.getenv("XAI_API_KEY") and not os.getenv("GROK_API_KEY"):
        os.environ["GROK_API_KEY"] = os.getenv("XAI_API_KEY", "")

    return loaded


def load_config(config_path: str | None = None) -> dict:
    """Load YAML config."""
    if config_path:
        path = Path(config_path).expanduser()
    else:
        if yaml is None and (BASE_DIR / "config.json").exists():
            path = BASE_DIR / "config.json"
        else:
            path = BASE_DIR / "config.yaml"
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()

    with open(path, "r", encoding="utf-8") as f:
        if path.suffix.lower() == ".json":
            cfg = json.load(f) or {}
        elif yaml is not None:
            cfg = yaml.safe_load(f) or {}
        else:
            raise RuntimeError(
                "PyYAML is not installed and config is YAML. "
                "Use --config config.json or install pyyaml."
            )
    cfg["_config_path"] = str(path)
    return cfg


def _safe_source_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_")
    return safe or "source"


def resolve_sources(config: dict, source_args: list[str] | None = None) -> list[tuple[str, Path]]:
    """
    Resolve source directories.

    Priority:
    1) CLI args: local dir path or raw source alias name.
    2) config.sources.local_dirs
    3) default raw/onedrive + raw/gdrive
    """
    resolved: list[tuple[str, Path]] = []
    seen_paths: set[str] = set()

    def add_source(label: str, path: Path):
        key = str(path.resolve())
        if key in seen_paths:
            return
        seen_paths.add(key)
        resolved.append((label, path.resolve()))

    if source_args:
        for item in source_args:
            candidate = Path(item).expanduser()
            if not candidate.is_absolute():
                candidate = (Path.cwd() / candidate).resolve()

            if candidate.exists() and candidate.is_dir():
                add_source(_safe_source_name(candidate.name), candidate)
                continue

            raw_candidate = RAW_DIR / item
            if raw_candidate.exists() and raw_candidate.is_dir():
                add_source(_safe_source_name(item), raw_candidate)

        return resolved

    source_cfg = config.get("sources", {})
    local_dirs = source_cfg.get("local_dirs", []) or []

    for i, item in enumerate(local_dirs, start=1):
        p = Path(item).expanduser()
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        if p.exists() and p.is_dir():
            label = _safe_source_name(p.name or f"local_{i}")
            add_source(label, p)

    if resolved:
        return resolved

    # Fallback to legacy raw sources
    for source_name in ("onedrive", "gdrive"):
        p = RAW_DIR / source_name
        if p.exists() and p.is_dir():
            add_source(source_name, p)

    return resolved


def step_parse(sources: list[tuple[str, Path]]) -> list[dict]:
    """Step 1: Parse source files into text."""
    print("\n" + "=" * 60)
    print("📄 STEP 1: PARSE")
    print("=" * 60)

    all_entries = []
    parser = DocumentParser()

    for source_name, src_dir in sources:
        if not src_dir.exists():
            print(f"⏭️  Skipping {source_name} ({src_dir}) - not found")
            continue

        output_path = PARSED_DIR / f"{source_name}.json"
        entries = parser.parse_directory(src_dir, output_path)
        all_entries.extend(entries)

    return all_entries


def step_distill(entries: list[dict], config: dict) -> list[dict]:
    """Step 2: AI distillation."""
    print("\n" + "=" * 60)
    print("🧪 STEP 2: DISTILL")
    print("=" * 60)

    distill_config = config.get("distill", {})
    provider = distill_config.get("provider", "gemini")
    delay = float(distill_config.get("delay_seconds", 1))
    min_len = int(distill_config.get("min_content_length", 100))
    budget_usd = distill_config.get("budget_usd")
    max_documents = distill_config.get("max_documents")

    eligible = [e for e in entries if e.get("content") and len(e["content"]) >= min_len]
    print(f"Eligible for distillation: {len(eligible)}/{len(entries)}")

    distiller = Distiller(provider=provider, config=distill_config)
    output_path = DISTILLED_DIR / "distilled.json"
    results = distiller.distill_batch(
        eligible,
        output_path,
        delay=delay,
        budget_usd=budget_usd,
        max_documents=max_documents,
    )
    return results


def step_sanitize(entries: list[dict], config: dict) -> list[dict]:
    """Step 3: Sanitize sensitive data."""
    print("\n" + "=" * 60)
    print("🔒 STEP 3: SANITIZE")
    print("=" * 60)

    sanitize_config = config.get("sanitize", {})
    if not sanitize_config.get("enabled", True):
        print("Sanitization disabled in config.")
        return entries

    sanitizer = Sanitizer(config=sanitize_config)
    sanitized = []

    for entry in entries:
        s = sanitizer.sanitize_entry(entry)
        sanitized.append(s)

    sanitizer.print_stats()

    output_path = DISTILLED_DIR / "sanitized.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sanitized, f, indent=2, ensure_ascii=False)

    print(f"✅ Sanitized -> {output_path}")
    return sanitized


def step_export(entries: list[dict], config: dict):
    """Step 4: Export to Markdown, vectors, Notion, GitHub."""
    print("\n" + "=" * 60)
    print("📤 STEP 4: EXPORT")
    print("=" * 60)

    export_config = config.get("export", {})

    if export_config.get("markdown", {}).get("enabled", True):
        print("\n--- Markdown Export ---")
        md_dir = export_config.get("markdown", {}).get("output_dir", "output/markdown")
        exporter = MarkdownExporter(output_dir=md_dir)
        exporter.export(entries)

    if export_config.get("vector", {}).get("enabled", False):
        print("\n--- Vector Seed Export ---")
        vec_dir = export_config.get("vector", {}).get("output_dir", "output/vectors")
        vector_exporter = VectorExporter(output_dir=vec_dir)
        vector_exporter.export(entries)

    if export_config.get("notion", {}).get("enabled", False):
        notion_key = os.getenv("NOTION_API_KEY")
        parent_id = (
            export_config.get("notion", {}).get("parent_page_id")
            or os.getenv("NOTION_PARENT_PAGE_ID")
        )

        if notion_key and parent_id:
            print("\n--- Notion Export ---")
            notion = NotionExporter(api_key=notion_key, parent_page_id=parent_id)
            try:
                db_id = notion.create_database("Cloud Distill KB")
                notion.export_batch(db_id, entries)
            except Exception as e:
                print(f"❌ Notion export failed: {e}")
        else:
            print("\n⏭️  Notion export skipped (no API key or parent page ID)")

    if export_config.get("github", {}).get("enabled", False):
        print("\n--- GitHub Export ---")
        repo = export_config.get("github", {}).get("repo", "gcp-cloud-distill")
        private = export_config.get("github", {}).get("private", True)
        gh = GitHubExporter(repo_name=repo, private=private)
        md_dir = export_config.get("markdown", {}).get("output_dir", "output/markdown")
        gh.init_and_push(Path(md_dir))


def run_full_pipeline(config: dict, source_args: list[str] | None = None):
    sources = resolve_sources(config, source_args=source_args)
    if not sources:
        print("❌ No sources found.")
        print("   Options:")
        print("   1) Put files under cloud-distill/raw/onedrive or raw/gdrive")
        print("   2) Set config.sources.local_dirs")
        print("   3) Run parse with explicit source path: python main.py parse /path/to/TXT")
        sys.exit(1)

    print("Sources:")
    for name, path in sources:
        print(f"  - {name}: {path}")

    parsed = step_parse(sources)
    distilled = step_distill(parsed, config)
    sanitized = step_sanitize(distilled, config)
    step_export(sanitized, config)

    print("\n" + "=" * 60)
    print("✅ PIPELINE COMPLETE")
    print("=" * 60)
    print(f"   Parsed: {len(parsed)} files")
    print(f"   Distilled: {sum(1 for e in distilled if e.get('distilled'))}")
    print(f"   Output: {OUTPUT_DIR}/")
    print(f"   Finished: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")


def load_json_files(pattern: str) -> list[dict]:
    entries: list[dict] = []
    for file_path in sorted(Path(pattern).parent.glob(Path(pattern).name)):
        if not file_path.exists():
            continue
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    entries.extend(data)
            except json.JSONDecodeError:
                continue
    return entries


def main():
    loaded_envs = load_env_chain()

    parser = argparse.ArgumentParser(description="Cloud Distill Pipeline")
    parser.add_argument(
        "step",
        nargs="?",
        default="run",
        choices=["run", "parse", "distill", "sanitize", "export"],
        help="Pipeline step to run",
    )
    parser.add_argument(
        "sources",
        nargs="*",
        help="Optional source aliases or local directories for parse/run steps",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Path to YAML config (default: config.yaml)",
    )
    args = parser.parse_args()

    config = load_config(args.config_path)

    print("☁️🧪 Cloud Distill Pipeline")
    print(f"   Started: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"   Base: {BASE_DIR}")
    print(f"   Config: {config.get('_config_path')}")
    if loaded_envs:
        print(f"   Env loaded: {', '.join(str(p) for p in loaded_envs)}")
    print("")

    if args.step == "run":
        run_full_pipeline(config, source_args=args.sources or None)
        return

    if args.step == "parse":
        sources = resolve_sources(config, source_args=args.sources or None)
        if not sources:
            print("❌ No parse sources resolved.")
            sys.exit(1)
        step_parse(sources)
        return

    if args.step == "distill":
        parsed_entries = load_json_files(str(PARSED_DIR / "*.json"))
        if not parsed_entries:
            print("❌ No parsed entries found. Run parse first.")
            sys.exit(1)
        step_distill(parsed_entries, config)
        return

    if args.step == "sanitize":
        src = DISTILLED_DIR / "distilled.json"
        if not src.exists():
            print("❌ distilled/distilled.json not found. Run distill first.")
            sys.exit(1)
        with open(src, "r", encoding="utf-8") as f:
            entries = json.load(f)
        step_sanitize(entries, config)
        return

    if args.step == "export":
        src = DISTILLED_DIR / "sanitized.json"
        if not src.exists():
            print("❌ distilled/sanitized.json not found. Run sanitize first.")
            sys.exit(1)
        with open(src, "r", encoding="utf-8") as f:
            entries = json.load(f)
        step_export(entries, config)
        return


if __name__ == "__main__":
    main()
