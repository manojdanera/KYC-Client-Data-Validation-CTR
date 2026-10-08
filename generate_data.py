"""Generate a SYNTHETIC client + transaction dataset with deliberately injected
data-quality and AML red-flag scenarios. No real or confidential data is used."""
import string
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)
DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)

AS_OF = pd.Timestamp("2025-12-31")
N = 5000

FIRST = ["Aarav", "Priya", "Rohan", "Ananya", "Vikram", "Neha", "Arjun", "Sneha", "Karan", "Meera",
         "John", "Emma", "Liam", "Olivia", "Noah", "Sophia", "Ethan", "Mia", "Lucas", "Ava"]
LAST = ["Sharma", "Patel", "Reddy", "Iyer", "Singh", "Nair", "Gupta", "Khan", "Smith", "Brown",
        "Wilson", "Taylor", "Clark", "Lewis", "Walker", "Hall", "Young", "King", "Wright", "Scott"]
COUNTRIES = ["IN", "US", "GB", "AE", "SG", "DE", "FR", "CA", "AU", "JP"]
ID_TYPES = ["Passport", "Driver License", "National ID"]

# --- unique, correctly formatted ID numbers (2 letters + 7 digits) ---
ids = set()
while len(ids) < N:
    ids.add("".join(rng.choice(list(string.ascii_uppercase), 2)) + "".join(rng.choice(list("0123456789"), 7)))
ids = list(ids)

df = pd.DataFrame({
    "client_id": [f"C{i:05d}" for i in range(1, N + 1)],
    "full_name": [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(N)],
    "dob": [(AS_OF - pd.Timedelta(days=int(d))).strftime("%Y-%m-%d") for d in rng.integers(18 * 365 + 30, 85 * 365, N)],
    "id_type": rng.choice(ID_TYPES, N),
    "id_number": ids,
    "id_expiry": [(AS_OF + pd.Timedelta(days=int(d))).strftime("%Y-%m-%d") for d in rng.integers(30, 3650, N)],
    "address": [f"{rng.integers(1, 999)} {rng.choice(['MG Road', 'Park Street', 'High Street', 'Main Avenue', 'Lake View'])}" for _ in range(N)],
    "country": rng.choice(COUNTRIES, N),
    "email": [f"user{i}@example.com" for i in range(1, N + 1)],
    "onboarding_date": [(pd.Timestamp("2015-01-01") + pd.Timedelta(days=int(d))).strftime("%Y-%m-%d") for d in rng.integers(0, 365 * 10, N)],
})


def pick(frac):
    return rng.choice(N, int(N * frac), replace=False)


# --- inject data-quality issues ---
for i in pick(0.04):                                   # missing mandatory fields
    df.loc[i, rng.choice(["full_name", "dob", "id_number", "address", "country"])] = np.nan
for i in pick(0.015):                                  # invalid ID format
    if pd.notna(df.loc[i, "id_number"]):
        d = lambda k: "".join(rng.choice(list("0123456789"), k))   # unique digits so bad IDs never collide
        df.loc[i, "id_number"] = rng.choice([f"A{d(5)}", f"{d(7)}AB", f"XY{d(2)}-{d(4)}", f"ABC{d(6)}"])
for k, i in enumerate(pick(0.012)):                    # invalid DOB (future / under 18)
    if pd.notna(df.loc[i, "dob"]):
        df.loc[i, "dob"] = (AS_OF + pd.Timedelta(days=400)).strftime("%Y-%m-%d") if k % 2 else \
                           (AS_OF - pd.Timedelta(days=365 * 10)).strftime("%Y-%m-%d")
for i in pick(0.04):                                   # expired ID documents
    df.loc[i, "id_expiry"] = (AS_OF - pd.Timedelta(days=int(rng.integers(1, 700)))).strftime("%Y-%m-%d")
for i in pick(0.02):                                   # malformed email
    df.loc[i, "email"] = df.loc[i, "email"].replace("@", "")
for i in pick(0.008):                                  # invalid country code
    df.loc[i, "country"] = "ZZ"
for i in pick(0.02):                                   # illustrative high-risk jurisdictions
    df.loc[i, "country"] = rng.choice(["IR", "KP", "MM"])

dups = df.iloc[rng.choice(N, 60, replace=False)].copy()  # duplicate client records
dups["client_id"] = [f"C{N + j:05d}" for j in range(1, len(dups) + 1)]
dups["full_name"] = dups["full_name"].str.upper()
df = pd.concat([df, dups], ignore_index=True)
client_ids = df["client_id"].tolist()

# --- transactions ---
T = 25000
tx = pd.DataFrame({
    "client_id": rng.choice(client_ids, T),
    "txn_date": [(pd.Timestamp("2025-01-01") + pd.Timedelta(days=int(d))).strftime("%Y-%m-%d") for d in rng.integers(0, 365, T)],
    "txn_type": rng.choice(["Cash Deposit", "Cash Withdrawal", "Wire", "Check"], T, p=[0.30, 0.15, 0.35, 0.20]),
    "amount": np.round(rng.lognormal(6.5, 1.1, T), 2),
})
extra = []
for c in rng.choice(client_ids, 25, replace=False):    # structuring pattern: 3 deposits just under 10k
    start = pd.Timestamp("2025-01-01") + pd.Timedelta(days=int(rng.integers(0, 350)))
    for d in range(3):
        extra.append((c, (start + pd.Timedelta(days=d)).strftime("%Y-%m-%d"), "Cash Deposit", round(float(rng.uniform(9000, 9900)), 2)))
for c in rng.choice(client_ids, 40, replace=False):    # single large cash deposits
    extra.append((c, (pd.Timestamp("2025-01-01") + pd.Timedelta(days=int(rng.integers(0, 365)))).strftime("%Y-%m-%d"),
                  "Cash Deposit", round(float(rng.uniform(10500, 60000)), 2)))
for c in rng.choice(client_ids, 30, replace=False):    # same-day deposits that aggregate above 10k
    day = (pd.Timestamp("2025-01-01") + pd.Timedelta(days=int(rng.integers(0, 365)))).strftime("%Y-%m-%d")
    extra.append((c, day, "Cash Deposit", 6000.0))
    extra.append((c, day, "Cash Deposit", 5500.0))
tx = pd.concat([tx, pd.DataFrame(extra, columns=tx.columns)], ignore_index=True)
orphans = rng.choice(len(tx), 100, replace=False)      # transactions for unknown clients
tx.loc[orphans, "client_id"] = [f"C9{int(x):04d}" for x in rng.integers(0, 9999, len(orphans))]
tx = tx.sample(frac=1, random_state=SEED).reset_index(drop=True)
tx.insert(0, "txn_id", [f"T{i:06d}" for i in range(1, len(tx) + 1)])

df.to_csv(DATA / "clients_raw.csv", index=False)
tx.to_csv(DATA / "transactions.csv", index=False)
print(f"Generated {len(df):,} client records and {len(tx):,} transactions")
