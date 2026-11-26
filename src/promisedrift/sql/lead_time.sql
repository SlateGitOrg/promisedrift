-- Actual lead time (order date to first receipt) against the supplier's quoted lead time, per
-- supplier and calendar quarter of the order date.
WITH actual AS (
    SELECT
        supplier_id,
        date_trunc('quarter', order_dt) AS quarter_start,
        first_receipt_dt - order_dt AS actual_days
    FROM line_status
    WHERE first_receipt_dt IS NOT NULL
)
SELECT
    a.supplier_id,
    strftime(a.quarter_start, '%Y') || '-Q' || CAST(quarter(a.quarter_start) AS VARCHAR)
        AS quarter_label,
    CAST(a.quarter_start AS DATE) AS quarter_start,
    count(*)::BIGINT AS lines,
    s.quoted_lead_days,
    round(quantile_cont(a.actual_days, 0.5), 2) AS actual_p50_days,
    round(quantile_cont(a.actual_days, 0.9), 2) AS actual_p90_days
FROM actual AS a
INNER JOIN suppliers AS s USING (supplier_id)
GROUP BY a.supplier_id, a.quarter_start, s.quoted_lead_days
ORDER BY a.supplier_id, a.quarter_start
