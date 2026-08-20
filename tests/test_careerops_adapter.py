from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Path:
    root = tmp_path / 'career-ops'
    for rel in ['data', 'reports', 'templates', 'batch/tracker-additions', 'bin', 'run']:
        (root / rel).mkdir(parents=True, exist_ok=True)

    (root / 'templates' / 'states.yml').write_text(
        'states:\n'
        '  - id: evaluated\n'
        '    label: Evaluated\n'
        '  - id: applied\n'
        '    label: Applied\n',
        encoding='utf-8',
    )
    (root / 'data' / 'applications.md').write_text(
        '# Career-Ops Applications\n\n'
        '| # | Date | Company | Via | Role | Score | Status | PDF | Report | Notes |\n'
        '|---|---|---|---|---|---|---|---|---|---|\n'
        '| 42 | 2026-08-13 | Acme | — | SOC Analyst I | 4.4/5 | Evaluated | ✅ | [042](../reports/042-acme-soc-analyst-i-2026-08-13.md) | initial |\n',
        encoding='utf-8',
    )
    (root / 'data' / 'pipeline.md').write_text(
        '# Career-Ops Job Inbox\n\n## Pending\n\n- [ ] https://example.com/jobs/old | Acme | SOC Analyst I | Remote\n',
        encoding='utf-8',
    )
    (root / 'data' / 'status-log.tsv').write_text(
        '42\t2026-08-13\tEvaluated\tApplied\tjobradar\tnote\n', encoding='utf-8'
    )
    (root / 'data' / 'scan-history.tsv').write_text(
        '2026-08-13\tgreenhouse\tAcme\tSOC Analyst I\tRemote\thttps://example.com/jobs/old\thash1\tsimhash1\t2026-08-12\n',
        encoding='utf-8',
    )
    (root / 'data' / 'scan-runs.tsv').write_text(
        'timestamp\tstatus\tcompanies\tboards\tfound\tfiltered_title\tfiltered_tier\tfiltered_location\tfiltered_posting_age\tfiltered_salary\tfiltered_content\tfiltered_cooldown\tdupes\tnew_added\terrors\tfiltered_blacklist\tfiltered_visa\tfiltered_posted_date\n'
        '2026-08-13T10:00:00Z\tcompleted\t0\t11\t247\t240\t0\t7\t0\t0\t0\t0\t0\t2\t0\t0\t0\t0\n',
        encoding='utf-8'
    )
    (root / 'data' / 'contacts.tsv').write_text(
        'name\ttitle\temail\nAlice Smith\tRecruiter\talice@example.com\n', encoding='utf-8'
    )
    (root / 'reports' / '042-acme-soc-analyst-i-2026-08-13.md').write_text(
        '# Report\n\n'
        '**URL:** https://example.com/jobs/42\n\n'
        '**Legitimacy:** high_confidence\n\n'
        '## Machine Summary\n'
        '```yaml\n'
        'report_number: 42\n'
        'company: Acme\n'
        'title: SOC Analyst I\n'
        'score: 4.4\n'
        'legitimacy: high_confidence\n'
        'reasons:\n'
        '  - Strong SOC title alignment\n'
        'concerns:\n'
        '  - Sponsorship unclear\n'
        'url: https://example.com/jobs/42\n'
        '```\n',
        encoding='utf-8',
    )

    node = root / 'bin' / 'node'
    node.write_text(
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "root = Path.cwd()\n"
        "script = Path(sys.argv[1]).name\n"
        "args = sys.argv[2:]\n"
        "if script == 'doctor.mjs':\n"
        "    print(json.dumps({'onboardingNeeded': False, 'missing': [], 'warnings': []}))\n"
        "elif script == 'stats.mjs':\n"
        "    print(json.dumps({'applications': 1, 'reports': 1}))\n"
        "elif script == 'reserve-report-num.mjs':\n"
        "    if '--release' in args:\n"
        "        print('released')\n"
        "    else:\n"
        "        print('043-044')\n"
        "elif script == 'set-status.mjs':\n"
        "    print('status updated')\n"
        "elif script == 'merge-tracker.mjs':\n"
        "    print('merged')\n"
        "elif script == 'tracker.mjs' and len(args) == 1 and args[0] == 'sync':\n"
        "    print('synced')\n"
        "elif script == 'outcome.mjs':\n"
        "    print('outcome recorded')\n"
        "elif script == 'archive-posting.mjs':\n"
        "    out = root / 'output' / 'archive-042.pdf'\n"
        "    out.parent.mkdir(parents=True, exist_ok=True)\n"
        "    out.write_text('pdf', encoding='utf-8')\n"
        "    print(str(out))\n"
        "else:\n"
        "    raise SystemExit(f'unsupported script: {script}')\n",
        encoding='utf-8',
    )
    node.chmod(node.stat().st_mode | stat.S_IEXEC)
    return root


