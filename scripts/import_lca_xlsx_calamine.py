#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from python_calamine import load_workbook  # noqa: E402
from jobradar_app.config import get_settings  # noqa: E402
from jobradar_app.db import connect, migrate_to_latest, new_id, now_iso  # noqa: E402
from scripts.import_sponsorship_data import refresh_current_jobs, _normalize_company_name  # noqa: E402


def val(row, idx):
    if idx is None or idx >= len(row):
        return ""
    v = row[idx]
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.isoformat()[:10]
    return str(v).strip()


def num(row, idx):
    raw = val(row, idx).replace(',', '')
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Fast import DOL LCA XLSX via python-calamine")
    ap.add_argument('xlsx', type=Path)
    ap.add_argument('--fiscal-year', type=int, required=True)
    ap.add_argument('--source-url', default='')
    ap.add_argument('--replace-fiscal-year', action='store_true')
    ap.add_argument('--batch-size', type=int, default=10000)
    args = ap.parse_args()
    settings = get_settings(); migrate_to_latest(settings)
    source = args.source_url or str(args.xlsx)
    loaded_at = now_iso()

    wb = load_workbook(str(args.xlsx))
    sheet = wb.get_sheet_by_index(0)
    it = sheet.iter_rows()
    headers = [str(x).strip().upper() if x is not None else '' for x in next(it)]
    def ix(*names: str):
        for name in names:
            name = name.upper()
            if name in headers:
                return headers.index(name)
        return None
    cols = {
        'employer': ix('EMPLOYER_NAME'),
        'job_title': ix('JOB_TITLE'),
        'soc_code': ix('SOC_CODE'),
        'wage_rate_from': ix('WAGE_RATE_OF_PAY_FROM', 'WAGE_RATE_OF_PAY_FROM_1'),
        'wage_unit': ix('WAGE_UNIT_OF_PAY', 'WAGE_UNIT_OF_PAY_1'),
        'wage_level': ix('PW_WAGE_LEVEL', 'PW_WAGE_LEVEL_1'),
        'worksite_city': ix('WORKSITE_CITY', 'WORKSITE_CITY_1'),
        'worksite_state': ix('WORKSITE_STATE', 'WORKSITE_STATE_1'),
        'case_status': ix('CASE_STATUS'),
        'decision_date': ix('DECISION_DATE'),
    }
    print({'height': sheet.height, 'width': sheet.width, 'columns': cols}, flush=True)
    inserted = 0
    batch = []
    with connect(settings) as conn:
        if args.replace_fiscal_year:
            deleted = conn.execute('DELETE FROM lca_records WHERE fiscal_year = ?', (args.fiscal_year,)).rowcount
            conn.commit()
            print({'deleted_existing_fy_rows': deleted}, flush=True)
        for row in it:
            employer = val(row, cols['employer'])
            if not employer:
                continue
            batch.append((
                new_id(), args.fiscal_year, None, _normalize_company_name(employer),
                val(row, cols['job_title']), val(row, cols['soc_code']), num(row, cols['wage_rate_from']),
                val(row, cols['wage_unit']), val(row, cols['wage_level']), val(row, cols['worksite_city']),
                val(row, cols['worksite_state']), val(row, cols['case_status']), val(row, cols['decision_date']),
                loaded_at, source,
            ))
            if len(batch) >= args.batch_size:
                conn.executemany("""
                  INSERT INTO lca_records (id, fiscal_year, quarter, employer_name_normalized, job_title, soc_code,
                    wage_rate_from, wage_unit, wage_level, worksite_city, worksite_state,
                    case_status, decision_date, loaded_at, source_url)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, batch)
                conn.commit()
                inserted += len(batch); batch.clear()
                if inserted % 100000 == 0:
                    print({'inserted': inserted}, flush=True)
        if batch:
            conn.executemany("""
              INSERT INTO lca_records (id, fiscal_year, quarter, employer_name_normalized, job_title, soc_code,
                wage_rate_from, wage_unit, wage_level, worksite_city, worksite_state,
                case_status, decision_date, loaded_at, source_url)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            conn.commit()
            inserted += len(batch)
    refreshed = refresh_current_jobs()
    print({'lca_rows': inserted, **refreshed})
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
