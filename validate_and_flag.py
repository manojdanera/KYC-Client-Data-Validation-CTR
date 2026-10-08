"""Validate client (KYC) records and flag Currency Transaction Report (CTR) candidates
and possible structuring. Writes cleaned data, exception logs and KPIs."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AS_OF = pd.Timestamp("2025-12-31")
CTR_THRESHOLD = 10_000
MANDATORY = ["full_name", "dob", "id_number", "address", "country"]
VALID_COUNTRIES = {"IN", "US", "GB", "AE", "SG", "DE", "FR", "CA", "AU", "JP", "IR", "KP", "MM"}
HIGH_RISK = {"IR", "KP", "MM"}   # illustrative list for enhanced due diligence review

clients = pd.read_csv(DATA / "clients_raw.csv", dtype=str)
tx = pd.read_csv(DATA / "transactions.csv", dtype={"client_id": str})

# ------------------------------------------------------------------ client checks
dob = pd.to_datetime(clients["dob"], errors="coerce")
expiry = pd.to_datetime(clients["id_expiry"], errors="coerce")
age = (AS_OF - dob).dt.days / 365.25

f = pd.DataFrame(index=clients.index)
f["missing_mandatory"] = clients[MANDATORY].isna().any(axis=1)
f["duplicate_record"] = clients["id_number"].notna() & clients.duplicated("id_number", keep="first")
f["invalid_id_format"] = clients["id_number"].notna() & ~clients["id_number"].str.match(r"^[A-Z]{2}\d{7}$", na=False)
f["invalid_dob"] = dob.notna() & ((dob > AS_OF) | (age < 18))
f["expired_id"] = expiry < AS_OF
f["invalid_country"] = clients["country"].notna() & ~clients["country"].isin(VALID_COUNTRIES)
f["invalid_email"] = clients["email"].notna() & ~clients["email"].str.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", na=False)
f["high_risk_country"] = clients["country"].isin(HIGH_RISK)   # review flag, not a data error

BLOCKING = ["missing_mandatory", "duplicate_record", "invalid_id_format", "invalid_dob", "expired_id", "invalid_country"]
SEVERITY = {"missing_mandatory": "Critical", "duplicate_record": "Critical", "invalid_id_format": "Critical",
            "invalid_dob": "Critical", "expired_id": "High", "invalid_country": "High",
            "invalid_email": "Low", "high_risk_country": "Review (EDD)"}
f["has_blocking_issue"] = f[BLOCKING].any(axis=1)

# exceptions log (one row per client per issue)
rows = []
for col, sev in SEVERITY.items():
    for i in clients.index[f[col]]:
        detail = ", ".join(c for c in MANDATORY if pd.isna(clients.loc[i, c])) if col == "missing_mandatory" else ""
        rows.append((clients.loc[i, "client_id"], col, sev, detail))
exceptions = pd.DataFrame(rows, columns=["client_id", "issue", "severity", "detail"])
exceptions.to_csv(DATA / "exceptions_clients.csv", index=False)

# cleaned file: de-duplicated, standardised, with a review status for the client-facing team
clean = clients.copy()
clean["full_name"] = clean["full_name"].str.strip().str.title()
clean["id_number"] = clean["id_number"].str.strip().str.upper()
clean["issues"] = [", ".join(c for c in list(SEVERITY) if f.loc[i, c]) for i in clients.index]
clean["review_status"] = f["has_blocking_issue"].map({True: "Escalate", False: "Ready"})
clean = clean[~f["duplicate_record"]]
clean.to_csv(DATA / "clients_clean.csv", index=False)

# ------------------------------------------------------------------ transaction checks
known = set(clients["client_id"])
orphan = ~tx["client_id"].isin(known)
cash = tx[tx["txn_type"].isin(["Cash Deposit", "Cash Withdrawal"])]
daily = (cash.groupby(["client_id", "txn_date", "txn_type"])
             .agg(total_cash=("amount", "sum"), txn_count=("amount", "size")).reset_index())
ctr = daily[daily["total_cash"] > CTR_THRESHOLD].copy()
ctr["total_cash"] = ctr["total_cash"].round(2)
bad_clients = set(clients.loc[f["has_blocking_issue"], "client_id"])
ctr["client_data_status"] = ctr["client_id"].map(
    lambda c: "Unknown client" if c not in known else ("Incomplete/invalid - fix first" if c in bad_clients else "Ready to file"))
ctr.to_csv(DATA / "ctr_candidates.csv", index=False)

near = tx[(tx["txn_type"] == "Cash Deposit") & tx["amount"].between(9000, 9999.99)].copy()
near["txn_date"] = pd.to_datetime(near["txn_date"])
near = near.sort_values(["client_id", "txn_date"])
near["gap"] = near.groupby("client_id")["txn_date"].diff().dt.days
struct_clients = near.loc[near["gap"] <= 3, "client_id"].unique()
struct = (near[near["client_id"].isin(struct_clients)].groupby("client_id")
          .agg(deposits_near_threshold=("amount", "size"), total=("amount", "sum"),
               first_date=("txn_date", "min"), last_date=("txn_date", "max")).reset_index())
struct["total"] = struct["total"].round(2)
struct.to_csv(DATA / "structuring_alerts.csv", index=False)

# ------------------------------------------------------------------ KPIs
n = len(clients)
kpi = {
    "total_client_records": n,
    "unique_clients_after_dedup": n - int(f["duplicate_record"].sum()),
    "mandatory_field_completeness_pct": round(100 * (1 - clients[MANDATORY].isna().sum().sum() / (n * len(MANDATORY))), 2),
    "records_with_blocking_issue": int(f["has_blocking_issue"].sum()),
    "records_with_blocking_issue_pct": round(100 * f["has_blocking_issue"].mean(), 2),
    "records_passing_all_checks_pct": round(100 * (~f["has_blocking_issue"]).mean(), 2),
}
for col in list(SEVERITY):
    kpi[f"check_{col}"] = int(f[col].sum())
kpi.update({
    "total_transactions": len(tx),
    "orphan_transactions": int(orphan.sum()),
    "ctr_candidates": len(ctr),
    "ctr_ready_to_file": int((ctr["client_data_status"] == "Ready to file").sum()),
    "ctr_blocked_by_client_data_or_unknown": int((ctr["client_data_status"] != "Ready to file").sum()),
    "structuring_alert_clients": len(struct),
})
pd.Series(kpi, name="value").rename_axis("metric").reset_index().to_csv(DATA / "data_quality_kpis.csv", index=False)
for k, v in kpi.items():
    print(f"{k:45s} {v}")