def test_adapter_reads_report_parses_machine_summary_and_logs_runs(tmp_path: Path, fixture_repo: Path) -> None:
    from careerops_adapter import CareerOpsAdapter
    from jobradar_app.config import Settings
    from jobradar_app.db import migrate_to_latest, connect

    settings = Settings(
        secret_key='test-secret-key-32-bytes-minimum-value',
        password_hash='hash',
        session_dir=tmp_path / 'sessions',
        db_path=tmp_path / 'jobradar.sqlite3',
        import_dir=tmp_path / 'processed',
    )
    migrate_to_latest(settings)

    adapter = CareerOpsAdapter(
        root=fixture_repo,
        node_bin=fixture_repo / 'bin' / 'node',
        timeout_s=30,
        settings=settings,
    )

    doctor = adapter.doctor_json()
    stats = adapter.stats_json()
    tracker = adapter.read_tracker()
    report = adapter.read_report(42)

    assert doctor['onboardingNeeded'] is False
    assert stats['applications'] == 1
    assert tracker[0].report_number == 42
    assert report.report_number == 42
    assert report.score == 4.4
    assert report.legitimacy == 'high_confidence'
    assert report.url == 'https://example.com/jobs/42'
    assert report.parse_confidence == 'full'
    runs = adapter.read_scan_runs()
    assert runs[0].started_at == '2026-08-13T10:00:00Z'
    assert runs[0].status == 'completed'
    assert runs[0].jobs_seen == 247
    assert runs[0].jobs_added == 2

    with connect(settings) as conn:
        rows = conn.execute('SELECT name, argv, exit_code, status FROM automation_runs ORDER BY started_at').fetchall()
    assert len(rows) >= 2
    assert rows[0]['name'] == 'doctor.mjs'
    assert '--json' in rows[0]['argv']
    assert 'stats.mjs' in rows[1]['argv']
    assert all(row['exit_code'] == 0 for row in rows)
    assert all(row['status'] == 'completed' for row in rows)


def test_adapter_accepts_single_reserved_report_number(tmp_path: Path, fixture_repo: Path) -> None:
    from careerops_adapter import CareerOpsAdapter
    from jobradar_app.config import Settings
    from jobradar_app.db import migrate_to_latest

    node_path = fixture_repo / 'bin' / 'node'
    text = node_path.read_text(encoding='utf-8')
    text = text.replace("        print('043-044')", "        print('078')")
    node_path.write_text(text, encoding='utf-8')

    settings = Settings(
        secret_key='test-secret-key-32-bytes-minimum-value',
        password_hash='hash',
        session_dir=tmp_path / 'sessions',
        db_path=tmp_path / 'jobradar.sqlite3',
        import_dir=tmp_path / 'processed',
    )
    migrate_to_latest(settings)
    adapter = CareerOpsAdapter(
        root=fixture_repo,
        node_bin=node_path,
        timeout_s=30,
        settings=settings,
    )

    reserved = adapter.reserve_report_numbers(1)
    assert reserved.start == 78
    assert reserved.stop == 79


def test_adapter_write_surface_uses_node_commands_and_lock(tmp_path: Path, fixture_repo: Path) -> None:
    from careerops_adapter import CareerOpsAdapter, PipelineEntry, TrackerAddition
    from jobradar_app.config import Settings
    from jobradar_app.db import migrate_to_latest, connect

    settings = Settings(
        secret_key='test-secret-key-32-bytes-minimum-value',
        password_hash='hash',
        session_dir=tmp_path / 'sessions',
        db_path=tmp_path / 'jobradar.sqlite3',
        import_dir=tmp_path / 'processed',
    )
    migrate_to_latest(settings)
    adapter = CareerOpsAdapter(
        root=fixture_repo,
        node_bin=fixture_repo / 'bin' / 'node',
        timeout_s=30,
        settings=settings,
    )

    adapter.enqueue_url(PipelineEntry(url='https://example.com/jobs/new', company='Beta', title='Junior SOC Analyst', location='Remote'))
    reserved = adapter.reserve_report_numbers(2)
    adapter.release_report_numbers(reserved)
    adapter.add_tracker_row(TrackerAddition(report_number=43, date='2026-08-13', company='Beta', via='—', role='Junior SOC Analyst', score='4.0/5', status='Evaluated', pdf='❌', report='[043](../reports/043-beta-junior-soc-analyst-2026-08-13.md)', notes='queued'))
    adapter.set_status('43', 'Applied', note='human confirmed')
    adapter.sync_tracker_index()

    pipeline = (fixture_repo / 'data' / 'pipeline.md').read_text(encoding='utf-8')
    addition = (fixture_repo / 'batch' / 'tracker-additions' / '043-beta.tsv').read_text(encoding='utf-8')
    lock_path = fixture_repo / 'run' / 'careerops.lock'

    assert 'https://example.com/jobs/new' in pipeline
    assert 'Junior SOC Analyst' in addition
    assert lock_path.exists()

    with connect(settings) as conn:
        names = [row[0] for row in conn.execute('SELECT name FROM automation_runs ORDER BY started_at').fetchall()]
    assert 'reserve-report-num.mjs' in names
    assert 'set-status.mjs' in names
    assert 'merge-tracker.mjs' in names
    assert 'tracker.mjs' in names
