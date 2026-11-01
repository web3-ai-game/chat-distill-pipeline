#!/usr/bin/env python3
"""
Sanitizer - desensitize personal/sensitive information from text.
Supports: phone, email, ID numbers, card numbers, addresses, names.
"""

import re
from typing import Optional


class Sanitizer:
    """Remove or mask sensitive information from text."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.stats = {
            "phone": 0,
            "email": 0,
            "id_number": 0,
            "card_number": 0,
            "url_credential": 0,
            "ip_address": 0,
            "custom": 0,
        }

        # Compile regex patterns
        self._patterns = self._build_patterns()

    def _build_patterns(self) -> list[tuple[str, re.Pattern, str]]:
        """Build compiled regex patterns."""
        patterns = []

        # Email (high priority - match before other patterns)
        patterns.append((
            "email",
            re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'),
            "[EMAIL]"
        ))

        # Phone numbers (international formats)
        phone_patterns = [
            # International: +66 81 606 1234, +86-138-0013-8000
            r'\+\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{2,4}[-.\s]?\d{2,4}[-.\s]?\d{0,4}',
            # Thai: 081-606-1234, 02-123-4567
            r'\b0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b',
            # Chinese: 138 0013 8000
            r'\b1[3-9]\d[-.\s]?\d{4}[-.\s]?\d{4}\b',
            # Generic: (02) 1234-5678
            r'\(\d{2,4}\)\s?\d{3,4}[-.\s]?\d{3,4}',
        ]
        for pp in phone_patterns:
            patterns.append(("phone", re.compile(pp), "[PHONE]"))

        # Credit/debit card numbers
        patterns.append((
            "card_number",
            re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
            "[CARD_NUMBER]"
        ))

        # ID numbers
        id_patterns = [
            # Thai national ID: 1-1234-12345-12-1
            r'\b\d{1}[-]\d{4}[-]\d{5}[-]\d{2}[-]\d{1}\b',
            # Chinese national ID: 18 digits
            r'\b\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b',
            # Passport-like: AB1234567
            r'\b[A-Z]{1,2}\d{7,9}\b',
        ]
        for ip in id_patterns:
            patterns.append(("id_number", re.compile(ip), "[ID_NUMBER]"))

        # URLs with credentials: https://user:pass@host
        patterns.append((
            "url_credential",
            re.compile(r'(https?://)([^:]+):([^@]+)@'),
            r'\1[USER]:[PASS]@'
        ))

        # IP addresses (private ranges more aggressively)
        patterns.append((
            "ip_address",
            re.compile(r'\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b'),
            "[PRIVATE_IP]"
        ))

        # API keys / tokens (common patterns)
        api_key_patterns = [
            # Generic long hex/base64 tokens
            r'\b(?:sk|pk|api|key|token|secret|password)[-_]?[=:]\s*["\']?([A-Za-z0-9_\-]{20,})["\']?',
            # AWS keys
            r'\bAKIA[0-9A-Z]{16}\b',
            # Specific prefixes
            r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b',
            r'\bxai-[A-Za-z0-9]{20,}\b',
            r'\bntn_[A-Za-z0-9]{20,}\b',
            r'\bAIza[A-Za-z0-9_\-]{35}\b',
        ]
        for ap in api_key_patterns:
            patterns.append(("custom", re.compile(ap), "[API_KEY]"))

        return patterns

    def sanitize(self, text: str) -> str:
        """
        Apply all sanitization rules to text.
        Returns sanitized text.
        """
        if not text:
            return text

        result = text

        for category, pattern, replacement in self._patterns:
            matches = pattern.findall(result)
            if matches:
                self.stats[category] = self.stats.get(category, 0) + len(matches)
                result = pattern.sub(replacement, result)

        # Apply custom patterns from config
        for custom in self.config.get("custom_patterns", []):
            try:
                pat = re.compile(custom["pattern"])
                matches = pat.findall(result)
                if matches:
                    self.stats["custom"] += len(matches)
                    result = pat.sub(custom.get("replacement", "[REDACTED]"), result)
            except re.error:
                pass

        return result

    def sanitize_entry(self, entry: dict) -> dict:
        """Sanitize a parsed document entry."""
        sanitized = entry.copy()

        # Sanitize content
        if entry.get("content"):
            sanitized["content"] = self.sanitize(entry["content"])

        # Sanitize file path (may contain usernames)
        if entry.get("file_path"):
            sanitized["file_path"] = self._sanitize_path(entry["file_path"])
        if entry.get("relative_path"):
            sanitized["relative_path"] = self._sanitize_path(entry["relative_path"])

        sanitized["sanitized"] = True
        return sanitized

    def _sanitize_path(self, path: str) -> str:
        """Sanitize file paths - replace home directory username."""
        # Replace /Users/username/ or /home/username/ with /Users/[USER]/
        result = re.sub(r'/(?:Users|home)/[^/]+/', '/Users/[USER]/', path)
        return result

    def get_stats(self) -> dict:
        """Return sanitization statistics."""
        total = sum(self.stats.values())
        return {**self.stats, "total_replacements": total}

    def print_stats(self):
        """Print sanitization statistics."""
        stats = self.get_stats()
        print(f"\n🔒 Sanitization Stats:")
        print(f"   Total replacements: {stats['total_replacements']}")
        for key, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
            if key != "total_replacements" and count > 0:
                print(f"   {key}: {count}")
