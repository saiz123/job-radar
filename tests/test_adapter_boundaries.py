from __future__ import annotations

from pathlib import Path


ROOT = Path('/home/saikali/openclaw-projects/job-hunter')
FORBIDDEN = ('import subprocess', 'from subprocess import', 'openclaw-projects/career-ops', 'career-ops')
ALLOWED_DIRS = {'careerops_adapter', 'tests'}
ALLOWED_FILES = {'run_jobradar.py'}
SCANNED_ROOTS = ['jobradar_app', 'run_jobradar.py']


def iter_targets() -> list[Path]:
    targets: list[Path] = []
    for entry in SCANNED_ROOTS:
        path = ROOT / entry
        if path.is_dir():
            targets.extend(sorted(path.rglob('*.py')))
        elif path.is_file():
            targets.append(path)
    return targets


def test_only_adapter_touches_subprocess_or_careerops_paths() -> None:
    offenders: list[str] = []
    for path in iter_targets():
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding='utf-8')
        if rel.parts[0] in ALLOWED_DIRS or rel.name in ALLOWED_FILES:
            continue
        for forbidden in FORBIDDEN:
            if forbidden in text:
                offenders.append(f'{rel}: {forbidden}')
    assert offenders == []
