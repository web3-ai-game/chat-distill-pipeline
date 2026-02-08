#!/usr/bin/env python3
"""
Exporter - output distilled knowledge to Markdown, Notion, and GitHub.
"""

import json
import os
import subprocess
import hashlib
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone


class MarkdownExporter:
    """Export distilled docs to a structured Markdown document pack."""

    def __init__(self, output_dir: str = "output/markdown"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, entries: list[dict]) -> Path:
        """Export all entries to organized markdown files."""
        # Group by category
        by_category = {}
        for entry in entries:
            dr = entry.get("distill_result")
            if not dr:
                continue
            cat = dr.get("category", "misc")
            by_category.setdefault(cat, []).append(entry)

        # Write index
        index_path = self.output_dir / "INDEX.md"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# Cloud Distill - Knowledge Base\n\n")
            f.write(f"> Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n")

            total = sum(len(v) for v in by_category.values())
            f.write(f"**Total documents**: {total}\n\n")
            f.write("## Categories\n\n")

            for cat in sorted(by_category.keys()):
                items = by_category[cat]
                f.write(f"- **[{cat}]({cat}/README.md)** — {len(items)} docs\n")

        # Write per-category files
        for cat, items in by_category.items():
            cat_dir = self.output_dir / cat
            cat_dir.mkdir(exist_ok=True)

            # Sort by importance
            items.sort(key=lambda x: x.get("distill_result", {}).get("importance", 0),
                       reverse=True)

            # Category README
            readme_path = cat_dir / "README.md"
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(f"# {cat.title()}\n\n")
                f.write(f"{len(items)} distilled documents\n\n")

                for entry in items:
                    dr = entry["distill_result"]
                    stars = "⭐" * dr.get("importance", 0)
                    title = dr.get("title", entry.get("file_name", "Untitled"))
                    safe_name = self._safe_filename(title)
                    f.write(f"- {stars} [{title}]({safe_name}.md)\n")

            # Individual doc files
            for entry in items:
                dr = entry["distill_result"]
                title = dr.get("title", entry.get("file_name", "Untitled"))
                safe_name = self._safe_filename(title)

                doc_path = cat_dir / f"{safe_name}.md"
                with open(doc_path, "w", encoding="utf-8") as f:
                    self._write_doc(f, entry, dr)

        print(f"✅ Exported {total} docs to {self.output_dir}/")
        return self.output_dir

    def _write_doc(self, f, entry: dict, dr: dict):
        """Write a single distilled document."""
        stars = "⭐" * dr.get("importance", 0)
        f.write(f"# {dr.get('title', 'Untitled')}\n\n")
        f.write(f"**Importance**: {stars} ({dr.get('importance', '?')}/5)\n\n")
        f.write(f"**Category**: {dr.get('category', 'misc')}\n\n")

        if dr.get("language"):
            f.write(f"**Language**: {dr['language']}\n\n")

        if dr.get("topics"):
            f.write(f"**Topics**: {', '.join(dr['topics'])}\n\n")

        f.write("---\n\n")

        # Summary
        f.write(f"## Summary\n\n{dr.get('summary', 'N/A')}\n\n")

        # Key points
        if dr.get("key_points"):
            f.write("## Key Points\n\n")
            for pt in dr["key_points"]:
                f.write(f"- {pt}\n")
            f.write("\n")

        # Data points
        if dr.get("data_points"):
            f.write("## Data Points\n\n")
            for dp in dr["data_points"]:
                f.write(f"- {dp}\n")
            f.write("\n")

        # Actionable items
        if dr.get("actionable_items"):
            f.write("## Action Items\n\n")
            for ai in dr["actionable_items"]:
                f.write(f"- [ ] {ai}\n")
            f.write("\n")

        # Metadata
        f.write("---\n\n")
        f.write(f"*Source: `{entry.get('relative_path', entry.get('file_name', ''))}`*\n")
        f.write(f"*Size: {entry.get('size_bytes', 0):,} bytes*\n")
        f.write(f"*Distilled: {entry.get('distill_tokens', {}).get('input', 0):,} tokens*\n")

    def _safe_filename(self, title: str) -> str:
        """Convert title to safe filename."""
        import re
        safe = re.sub(r'[^\w\s\-]', '', title)
        safe = re.sub(r'\s+', '-', safe.strip())
        return safe[:80].rstrip('-') or "untitled"


