#!/usr/bin/env python3
"""Install the portable DJI Cloud API skill for supported coding agents."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "build/skills/dji-cloud-api"
TARGETS = {
    "cursor": ".cursor/skills",
    "codex": ".agents/skills",
    "claude": ".claude/skills",
    "codebuddy": ".codebuddy/skills",
    "workbuddy": ".workbuddy/skills",
    "copilot": ".github/skills",
    "antigravity": ".agent/skills",
    "gemini": ".gemini/skills",
}


def copy_skill(destination_root: Path, force: bool) -> Path:
    destination = destination_root / SOURCE.name
    if destination.resolve() == SOURCE.resolve():
        return destination
    if destination.exists():
        if not force:
            raise FileExistsError(f"{destination} exists; pass --force to replace it")
        shutil.rmtree(destination)
    destination_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SOURCE,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agents", nargs="*", choices=sorted(TARGETS), help="Agent targets to install")
    parser.add_argument("--all", action="store_true", help="Install for every supported agent")
    parser.add_argument("--project", type=Path, default=ROOT, help="Target project root")
    parser.add_argument("--target-dir", type=Path, help="Install into a custom skills directory")
    parser.add_argument("--force", action="store_true", help="Replace an existing installed copy")
    args = parser.parse_args()

    subprocess.run([sys.executable, str(ROOT / "scripts/build_artifacts.py")], cwd=ROOT, check=True)

    if args.target_dir:
        destinations = [args.target_dir.resolve()]
    else:
        agents = sorted(TARGETS) if args.all else args.agents
        if not agents:
            parser.error("specify one or more agents, --all, or --target-dir")
        project = args.project.resolve()
        destinations = [project / TARGETS[agent] for agent in agents]

    for destination_root in destinations:
        installed = copy_skill(destination_root, args.force)
        print(installed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
