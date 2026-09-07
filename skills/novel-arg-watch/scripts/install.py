#!/usr/bin/env python3
"""Copy this skill into a Cursor or Codex skill directory.

  python scripts/install.py --codex          # ~/.codex/skills/novel-arg-watch
  python scripts/install.py --cursor         # ./.cursor/skills/novel-arg-watch
  python scripts/install.py --dest some/dir  # anywhere

Standard library only, so it runs on a bare Python 3.9+.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_NAME = SKILL_DIR.name
SKIP = {"__pycache__"}


def copy_skill(dest: Path, force: bool) -> None:
    if dest.exists():
        if not force:
            raise SystemExit(f"{dest} already exists; pass --force to replace it")
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SKILL_DIR,
        dest,
        ignore=shutil.ignore_patterns(*SKIP, "*.pyc", "*.partial", "*.bak-*"),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Install the novel-arg-watch skill")
    ap.add_argument("--codex", action="store_true", help="install to ~/.codex/skills/")
    ap.add_argument("--cursor", action="store_true", help="install to ./.cursor/skills/")
    ap.add_argument("--dest", type=Path, help="explicit destination directory")
    ap.add_argument("--force", action="store_true", help="replace an existing install")
    args = ap.parse_args()

    targets: list[Path] = []
    if args.codex:
        targets.append(Path.home() / ".codex" / "skills" / SKILL_NAME)
    if args.cursor:
        targets.append(Path.cwd() / ".cursor" / "skills" / SKILL_NAME)
    if args.dest:
        targets.append(args.dest if args.dest.name == SKILL_NAME else args.dest / SKILL_NAME)
    if not targets:
        raise SystemExit("pick at least one of --codex, --cursor, --dest")

    for dest in targets:
        copy_skill(dest, args.force)
        print(f"installed {SKILL_NAME} -> {dest}")
    print(f"verify with: {sys.executable} {targets[0] / 'scripts' / 'verify.py'}")


if __name__ == "__main__":
    main()
