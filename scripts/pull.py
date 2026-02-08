#!/usr/bin/env python3
"""
Pull files from OneDrive and Google Drive to local raw/ directory.
Uses rclone for efficient syncing.
"""

import subprocess
import sys
import os
import json
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw"


def ensure_dirs():
    """Create raw directories if they don't exist."""
    (RAW_DIR / "onedrive").mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "gdrive").mkdir(parents=True, exist_ok=True)


def list_remotes():
    """Get configured rclone remotes."""
    result = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True)
    return [r.strip().rstrip(":") for r in result.stdout.strip().split("\n") if r.strip()]


def preview_remote(remote_name: str):
    """Show what's in the remote before pulling."""
    print(f"\n📂 Previewing {remote_name}:")

    # List top-level with sizes
    result = subprocess.run(
        ["rclone", "lsd", f"{remote_name}:"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        print(f"  ❌ Cannot access {remote_name}: {result.stderr.strip()}")
        return False

    folders = result.stdout.strip().split("\n")
    for f in folders[:20]:
        print(f"  {f}")
    if len(folders) > 20:
        print(f"  ... and {len(folders) - 20} more folders")

    # Get total size
    print(f"\n  Calculating total size (may take a moment)...")
    result = subprocess.run(
        ["rclone", "size", f"{remote_name}:", "--json"],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode == 0:
        try:
            size_info = json.loads(result.stdout)
            count = size_info.get("count", 0)
            size_bytes = size_info.get("bytes", 0)
            size_gb = size_bytes / (1024 ** 3)
            print(f"  📊 Total: {count:,} files, {size_gb:.2f} GB")
        except json.JSONDecodeError:
            pass

    return True


def pull_remote(remote_name: str, local_subdir: str, dry_run=False):
    """
    Pull files from a remote to local directory.
    Uses rclone copy (not sync - won't delete local files).
    """
    local_path = RAW_DIR / local_subdir
    local_path.mkdir(parents=True, exist_ok=True)

    print(f"\n{'🔍 DRY RUN' if dry_run else '📥 Pulling'}: {remote_name}: → {local_path}")

    cmd = [
        "rclone", "copy",
        f"{remote_name}:",
        str(local_path),
        "--progress",
        "--transfers", "8",          # Parallel transfers
        "--checkers", "16",          # Parallel checkers
        "--stats", "5s",             # Progress every 5s
        "--stats-one-line",
        "--log-level", "NOTICE",
        # Skip very large files (>500MB) - videos etc
        "--max-size", "500M",
    ]

    if dry_run:
        cmd.append("--dry-run")

    print(f"  Command: {' '.join(cmd)}\n")

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print(f"\n✅ {'Preview' if dry_run else 'Pull'} complete for {remote_name}")
    else:
        print(f"\n⚠️  Pull had issues (exit code {result.returncode})")

    return result.returncode == 0


def generate_manifest(local_subdir: str, remote_name: str):
    """Generate a manifest of pulled files."""
    local_path = RAW_DIR / local_subdir
    manifest = {
        "source": remote_name,
        "pulled_at": datetime.utcnow().isoformat(),
        "files": []
    }

    for root, dirs, files in os.walk(local_path):
        for f in files:
            fpath = Path(root) / f
            rel = fpath.relative_to(local_path)
            manifest["files"].append({
                "path": str(rel),
                "size": fpath.stat().st_size,
                "ext": fpath.suffix.lower()
            })

    manifest["total_files"] = len(manifest["files"])
    manifest["total_size"] = sum(f["size"] for f in manifest["files"])

    # Stats by extension
    ext_stats = {}
    for f in manifest["files"]:
        ext = f["ext"] or "(no ext)"
        if ext not in ext_stats:
            ext_stats[ext] = {"count": 0, "size": 0}
        ext_stats[ext]["count"] += 1
        ext_stats[ext]["size"] += f["size"]
    manifest["by_extension"] = dict(sorted(ext_stats.items(), key=lambda x: x[1]["count"], reverse=True))

    manifest_path = RAW_DIR / f"{local_subdir}_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2, ensure_ascii=False)

    print(f"\n📋 Manifest: {manifest_path}")
    print(f"   Total: {manifest['total_files']:,} files, {manifest['total_size'] / (1024**2):.1f} MB")
    print(f"   Top types:")
    for ext, stats in list(manifest["by_extension"].items())[:10]:
        print(f"     {ext}: {stats['count']} files ({stats['size'] / (1024**2):.1f} MB)")

    return manifest


def main():
    print("📥 Cloud Distill - File Puller\n")

    ensure_dirs()
    remotes = list_remotes()

    if not remotes:
        print("❌ No rclone remotes configured.")
        print("   Run: python scripts/setup_remotes.py")
        sys.exit(1)

    print(f"Available remotes: {', '.join(remotes)}")

    # Check what user wants
    targets = []
    if "onedrive" in remotes:
        targets.append(("onedrive", "onedrive"))
    if "gdrive" in remotes:
        targets.append(("gdrive", "gdrive"))

    if not targets:
        print("❌ Neither 'onedrive' nor 'gdrive' remote found.")
        print("   Run: python scripts/setup_remotes.py")
        sys.exit(1)

    # Preview first
    for remote_name, local_subdir in targets:
        accessible = preview_remote(remote_name)
        if not accessible:
            continue

    # Confirm
    print("\n" + "=" * 50)
    resp = input("Proceed with pull? [y/N/dry]: ").strip().lower()

    if resp == "dry":
        for remote_name, local_subdir in targets:
            pull_remote(remote_name, local_subdir, dry_run=True)
        return

    if resp != "y":
        print("Cancelled.")
        return

    # Pull
    for remote_name, local_subdir in targets:
        success = pull_remote(remote_name, local_subdir)
        if success:
            generate_manifest(local_subdir, remote_name)

    print("\n" + "=" * 50)
    print("✅ All pulls complete!")
    print("Next: python main.py")
    print("=" * 50)


if __name__ == "__main__":
    main()
