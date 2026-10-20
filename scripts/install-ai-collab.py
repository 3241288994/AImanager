#!/usr/bin/env python3
"""Install a versioned, standard-library-only collaboration CLI and companion skill."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    parser.add_argument("--skill-dir", type=Path, default=Path.home() / ".codex/skills")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    repo = source.parent
    prefix = args.prefix.expanduser().resolve()
    home = prefix / "lib/ai-collab"
    home.mkdir(parents=True, exist_ok=True)
    inputs = [source / "ai_collab_cli.py", repo / "docs/ai-collaboration.md"]
    inputs += sorted((source / "ai_collab").glob("*.py"))
    inputs += sorted(p for p in (repo / "skills/multi-model-collaboration").rglob("*") if p.is_file())
    digest = hashlib.sha256()
    for path in inputs:
        digest.update(str(path.relative_to(repo)).encode())
        digest.update(path.read_bytes())
    release = home / "versions" / digest.hexdigest()[:16]
    release.parent.mkdir(exist_ok=True)
    if not release.exists():
        temporary = Path(tempfile.mkdtemp(prefix=".install-", dir=str(release.parent)))
        shutil.copytree(source / "ai_collab", temporary / "ai_collab",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(source / "ai_collab_cli.py", temporary / "ai_collab_cli.py")
        shutil.copy2(repo / "docs/ai-collaboration.md", temporary / "README.md")
        os.replace(temporary, release)
    executable = prefix / "bin/ai-collab"
    executable.parent.mkdir(parents=True, exist_ok=True)
    marker = "# managed by AIManager ai-collab installer"
    if executable.exists() and marker not in executable.read_text()[:512]:
        raise SystemExit("Refusing to replace an unrelated ai-collab command")
    target = args.skill_dir.expanduser().resolve() / "multi-model-collaboration"
    if target.exists() and not (target / ".ai-collab-managed").is_file():
        raise SystemExit("Refusing to replace an unmanaged collaboration skill")
    link = home / (".current-" + str(os.getpid()))
    link.symlink_to(release)
    os.replace(link, home / "current")
    wrapper = ("#!/usr/bin/env python3\n" + marker + "\nimport os, runpy, sys\n"
               + "os.environ.setdefault('AI_COLLAB_HOME', " + repr(str(Path.home())) + ")\n"
               + "sys.path.insert(0, " + repr(str(home / "current")) + ")\n"
               + "runpy.run_path(" + repr(str(home / "current/ai_collab_cli.py")) + ", run_name='__main__')\n")
    staged = executable.with_name(".ai-collab-" + str(os.getpid()))
    staged.write_text(wrapper)
    staged.chmod(0o755)
    os.replace(staged, executable)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = home / ("skill-backup-" + str(time.time_ns()))
        shutil.move(str(target), str(backup))
    shutil.copytree(repo / "skills/multi-model-collaboration", target)
    (target / ".ai-collab-managed").write_text(digest.hexdigest() + "\n")
    print(json.dumps({"command": str(executable), "release": str(release), "skill": str(target)}))


if __name__ == "__main__":
    main()
