#!/usr/bin/env python3
# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - ci_validate.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Run the dependency-free, non-destructive HYDRA-UMC project baseline."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_DOCUMENTS = ("README.md", "README_spa.md", "README_fra.md", "README_ita.md", "README_deu.md", "README_zho.md", "README_jpn.md", "CHANGELOG.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "SUPPORT.md")
REQUIRED_MANIFEST_KEYS = ("schema_version", "ecosystem", "name", "version", "role", "stack", "technologies", "deployment_target", "maturity", "family", "parent", "build", "notes", "native_version")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
CHANGELOG_VERSION = re.compile(r"(?im)^#{1,3}\s*\[?(\d+\.\d+\.\d+)(?:\]|\s|$)")
LOCAL_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+[\"'][^)]*)?\)")
EXCLUDED_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "build", "dist", "target", "__pycache__", ".gradle"}

def fail(message: str) -> None:
    print(f"CI_VALIDATION=FAIL {message}", file=sys.stderr)
    raise SystemExit(1)

def native_version(path: Path, pattern: str | dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if isinstance(pattern, dict):
        values: list[str] = []
        for component in ("major", "minor", "patch"):
            match = re.search(pattern[component], text, re.MULTILINE)
            if match is None: raise ValueError(f"native {component} version component not found")
            values.append(match.group(1))
        return ".".join(values)
    match = re.search(pattern, text, re.MULTILINE)
    if match is None or len(match.groups()) < 3: raise ValueError("native version pattern did not expose major.minor.patch")
    return ".".join(match.group(index) for index in (1, 2, 3))

def validate_markdown_links() -> None:
    broken: list[str] = []
    for markdown_path in ROOT.rglob("*.md"):
        if any(part in EXCLUDED_DIRECTORIES for part in markdown_path.parts): continue
        for number, line in enumerate(markdown_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            for match in LOCAL_LINK.finditer(line):
                reference = match.group(1).strip().strip("<>")
                target = reference.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0]
                if not target or re.match(r"(?i)^(https?:|mailto:|tel:|data:)", target) or target.startswith("/"): continue
                if not (markdown_path.parent / target).resolve().exists(): broken.append(f"{markdown_path.relative_to(ROOT)}:{number} -> {reference}")
    if broken: fail("broken local Markdown link(s): " + "; ".join(broken[:10]))

def main() -> int:
    try: manifest = json.loads((ROOT / "hydra-umc.project.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: fail(f"cannot read manifest: {exc}")
    missing = [key for key in REQUIRED_MANIFEST_KEYS if key not in manifest]
    if missing: fail("manifest missing required keys: " + ", ".join(missing))
    if manifest["ecosystem"] != "HYDRA-UMC" or manifest["name"] != ROOT.name: fail("manifest ecosystem/name does not match this HYDRA-UMC repository")
    if not isinstance(manifest["version"], str) or not SEMVER.fullmatch(manifest["version"]): fail("manifest version must be MAJOR.MINOR.PATCH")
    if not isinstance(manifest["technologies"], list) or not manifest["technologies"]: fail("manifest technologies must be a non-empty list")
    missing_docs = [name for name in REQUIRED_DOCUMENTS if not (ROOT / name).is_file()]
    if missing_docs: fail("required documentation missing: " + ", ".join(missing_docs))
    required_build_files = ("build-test.bat", "build-test.sh", "tools/build_test.py", "tools/bump_version.py")
    missing_build = [name for name in required_build_files if not (ROOT / name).is_file()]
    if missing_build: fail("required build support missing: " + ", ".join(missing_build))
    native = manifest["native_version"]
    try: actual_native = native_version(ROOT / str(native["file"]), native["pattern"])
    except (KeyError, OSError, TypeError, ValueError, re.error) as exc: fail(f"cannot validate native version: {exc}")
    if actual_native != manifest["version"]: fail(f"native version {actual_native} differs from manifest {manifest['version']}")
    changelog_match = CHANGELOG_VERSION.search((ROOT / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace"))
    if changelog_match is None or changelog_match.group(1) != manifest["version"]: fail("latest CHANGELOG version differs from manifest")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="replace")
    if not re.search(r"(?m)^\.env(?:\.|$|\*)", gitignore) or not re.search(r"(?m)^!\.env\.example$", gitignore): fail(".gitignore must exclude .env and retain .env.example")
    validate_markdown_links()
    private_marker = "SON" + "NET"
    result = subprocess.run(("git", "grep", "-n", "-I", "--", private_marker), cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if result.returncode == 0: fail("public files must not reference private documentation")
    if result.returncode not in (0, 1): fail("could not check public/private documentation boundary")
    print(f"CI_VALIDATION=PASS project={manifest['name']} version={manifest['version']}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
