#!/usr/bin/env python3
"""
Document parser - extract text content from various file types.
Supports: DOCX, PDF, PPT, XLSX, TXT, RTF, CSV, MD, images (metadata only)
"""

import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from datetime import datetime


class DocumentParser:
    """Parse documents into structured text content."""

    DOCUMENT_EXTS = {".docx", ".doc", ".pdf", ".txt", ".rtf", ".md", ".odt"}
    SPREADSHEET_EXTS = {".xlsx", ".xls", ".csv", ".ods"}
    PRESENTATION_EXTS = {".pptx", ".ppt", ".odp"}
    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}
    SKIP_EXTS = {".mp4", ".mov", ".avi", ".mp3", ".wav", ".zip", ".rar",
                 ".7z", ".exe", ".dmg", ".iso", ".bin", ".dat"}

    def __init__(self, min_content_length: int = 50):
        self.min_content_length = min_content_length
        self.stats = {"parsed": 0, "skipped": 0, "failed": 0, "by_type": {}}

    def parse_file(self, file_path: Path) -> Optional[dict]:
        """
        Parse a single file and return structured content.
        Returns None if file should be skipped.
        """
        ext = file_path.suffix.lower()

        if ext in self.SKIP_EXTS:
            self.stats["skipped"] += 1
            return self._make_entry(file_path, ext, "", "skipped")

        try:
            text = ""
            if ext in self.DOCUMENT_EXTS:
                text = self._parse_document(file_path, ext)
            elif ext in self.SPREADSHEET_EXTS:
                text = self._parse_spreadsheet(file_path, ext)
            elif ext in self.PRESENTATION_EXTS:
                text = self._parse_presentation(file_path, ext)
            elif ext in self.IMAGE_EXTS:
                text = self._parse_image(file_path)
            else:
                # Try as plain text
                text = self._parse_text(file_path)

            self.stats["parsed"] += 1
            self.stats["by_type"][ext] = self.stats["by_type"].get(ext, 0) + 1

            return self._make_entry(file_path, ext, text, "parsed")

        except Exception as e:
            self.stats["failed"] += 1
            return self._make_entry(file_path, ext, "", "failed", str(e))

    def _make_entry(self, file_path: Path, ext: str, text: str,
                    status: str, error: str = "") -> dict:
        """Create a standardized entry."""
        stat = file_path.stat() if file_path.exists() else None
        return {
            "file_path": str(file_path),
            "file_name": file_path.name,
            "extension": ext,
            "size_bytes": stat.st_size if stat else 0,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat() if stat else "",
            "status": status,
            "content": text,
            "content_length": len(text),
            "error": error,
            "parsed_at": datetime.utcnow().isoformat(),
        }

    def _parse_document(self, file_path: Path, ext: str) -> str:
        """Parse document files."""
        if ext == ".docx":
            return self._parse_docx(file_path)
        elif ext == ".pdf":
            return self._parse_pdf(file_path)
        elif ext == ".rtf":
            return self._parse_rtf(file_path)
        elif ext in (".txt", ".md"):
            return self._parse_text(file_path)
        elif ext == ".doc":
            # .doc (old format) - try as text, may fail
            return self._parse_text(file_path)
        return ""

    def _parse_docx(self, file_path: Path) -> str:
        """Parse DOCX using python-docx."""
        try:
            from docx import Document
            doc = Document(str(file_path))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]

            # Also extract from tables
            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if cells:
                        paragraphs.append(" | ".join(cells))

            return "\n\n".join(paragraphs)
        except Exception:
            # Fallback: parse OOXML directly, no external dependency.
            return self._parse_docx_fallback(file_path)

    def _parse_pdf(self, file_path: Path) -> str:
        """Parse PDF using PyPDF2."""
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(file_path))
            pages = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text and text.strip():
                    pages.append(f"[Page {i+1}]\n{text.strip()}")
            return "\n\n".join(pages)
        except Exception:
            return ""

    def _parse_rtf(self, file_path: Path) -> str:
        """Parse RTF using striprtf."""
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            rtf_content = f.read()
        try:
            from striprtf.striprtf import rtf_to_text
            return rtf_to_text(rtf_content)
        except Exception:
            # Minimal fallback parser for offline environments.
            text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", rtf_content)
            text = re.sub(r"\\[a-zA-Z]+\d* ?", " ", text)
            text = text.replace("{", " ").replace("}", " ")
            text = re.sub(r"\s+", " ", text)
            return text.strip()

    def _parse_text(self, file_path: Path) -> str:
        """Parse plain text files."""
        encodings = ["utf-8", "utf-16", "gb18030", "big5", "latin-1"]
        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        return ""

    def _parse_spreadsheet(self, file_path: Path, ext: str) -> str:
        """Parse spreadsheet files."""
        if ext == ".csv":
            return self._parse_text(file_path)
        elif ext in (".xlsx", ".xls"):
            return self._parse_xlsx(file_path)
        return ""

    def _parse_xlsx(self, file_path: Path) -> str:
        """Parse XLSX using openpyxl."""
        try:
            from openpyxl import load_workbook
            wb = load_workbook(str(file_path), read_only=True, data_only=True)
            sheets = []

            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows = []
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    if any(c.strip() for c in cells):
                        rows.append(" | ".join(cells))

                if rows:
                    sheets.append(f"[Sheet: {sheet_name}]\n" + "\n".join(rows))

            wb.close()
            return "\n\n".join(sheets)
        except Exception:
            return self._parse_xlsx_fallback(file_path)

    def _parse_presentation(self, file_path: Path, ext: str) -> str:
        """Parse presentation files."""
        if ext == ".pptx":
            return self._parse_pptx(file_path)
        return ""

    def _parse_pptx(self, file_path: Path) -> str:
        """Parse PPTX using python-pptx."""
        try:
            from pptx import Presentation
            prs = Presentation(str(file_path))
            slides = []

            for i, slide in enumerate(prs.slides):
                texts = []
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        texts.append(shape.text.strip())
                if texts:
                    slides.append(f"[Slide {i+1}]\n" + "\n".join(texts))

            return "\n\n".join(slides)
        except Exception:
            return self._parse_pptx_fallback(file_path)

    def _parse_image(self, file_path: Path) -> str:
        """For images, just record metadata (no OCR by default)."""
        try:
            from PIL import Image
            img = Image.open(str(file_path))
            w, h = img.size
            mode = img.mode
            fmt = img.format
            return f"[Image: {w}x{h}, {mode}, {fmt}]"
        except Exception:
            return f"[Image: {file_path.suffix}]"

    def _parse_docx_fallback(self, file_path: Path) -> str:
        """Fallback DOCX parser via XML extraction."""
        parts = []
        try:
            with zipfile.ZipFile(file_path) as zf:
                targets = [
                    name for name in zf.namelist()
                    if name.startswith("word/") and name.endswith(".xml")
                    and any(key in name for key in ("document", "header", "footer", "footnotes", "endnotes"))
                ]
                for member in sorted(targets):
                    texts = self._iter_xml_text(zf.read(member))
                    if texts:
                        parts.append("\n".join(texts))
        except Exception:
            return ""
        return "\n\n".join(parts).strip()

    def _parse_xlsx_fallback(self, file_path: Path) -> str:
        """Fallback XLSX parser via XML extraction."""
        try:
            with zipfile.ZipFile(file_path) as zf:
                shared = []
                if "xl/sharedStrings.xml" in zf.namelist():
                    shared = self._iter_xml_text(zf.read("xl/sharedStrings.xml"))

                ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                sheets = []
                sheet_files = sorted(
                    name for name in zf.namelist()
                    if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
                )
                for i, member in enumerate(sheet_files, start=1):
                    root = ET.fromstring(zf.read(member))
                    rows = []
                    for row in root.findall(".//a:row", ns):
                        vals = []
                        for cell in row.findall("a:c", ns):
                            cell_type = cell.attrib.get("t", "")
                            v = cell.find("a:v", ns)
                            is_text = cell.find("a:is/a:t", ns)
                            raw = ""
                            if is_text is not None and is_text.text:
                                raw = is_text.text
                            elif v is not None and v.text:
                                raw = v.text
                            if not raw:
                                continue
                            if cell_type == "s":
                                try:
                                    idx = int(raw)
                                    raw = shared[idx] if 0 <= idx < len(shared) else raw
                                except ValueError:
                                    pass
                            vals.append(raw.strip())

                        vals = [x for x in vals if x]
                        if vals:
                            rows.append(" | ".join(vals))

                    if rows:
                        sheets.append(f"[Sheet {i}]\n" + "\n".join(rows))

                return "\n\n".join(sheets)
        except Exception:
            return ""

    def _parse_pptx_fallback(self, file_path: Path) -> str:
        """Fallback PPTX parser via XML extraction."""
        try:
            with zipfile.ZipFile(file_path) as zf:
                slides = []
                members = sorted(
                    name for name in zf.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                )
                for i, member in enumerate(members, start=1):
                    texts = self._iter_xml_text(zf.read(member))
                    if texts:
                        slides.append(f"[Slide {i}]\n" + "\n".join(texts))
                return "\n\n".join(slides)
        except Exception:
            return ""

    def _iter_xml_text(self, xml_bytes: bytes) -> list[str]:
        """Extract text nodes from OOXML bytes."""
        try:
            root = ET.fromstring(xml_bytes)
        except Exception:
            return []

        texts = []
        for elem in root.iter():
            tag = elem.tag.split("}")[-1]
            if tag == "t":
                val = (elem.text or "").strip()
                if val:
                    texts.append(val)
        return texts

    def parse_directory(self, dir_path: Path, output_path: Path) -> list[dict]:
        """
        Parse all files in a directory recursively.
        Saves results incrementally to output_path.
        """
        results = []
        files = sorted(dir_path.rglob("*"))
        files = [f for f in files if f.is_file()]

        print(f"📄 Parsing {len(files)} files from {dir_path.name}/")

        for i, fpath in enumerate(files, 1):
            rel = fpath.relative_to(dir_path)
            entry = self.parse_file(fpath)
            if entry:
                entry["relative_path"] = str(rel)
                results.append(entry)

            if i % 50 == 0 or i == len(files):
                print(f"  [{i}/{len(files)}] Parsed: {self.stats['parsed']}, "
                      f"Skipped: {self.stats['skipped']}, Failed: {self.stats['failed']}")

        # Save
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Parsed {len(results)} files → {output_path}")
        self._print_stats()

        return results

    def _print_stats(self):
        """Print parsing statistics."""
        print(f"\n📊 Parse Stats:")
        print(f"   Parsed: {self.stats['parsed']}")
        print(f"   Skipped: {self.stats['skipped']}")
        print(f"   Failed: {self.stats['failed']}")
        if self.stats["by_type"]:
            print(f"   By type:")
            for ext, count in sorted(self.stats["by_type"].items(),
                                     key=lambda x: x[1], reverse=True):
                print(f"     {ext}: {count}")
