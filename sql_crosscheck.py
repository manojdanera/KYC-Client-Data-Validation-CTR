"""Run the SQL queries in sql/kyc_checks.sql on SQLite and confirm they match the pandas results."""
import re
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
con = sqlite3.connect(":memory:")
pd.read_csv(ROOT / "data/clients_raw.csv").to_sql("clients", con, index=False)
pd.read_csv(ROOT / "data/transactions.csv").to_sql("transactions", con, index=False)
kpi = pd.read_csv(ROOT / "data/data_quality_kpis.csv").set_index("metric")["value"]

expected = {
    "duplicate_records": kpi["check_duplicate_record"],
    "expired_id": kpi["check_expired_id"],
    "orphan_transactions": kpi["orphan_transactions"],
    "ctr_candidates": kpi["ctr_candidates"],
    "structuring_clients": kpi["structuring_alert_clients"],
}
blocks = re.split(r"-- name: (\w+)", (ROOT / "sql/kyc_checks.sql").read_text())[1:]
ok = True
for name, body in zip(blocks[::2], blocks[1::2]):
    n = con.execute(body.strip().rstrip(";")).fetchone()[0]
    if name in expected:
        match = int(n) == int(expected[name])
        ok &= match
        print(f"{name:22s} SQL={n:<6} pandas={int(expected[name]):<6} {'MATCH' if match else 'MISMATCH'}")
    else:
        print(f"{name:22s} SQL={n}")
print("ALL CHECKS MATCH" if ok else "MISMATCH FOUND")
