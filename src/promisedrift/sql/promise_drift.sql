-- Promise movement per line: how many times the promise changed and how far the latest promise
-- sits from the first confirmed date (positive = pushed out, negative = pulled in).
SELECT
    po_line_id,
    supplier_id,
    n_repromise,
    latest_promise_dt - first_confirmed_dt AS drift_days
FROM line_status
ORDER BY po_line_id