class VectorExporter:
    """Export distilled entries as vector-ready JSONL datasets."""

    def __init__(self, output_dir: str = "output/vectors"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, entries: list[dict]) -> dict:
        """Export persona / tech stack / timeline vector seeds."""
        now = datetime.now(timezone.utc).isoformat()
        buckets = {
            "persona": [],
            "tech_stack": [],
            "timeline": [],
            "all": [],
        }

        for entry in entries:
            dr = entry.get("distill_result")
            if not dr or dr.get("drop_content"):
                continue

            channels = self._resolve_channels(dr)
            for channel in channels:
                records = self._build_records_for_channel(entry, dr, channel, now)
                for rec in records:
                    buckets[channel].append(rec)
                    buckets["all"].append(rec)

        # Deduplicate by id in each bucket
        for key in ("persona", "tech_stack", "timeline", "all"):
            buckets[key] = self._dedupe_records(buckets[key])

        outputs = {
            "persona": self.output_dir / "persona_knowledge.jsonl",
            "tech_stack": self.output_dir / "tech_stack_knowledge.jsonl",
            "timeline": self.output_dir / "timeline_knowledge.jsonl",
            "all": self.output_dir / "all_knowledge.jsonl",
        }

        for name, path in outputs.items():
            self._write_jsonl(path, buckets[name])

        manifest = {
            "generated_at": now,
            "counts": {k: len(v) for k, v in buckets.items()},
            "files": {k: str(v) for k, v in outputs.items()},
            "schema": "knowledge_base-compatible seed format",
        }
        manifest_path = self.output_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        print(f"✅ Exported vector seeds to {self.output_dir}/")
        print(
            "   "
            f"persona={manifest['counts']['persona']}, "
            f"tech_stack={manifest['counts']['tech_stack']}, "
            f"timeline={manifest['counts']['timeline']}"
        )
        return manifest

    def _resolve_channels(self, dr: dict) -> list[str]:
        channels = dr.get("vector_channels", [])
        if not isinstance(channels, list):
            channels = []

        normalized = []
        for c in channels:
            val = str(c).strip().lower()
            if val in {"persona", "tech_stack", "timeline"}:
                normalized.append(val)

        # Fallback heuristics
        if dr.get("persona_signals") and "persona" not in normalized:
            normalized.append("persona")
        if dr.get("tech_stack_signals") and "tech_stack" not in normalized:
            normalized.append("tech_stack")
        if dr.get("timeline_signals") and "timeline" not in normalized:
            normalized.append("timeline")

        if not normalized:
            cat = str(dr.get("category", "")).lower()
            if cat in {"personal", "creative"}:
                normalized.append("persona")
            elif cat in {"technical", "data", "reference"}:
                normalized.append("tech_stack")

        return sorted(set(normalized))

    def _build_records_for_channel(self, entry: dict, dr: dict, channel: str,
                                   now: str) -> list[dict]:
        if channel == "timeline":
            return self._build_timeline_records(entry, dr, now)

        title = dr.get("title", entry.get("file_name", "Untitled"))
        summary = dr.get("summary", "")
        points = self._as_list(dr.get("key_points"))
        topics = self._as_list(dr.get("topics"))
        tags = self._build_tags(dr, channel)

        if channel == "persona":
            persona = dr.get("persona_signals", {}) if isinstance(dr.get("persona_signals"), dict) else {}
            lines = [
                f"Title: {title}",
                f"Summary: {summary}",
                f"Traits: {', '.join(self._as_list(persona.get('traits')))}",
                f"Style tags: {', '.join(self._as_list(persona.get('style_tags')))}",
                f"Core values: {', '.join(self._as_list(persona.get('core_values')))}",
                f"Key points: {'; '.join(points[:5])}",
            ]
            content = "\n".join(line for line in lines if not line.endswith(": "))
            record_title = f"{title} · persona"
        else:
            tech = dr.get("tech_stack_signals", {}) if isinstance(dr.get("tech_stack_signals"), dict) else {}
            lines = [
                f"Title: {title}",
                f"Summary: {summary}",
                f"Languages: {', '.join(self._as_list(tech.get('languages')))}",
                f"Frameworks: {', '.join(self._as_list(tech.get('frameworks')))}",
                f"Platforms: {', '.join(self._as_list(tech.get('platforms')))}",
                f"Security domains: {', '.join(self._as_list(tech.get('security_domains')))}",
                f"Tools: {', '.join(self._as_list(tech.get('tools')))}",
                f"Key points: {'; '.join(points[:5])}",
            ]
            content = "\n".join(line for line in lines if not line.endswith(": "))
            record_title = f"{title} · tech stack"

        return [self._make_record(
            channel=channel,
            title=record_title,
            content=content,
            tags=tags + topics,
            entry=entry,
            dr=dr,
            now=now,
        )]

    def _build_timeline_records(self, entry: dict, dr: dict, now: str) -> list[dict]:
        title = dr.get("title", entry.get("file_name", "Untitled"))
        summary = dr.get("summary", "")
        timeline = dr.get("timeline_signals", [])
        if not isinstance(timeline, list):
            timeline = []

        records = []
        for idx, item in enumerate(timeline):
            if not isinstance(item, dict):
                continue
            event = str(item.get("event", "")).strip()
            date_value = str(item.get("date", "unknown")).strip() or "unknown"
            confidence = item.get("confidence")
            if not event:
                continue

            conf_text = ""
            if isinstance(confidence, (int, float)):
                conf_text = f"\nConfidence: {float(confidence):.2f}"

            content = (
                f"Event: {event}\n"
                f"Date: {date_value}\n"
                f"Source summary: {summary}"
                f"{conf_text}"
            )
            tags = self._build_tags(dr, "timeline") + [date_value]
            rec = self._make_record(
                channel="timeline",
                title=f"{title} · timeline · {date_value}",
                content=content,
                tags=tags,
                entry=entry,
                dr=dr,
                now=now,
                extra_metadata={"timeline_date": date_value, "timeline_event": event, "timeline_index": idx},
            )
            records.append(rec)

        return records

    def _make_record(self, channel: str, title: str, content: str, tags: list[str],
                     entry: dict, dr: dict, now: str,
                     extra_metadata: Optional[dict] = None) -> dict:
        source_ref = entry.get("relative_path", entry.get("file_name", "unknown"))
        identifier = hashlib.sha1(f"{channel}|{title}|{source_ref}".encode("utf-8")).hexdigest()[:20]
        clean_tags = sorted(set(t for t in (str(x).strip().lower() for x in tags) if t))

        metadata = {
            "created_at": now,
            "updated_at": now,
            "tags": clean_tags,
            "view_count": 0,
            "source_path": source_ref,
            "source_file": entry.get("file_name", ""),
            "importance": dr.get("importance", 1),
            "language": dr.get("language", "unknown"),
            "distill_category": dr.get("category", "misc"),
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        return {
            "id": f"kb_{identifier}",
            "title": title,
            "content": content,
            # Keep empty by default; embedding generated by downstream vector worker.
            "embedding": [],
            "category": channel,
            "source": "manual",
            "metadata": metadata,
        }

    def _build_tags(self, dr: dict, channel: str) -> list[str]:
        tags = [channel, str(dr.get("category", "misc")).lower()]
        tags.extend(self._as_list(dr.get("topics")))

        if channel == "persona":
            persona = dr.get("persona_signals", {}) if isinstance(dr.get("persona_signals"), dict) else {}
            tags.extend(self._as_list(persona.get("traits")))
            tags.extend(self._as_list(persona.get("style_tags")))
            tags.extend(self._as_list(persona.get("core_values")))
        elif channel == "tech_stack":
            tech = dr.get("tech_stack_signals", {}) if isinstance(dr.get("tech_stack_signals"), dict) else {}
            tags.extend(self._as_list(tech.get("languages")))
            tags.extend(self._as_list(tech.get("frameworks")))
            tags.extend(self._as_list(tech.get("platforms")))
            tags.extend(self._as_list(tech.get("security_domains")))
            tags.extend(self._as_list(tech.get("tools")))

        return tags

    def _write_jsonl(self, path: Path, records: list[dict]):
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _dedupe_records(self, records: list[dict]) -> list[dict]:
        seen = set()
        out = []
        for rec in records:
            rid = rec.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            out.append(rec)
        return out

    def _as_list(self, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        v = str(value).strip()
        return [v] if v else []


class NotionExporter:
    """Export distilled docs to Notion via API."""

    def __init__(self, api_key: Optional[str] = None, parent_page_id: str = ""):
        self.api_key = api_key or os.getenv("NOTION_API_KEY")
        self.parent_page_id = parent_page_id
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }

    def create_database(self, title: str = "Cloud Distill Knowledge Base") -> str:
        """Create a Notion database for the knowledge base."""
        import requests

        payload = {
            "parent": {"page_id": self.parent_page_id},
            "title": [{"text": {"content": title}}],
            "properties": {
                "Title": {"title": {}},
                "Category": {
                    "select": {
                        "options": [
                            {"name": "technical", "color": "blue"},
                            {"name": "business", "color": "green"},
                            {"name": "personal", "color": "yellow"},
                            {"name": "reference", "color": "purple"},
                            {"name": "creative", "color": "pink"},
                            {"name": "data", "color": "orange"},
                            {"name": "misc", "color": "gray"},
                        ]
                    }
                },
                "Importance": {"number": {"format": "number"}},
                "Language": {"rich_text": {}},
                "Topics": {"multi_select": {"options": []}},
                "Source": {"rich_text": {}},
                "Summary": {"rich_text": {}},
            }
        }

        resp = requests.post(
            f"{self.base_url}/databases",
            headers=self.headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        db_id = resp.json()["id"]
        print(f"✅ Created Notion DB: {db_id}")
        return db_id

    def add_entry(self, db_id: str, entry: dict) -> Optional[str]:
        """Add a distilled entry to the Notion database."""
        import requests

        dr = entry.get("distill_result", {})
        if not dr:
            return None

        properties = {
            "Title": {"title": [{"text": {"content": dr.get("title", "Untitled")[:100]}}]},
            "Category": {"select": {"name": dr.get("category", "misc")}},
            "Importance": {"number": dr.get("importance", 1)},
            "Language": {"rich_text": [{"text": {"content": dr.get("language", "en")}}]},
            "Source": {"rich_text": [{"text": {"content": entry.get("relative_path", "")[:100]}}]},
            "Summary": {"rich_text": [{"text": {"content": dr.get("summary", "")[:2000]}}]},
        }

        # Topics as multi-select
        if dr.get("topics"):
            properties["Topics"] = {
                "multi_select": [{"name": t[:100]} for t in dr["topics"][:5]]
            }

        # Page content (children blocks)
        children = []

        # Summary heading
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"text": {"content": "Summary"}}]}
        })
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": dr.get("summary", "N/A")}}]}
        })

        # Key points
        if dr.get("key_points"):
            children.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": "Key Points"}}]}
            })
            for kp in dr["key_points"]:
                children.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"text": {"content": kp}}]}
                })

        payload = {
            "parent": {"database_id": db_id},
            "properties": properties,
            "children": children[:100],  # Notion limit
        }

        resp = requests.post(
            f"{self.base_url}/pages",
            headers=self.headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def export_batch(self, db_id: str, entries: list[dict], delay: float = 0.5):
        """Export batch of entries to Notion."""
        import time

        success = 0
        failed = 0

        for i, entry in enumerate(entries, 1):
            if not entry.get("distill_result"):
                continue
            try:
                page_id = self.add_entry(db_id, entry)
                if page_id:
                    success += 1
                    title = entry["distill_result"].get("title", "")[:40]
                    print(f"  [{i}] ✅ {title}")
            except Exception as e:
                failed += 1
                print(f"  [{i}] ❌ {e}")

            if delay > 0:
                time.sleep(delay)

        print(f"\n📊 Notion export: {success} success, {failed} failed")


class GitHubExporter:
    """Push distilled output to a GitHub repository."""

    def __init__(self, repo_name: str = "gcp-cloud-distill",
                 private: bool = True):
        self.repo_name = repo_name
        self.private = private

    def init_and_push(self, source_dir: Path):
        """Initialize git repo and push to GitHub."""
        # Check if gh CLI is available
        result = subprocess.run(["gh", "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            print("❌ GitHub CLI (gh) not found. Install: brew install gh")
            return

        print(f"\n📤 Pushing to GitHub: {self.repo_name}")

        # Init git
        subprocess.run(["git", "init"], cwd=str(source_dir))
        subprocess.run(["git", "add", "."], cwd=str(source_dir))
        subprocess.run(
            ["git", "commit", "-m", "Initial distilled knowledge base"],
            cwd=str(source_dir)
        )

        # Create repo
        vis = "--private" if self.private else "--public"
        result = subprocess.run(
            ["gh", "repo", "create", self.repo_name, vis,
             "--source", str(source_dir), "--push"],
            capture_output=True, text=True, cwd=str(source_dir)
        )

        if result.returncode == 0:
            print(f"✅ Pushed to GitHub: {self.repo_name}")
            print(f"   {result.stdout.strip()}")
        else:
            # Repo may already exist, try push
            print(f"  Repo may exist, trying push...")
            subprocess.run(
                ["git", "remote", "add", "origin",
                 f"https://github.com/{self._get_user()}/{self.repo_name}.git"],
                cwd=str(source_dir),
                capture_output=True,
            )
            subprocess.run(
                ["git", "push", "-u", "origin", "main"],
                cwd=str(source_dir),
            )

    def _get_user(self) -> str:
        """Get current GitHub username."""
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True,
        )
        return result.stdout.strip() or "user"
