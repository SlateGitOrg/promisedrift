-- OTIF flag per line under the four definitions.
--   D1  ERP headline: first receipt on or before the latest promise, eventually 98% received.
--   D2  latest promise, window -3/+0 days, 98% received by the promise.
--   D3  first confirmed date, same window and quantity rule.
--   D4  requested date, same window and quantity rule.
-- A line with no receipt at all fails every definition.
SELECT
    po_line_id,
    supplier_id,
    CAST(coalesce(
        first_receipt_dt <= latest_promise_dt AND qty_complete(qty_eventual, ordered_qty),
        false) AS INTEGER) AS d1_otif,
    CAST(coalesce(
        otif_window(first_receipt_dt, qty_by_latest_promise, ordered_qty, latest_promise_dt),
        false) AS INTEGER) AS d2_otif,
    CAST(coalesce(
        otif_window(first_receipt_dt, qty_by_first_confirmed, ordered_qty, first_confirmed_dt),
        false) AS INTEGER) AS d3_otif,
    CAST(coalesce(
        otif_window(first_receipt_dt, qty_by_requested, ordered_qty, requested_dt),
        false) AS INTEGER) AS d4_otif
FROM line_status
ORDER BY po_line_id
