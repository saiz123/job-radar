from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import fcntl
import yaml

from jobradar_app.config import Settings
from jobradar_app.db import connect, new_id, now_iso


class CareerOpsError(RuntimeError):
    pass


@dataclass(slots=True)
class PipelineEntry:
    url: str
    company: str
    title: str
    location: str
    note: str | None = None


@dataclass(slots=True)
class TrackerAddition:
    report_number: int
    date: str
    company: str
    via: str
    role: str
    score: str
    status: str
    pdf: str
    report: str
    notes: str


@dataclass(slots=True)
class TrackerRow:
    report_number: int
    date: str
    company: str
    via: str
    role: str
    score: str
    status: str
    pdf: str
    report: str
    notes: str


@dataclass(slots=True)
class StatusTransition:
    report_number: int
    date: str
    from_state: str
    to_state: str
    source: str
    note: str


@dataclass(slots=True)
class ScanHistoryRow:
    scanned_at: str
    source_platform: str
    company: str
    title: str
    location: str
    source_url: str
    raw_hash: str
    simhash: str
    posted_at: str


@dataclass(slots=True)
class ScanRunRow:
    started_at: str
    mode: str
    status: str
    jobs_seen: int
    jobs_added: int


@dataclass(slots=True)
class ReportRef:
    number: int
    path: Path
    company_slug: str
    report_date: str


@dataclass(slots=True)
class CareerOpsContact:
    name: str
    title: str
    email: str


@dataclass(slots=True)
class EvaluationReport:
    report_number: int
    company: str
    title: str
    score: float | None
    legitimacy: str | None
    reasons: list[str]
    concerns: list[str]
    url: str | None
    parse_confidence: str
    path: Path


