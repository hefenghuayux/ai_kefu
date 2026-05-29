#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_step(ps_script: Path) -> None:
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ps_script),
    ]
    print(f"\n>>> Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    scripts = [
        base_dir / "start_mysql.ps1",
        base_dir / "start_redis.ps1",
        base_dir / "start_neo4j.ps1",
    ]

    for script in scripts:
        if not script.exists():
            print(f"[ERROR] Script not found: {script}")
            return 1

    for script in scripts:
        try:
            run_step(script)
        except subprocess.CalledProcessError as exc:
            print(f"[ERROR] Failed: {script} (exit code: {exc.returncode})")
            return exc.returncode or 1
        except FileNotFoundError:
            print("[ERROR] `powershell` command not found in PATH.")
            return 1

    print("\nAll services start commands completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
