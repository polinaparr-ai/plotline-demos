"""./pl: run any step of the project from the IDE terminal.

  ./pl tables                         list warehouse tables
  ./pl sql 5_sql/region_yoy.sql       run a SQL file (or a quoted query) against the warehouse
  ./pl run 6_python/stamp_duty_pullforward.py
  ./pl refresh                        get the latest Land Registry release, rebuild, republish
  ./pl publish                        build the dashboard into 8_published/
  ./pl serve                          start the dashboard and assistant
"""
from __future__ import annotations

import pathlib
import runpy
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def next_release(after):
    """Land Registry publishes Price Paid Data on the 20th working day of each month (bank holidays can shift it)."""
    import datetime as dt
    y, m = after.year, after.month
    for _ in range(2):
        d, n = dt.date(y, m, 1), 0
        while True:
            if d.weekday() < 5:
                n += 1
                if n == 20:
                    break
            d += dt.timedelta(days=1)
        if d > after:
            return d
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return d


def refresh() -> None:
    import datetime as dt
    import email.utils
    import json
    ingest = runpy.run_path(str(ROOT / "1_data" / "ingest.py"))
    changed = ingest["download"]()
    if changed:
        ingest["build"]()
        ingest["write_samples"]()
        from plotline import publish
        publish.publish()
    release = json.loads((ROOT / "1_data" / "raw" / "release.json").read_text())
    latest = max(email.utils.parsedate_to_datetime(v).date() for v in release.values())
    from plotline import policy
    last_sale = policy.connect().execute("SELECT max(sale_date) FROM analytics.sales").fetchone()[0]
    state = "Updated" if changed else "Already up to date"
    print(f"{state}: Land Registry release of {latest:%-d %b %Y}, sales to {last_sale:%-d %b %Y}. "
          f"Next release expected {next_release(dt.date.today()):%a %-d %b %Y}.")
    if changed:
        print("Restart ./run.sh to serve the new data.")


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, args = argv[0], argv[1:]
    if cmd in ("sql", "tables"):
        from plotline import policy
        con = policy.connect()
        if cmd == "tables":
            con.sql("""SELECT schema_name || '.' || table_name AS "table", estimated_size AS rows, column_count AS columns
                       FROM duckdb_tables() ORDER BY schema_name DESC, table_name""").show()
            return
        src = args[0]
        query = (ROOT / src).read_text() if (ROOT / src).is_file() else src
        rel = con.sql(query.strip().rstrip(";"))
        n = rel.aggregate("count(*)").fetchone()[0]
        rel.limit(20).show(max_width=180)
        print(f"{n:,} rows" + (" (first 20 shown)" if n > 20 else ""))
    elif cmd == "run":
        runpy.run_path(str(ROOT / args[0]), run_name="__main__")
    elif cmd == "refresh":
        refresh()
    elif cmd == "publish":
        from plotline import publish
        publish.publish()
    elif cmd == "serve":
        from plotline import server
        server.main()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
