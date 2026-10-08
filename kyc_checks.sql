-- KYC data-quality and CTR queries (SQLite syntax; MySQL notes inline).
-- Tables: clients(client_id, full_name, dob, id_type, id_number, id_expiry, address, country, email, onboarding_date)
--         transactions(txn_id, client_id, txn_date, txn_type, amount)
-- As-of date: 2025-12-31. CTR threshold: 10,000 cash in or out per client per day.

-- name: missing_mandatory
SELECT COUNT(*) AS n FROM clients
WHERE full_name IS NULL OR dob IS NULL OR id_number IS NULL OR address IS NULL OR country IS NULL;

-- name: duplicate_records
SELECT COUNT(*) - COUNT(DISTINCT id_number) AS n FROM clients WHERE id_number IS NOT NULL;

-- name: expired_id
SELECT COUNT(*) AS n FROM clients WHERE id_expiry < '2025-12-31';

-- name: orphan_transactions
SELECT COUNT(*) AS n
FROM transactions t LEFT JOIN clients c ON t.client_id = c.client_id
WHERE c.client_id IS NULL;

-- name: ctr_candidates
SELECT COUNT(*) AS n FROM (
    SELECT client_id, txn_date, txn_type
    FROM transactions
    WHERE txn_type IN ('Cash Deposit', 'Cash Withdrawal')
    GROUP BY client_id, txn_date, txn_type
    HAVING SUM(amount) > 10000
);

-- name: structuring_clients
-- (MySQL: replace julianday differences with DATEDIFF(txn_date, LAG(txn_date) OVER (...)))
SELECT COUNT(DISTINCT client_id) AS n FROM (
    SELECT client_id,
           julianday(txn_date) - julianday(LAG(txn_date) OVER (PARTITION BY client_id ORDER BY txn_date)) AS gap
    FROM transactions
    WHERE txn_type = 'Cash Deposit' AND amount BETWEEN 9000 AND 9999.99
)
WHERE gap <= 3;
