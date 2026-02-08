#!/usr/bin/env python3
"""
Setup rclone remotes for OneDrive and Google Drive.
Requires user interaction in browser for OAuth.
"""

import subprocess
import sys


def run(cmd: list[str], interactive=False):
    """Run a command, optionally interactive (for OAuth)."""
    if interactive:
        # Interactive mode - user needs to see prompts and click browser
        result = subprocess.run(cmd)
        return result.returncode == 0
    else:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  Error: {result.stderr.strip()}")
        return result.returncode == 0


def check_rclone():
    """Check if rclone is installed."""
    result = subprocess.run(["rclone", "version"], capture_output=True, text=True)
    if result.returncode != 0:
        print("❌ rclone not found. Install: brew install rclone")
        sys.exit(1)
    version = result.stdout.split("\n")[0]
    print(f"✓ {version}")


def list_remotes():
    """List existing rclone remotes."""
    result = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True)
    remotes = [r.strip().rstrip(":") for r in result.stdout.strip().split("\n") if r.strip()]
    return remotes


def setup_onedrive():
    """Configure OneDrive remote."""
    print("\n" + "=" * 50)
    print("📁 Setting up OneDrive remote")
    print("=" * 50)
    print("This will open your browser for Microsoft login.")
    print("After login, grant permission to rclone.\n")

    # rclone config create onedrive onedrive
    # This is interactive - needs browser OAuth
    subprocess.run([
        "rclone", "config", "create", "onedrive", "onedrive",
        "--all"  # Show all options
    ])

    # Verify
    result = subprocess.run(
        ["rclone", "lsd", "onedrive:"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        print("\n✅ OneDrive connected! Top-level folders:")
        for line in result.stdout.strip().split("\n")[:10]:
            print(f"  {line}")
    else:
        print(f"\n⚠️  OneDrive verification failed: {result.stderr.strip()}")
        print("You may need to run: rclone config  (interactive setup)")


def setup_gdrive():
    """Configure Google Drive remote."""
    print("\n" + "=" * 50)
    print("📁 Setting up Google Drive remote")
    print("=" * 50)
    print("This will open your browser for Google login.")
    print("After login, grant permission to rclone.\n")

    # rclone config create gdrive drive
    subprocess.run([
        "rclone", "config", "create", "gdrive", "drive",
        "--all"
    ])

    # Verify
    result = subprocess.run(
        ["rclone", "lsd", "gdrive:"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        print("\n✅ Google Drive connected! Top-level folders:")
        for line in result.stdout.strip().split("\n")[:10]:
            print(f"  {line}")
    else:
        print(f"\n⚠️  Google Drive verification failed: {result.stderr.strip()}")
        print("You may need to run: rclone config  (interactive setup)")


def main():
    print("🔧 Cloud Distill - Remote Setup\n")

    check_rclone()

    existing = list_remotes()
    if existing:
        print(f"\nExisting remotes: {', '.join(existing)}")

    # OneDrive
    if "onedrive" in existing:
        print("\n✓ OneDrive remote already configured")
        resp = input("  Reconfigure? [y/N]: ").strip().lower()
        if resp != "y":
            print("  Skipped.")
        else:
            setup_onedrive()
    else:
        setup_onedrive()

    # Google Drive
    if "gdrive" in existing:
        print("\n✓ Google Drive remote already configured")
        resp = input("  Reconfigure? [y/N]: ").strip().lower()
        if resp != "y":
            print("  Skipped.")
        else:
            setup_gdrive()
    else:
        setup_gdrive()

    print("\n" + "=" * 50)
    print("✅ Setup complete!")
    print("Next: python scripts/pull.py")
    print("=" * 50)


if __name__ == "__main__":
    main()