class CareerOpsAdapter:
    def __init__(self, root: Path, node_bin: Path, timeout_s: int = 900, settings: Settings | None = None) -> None:
        self.root = root
        self.node_bin = node_bin
        self.timeout_s = timeout_s
        self.settings = settings
        self.run_dir = self.root / 'run'
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.run_dir / 'careerops.lock'
        self.lock_path.touch(exist_ok=True)

    def doctor_json(self) -> dict[str, Any]:
        return self._run_json('doctor.mjs', '--json')

    def stats_json(self) -> dict[str, Any]:
        return self._run_json('stats.mjs')

    def read_scan_history(self, since: date | None = None) -> list[ScanHistoryRow]:
        rows: list[ScanHistoryRow] = []
        path = self.root / 'data' / 'scan-history.tsv'
        if not path.exists():
            return rows
        for parts in self._read_tsv(path):
            if len(parts) < 9:
                continue
            row = ScanHistoryRow(*parts[:9])
            if since and row.posted_at and row.posted_at < since.isoformat():
                continue
            rows.append(row)
        return rows

    def read_scan_runs(self) -> list[ScanRunRow]:
        path = self.root / 'data' / 'scan-runs.tsv'
        if not path.exists():
            return []
        rows: list[ScanRunRow] = []
        for parts in self._read_tsv(path):
            if len(parts) < 5:
                continue
            if parts[0] == 'timestamp':
                continue
            if len(parts) >= 14:
                rows.append(ScanRunRow(parts[0], 'full', parts[1], int(parts[4]), int(parts[13])))
                continue
            rows.append(ScanRunRow(parts[0], parts[1], parts[2], int(parts[3]), int(parts[4])))
        return rows

    def list_reports(self, since: date | None = None) -> list[ReportRef]:
        refs: list[ReportRef] = []
        for path in sorted((self.root / 'reports').glob('*.md')):
            match = re.match(r'^(\d+)-(.+)-(\d{4}-\d{2}-\d{2})\.md$', path.name)
            if not match:
                continue
            report_date = match.group(3)
            if since and report_date < since.isoformat():
                continue
            refs.append(ReportRef(int(match.group(1)), path, match.group(2), report_date))
        return refs

    def read_report(self, number: int) -> EvaluationReport:
        path = self._report_path(number)
        text = path.read_text(encoding='utf-8')
        url = self._extract_header_field(text, 'URL')
        legitimacy = self._extract_header_field(text, 'Legitimacy')
        summary = self._parse_machine_summary(text)
        parse_confidence = 'full' if summary else 'partial'
        if summary:
            return EvaluationReport(
                report_number=int(summary.get('report_number', number)),
                company=str(summary.get('company', '')),
                title=str(summary.get('title', '')),
                score=float(summary['score']) if summary.get('score') is not None else None,
                legitimacy=str(summary.get('legitimacy') or legitimacy or ''),
                reasons=[str(x) for x in summary.get('reasons', [])],
                concerns=[str(x) for x in summary.get('concerns', [])],
                url=str(summary.get('url') or url or ''),
                parse_confidence=parse_confidence,
                path=path,
            )
        score_value = self._extract_header_field(text, 'Score')
        return EvaluationReport(
            report_number=number,
            company='',
            title='',
            score=float(score_value) if score_value else None,
            legitimacy=legitimacy,
            reasons=[],
            concerns=[],
            url=url,
            parse_confidence=parse_confidence,
            path=path,
        )

    def read_tracker(self) -> list[TrackerRow]:
        path = self.root / 'data' / 'applications.md'
        if not path.exists():
            return []
        rows: list[TrackerRow] = []
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.startswith('| ') or line.startswith('| # ') or line.startswith('|---'):
                continue
            parts = [p.strip() for p in line.strip('|').split('|')]
            if len(parts) < 10:
                continue
            rows.append(
                TrackerRow(
                    report_number=int(parts[0]),
                    date=parts[1],
                    company=parts[2],
                    via=parts[3],
                    role=parts[4],
                    score=parts[5],
                    status=parts[6],
                    pdf=parts[7],
                    report=parts[8],
                    notes=parts[9],
                )
            )
        return rows

    def read_status_log(self) -> list[StatusTransition]:
        path = self.root / 'data' / 'status-log.tsv'
        if not path.exists():
            return []
        rows: list[StatusTransition] = []
        for parts in self._read_tsv(path):
            if len(parts) < 6:
                continue
            rows.append(StatusTransition(int(parts[0]), parts[1], parts[2], parts[3], parts[4], parts[5]))
        return rows

    def read_contacts(self) -> list[CareerOpsContact]:
        path = self.root / 'data' / 'contacts.tsv'
        if not path.exists():
            return []
        rows: list[CareerOpsContact] = []
        for idx, parts in enumerate(self._read_tsv(path)):
            if idx == 0 and parts[:3] == ['name', 'title', 'email']:
                continue
            if len(parts) < 3:
                continue
            rows.append(CareerOpsContact(parts[0], parts[1], parts[2]))
        return rows

    def enqueue_url(self, entry: PipelineEntry) -> None:
        path = self.root / 'data' / 'pipeline.md'
        line = f'- [ ] {entry.url} | {entry.company} | {entry.title} | {entry.location}'
        if entry.note:
            line += f' | note: {entry.note}'
        text = path.read_text(encoding='utf-8') if path.exists() else '# Career-Ops Job Inbox\n\n## Pending\n\n'
        if entry.url in text:
            return
        marker = '## Pending'
        if marker in text:
            text = text.replace(marker, marker + '\n\n' + line, 1)
        else:
            text += '\n' + marker + '\n\n' + line + '\n'
        path.write_text(text, encoding='utf-8')

    def reserve_report_numbers(self, count: int) -> range:
        out = self._run_text('reserve-report-num.mjs', '--count', str(count)).strip()
        if '-' in out:
            start_s, end_s = out.split('-', 1)
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(out)
        return range(start, end + 1)

    def release_report_numbers(self, r: range) -> None:
        self._run_text('reserve-report-num.mjs', '--release', f'{r.start:03d}-{r.stop - 1:03d}')

    def add_tracker_row(self, row: TrackerAddition) -> None:
        slug = self._slugify(row.company)
        path = self.root / 'batch' / 'tracker-additions' / f'{row.report_number:03d}-{slug}.tsv'
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = '\t'.join([
            str(row.report_number), row.date, row.company, row.via, row.role,
            row.score, row.status, row.pdf, row.report, row.notes,
        ]) + '\n'
        with self._write_lock():
            path.write_text(payload, encoding='utf-8')
            self._run_text('merge-tracker.mjs')

    def set_status(self, selector: str, state: str, note: str | None = None) -> None:
        args = ['set-status.mjs', selector, state]
        if note:
            args.extend(['--note', note])
        with self._write_lock():
            self._run_text(*args)

    def archive_posting(self, url: str, report_number: int) -> Path:
        out = self._run_text('archive-posting.mjs', '--url', url, f'--report={report_number}').strip()
        return Path(out)

    def record_outcome(self, selector: str, outcome_type: str) -> None:
        with self._write_lock():
            self._run_text('outcome.mjs', selector, outcome_type)

    def sync_tracker_index(self) -> None:
        with self._write_lock():
            self._run_text('tracker.mjs', 'sync')

    def _report_path(self, number: int) -> Path:
        pattern = f'{number:03d}-*.md'
        matches = sorted((self.root / 'reports').glob(pattern))
        if not matches:
            raise CareerOpsError(f'report not found: {number}')
        return matches[0]

    def _run_json(self, script: str, *args: str) -> dict[str, Any]:
        return json.loads(self._run_text(script, *args))

    def _run_text(self, script: str, *args: str) -> str:
        argv = [str(self.node_bin), script, *args]
        started = time.time()
        proc = subprocess.run(
            argv,
            shell=False,
            cwd=self.root,
            timeout=self.timeout_s,
            capture_output=True,
            text=True,
            env=self._sanitized_env(),
        )
        duration_ms = int((time.time() - started) * 1000)
        stdout = proc.stdout[:4000]
        stderr = proc.stderr[:4000]
        self._log_run(Path(script).name, argv, proc.returncode, duration_ms, stdout, stderr)
        if proc.returncode != 0:
            raise CareerOpsError(f'{script} failed: {stderr or stdout}'.strip())
        return proc.stdout

    def _sanitized_env(self) -> dict[str, str]:
        env = {
            'PATH': os.environ.get('PATH', ''),
            'HOME': os.environ.get('HOME', ''),
            'NODE_ENV': os.environ.get('NODE_ENV', 'production'),
            'TZ': 'America/Chicago',
        }
        return env

    def _log_run(self, script_name: str, argv: list[str], exit_code: int, duration_ms: int, stdout: str, stderr: str) -> None:
        if self.settings is None:
            return
        with connect(self.settings) as conn:
            ts = now_iso()
            conn.execute(
                'INSERT INTO automation_runs (id, kind, name, argv, exit_code, duration_ms, stdout_head, stderr_head, status, started_at, finished_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    new_id(),
                    'careerops',
                    script_name,
                    json.dumps(argv),
                    exit_code,
                    duration_ms,
                    stdout,
                    stderr,
                    'completed' if exit_code == 0 else 'failed',
                    ts,
                    ts,
                    ts,
                ),
            )
            conn.commit()

    def _extract_header_field(self, text: str, field: str) -> str | None:
        match = re.search(rf'\*\*{re.escape(field)}:\*\*\s*(.+)', text)
        return match.group(1).strip() if match else None

    def _parse_machine_summary(self, text: str) -> dict[str, Any] | None:
        match = re.search(r'## Machine Summary\s*```yaml\s*(.*?)\s*```', text, re.S)
        if not match:
            return None
        data = yaml.safe_load(match.group(1))
        return data if isinstance(data, dict) else None

    def _read_tsv(self, path: Path) -> list[list[str]]:
        with path.open('r', encoding='utf-8', newline='') as handle:
            return [row for row in csv.reader(handle, delimiter='\t') if row]

    def _slugify(self, value: str) -> str:
        slug = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
        return slug or 'company'

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        with self.lock_path.open('r+', encoding='utf-8') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
