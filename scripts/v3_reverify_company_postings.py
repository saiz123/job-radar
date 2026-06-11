#!/usr/bin/env python3
from __future__ import annotations

from v3_db import connect


def main() -> None:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("update leads set verification_status='pending' where verification_status='needs-review' and source like 'seed:company-posting'")
        print(cur.rowcount)
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    main()
