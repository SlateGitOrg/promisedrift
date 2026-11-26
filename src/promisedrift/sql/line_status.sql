-- One row per PO line: the three dates a line can be judged against, the first receipt, and the
-- quantity in hand at each basis date.
--
-- latest_promise_dt is the new date of the highest change_seq in the promise-change log, or the
-- first confirmed date when the log has no entry for the line.
WITH latest AS (
    SELECT
        po_line_id,
        count(*) AS n_repromise,
        arg_max(new_promise_dt, change_seq) AS latest_promise_dt
    FROM promise_changes
    GROUP BY po_line_id
),
basis AS (
    SELECT
        l.po_line_id,
        l.supplier_id,
        l.order_dt,
        l.requested_dt,
        l.first_confirmed_dt,
        coalesce(c.latest_promise_dt, l.first_confirmed_dt) AS latest_promise_dt,
        coalesce(c.n_repromise, 0) AS n_repromise,
        l.ordered_qty
    FROM po_lines AS l
    LEFT JOIN latest AS c USING (po_line_id)
),
received AS (
    SELECT
        b.po_line_id,
        min(r.receipt_dt) AS first_receipt_dt,
        max(r.receipt_dt) AS last_receipt_dt,
        count(*) AS n_receipts,
        sum(r.qty_received) AS qty_eventual,
        sum(CASE WHEN r.receipt_dt <= b.requested_dt THEN r.qty_received ELSE 0 END)
            AS qty_by_requested,
        sum(CASE WHEN r.receipt_dt <= b.first_confirmed_dt THEN r.qty_received ELSE 0 END)
            AS qty_by_first_confirmed,
        sum(CASE WHEN r.receipt_dt <= b.latest_promise_dt THEN r.qty_received ELSE 0 END)
            AS qty_by_latest_promise
    FROM basis AS b
    INNER JOIN receipts AS r USING (po_line_id)
    GROUP BY b.po_line_id
)
SELECT
    b.po_line_id,
    b.supplier_id,
    s.commodity,
    b.order_dt,
    b.requested_dt,
    b.first_confirmed_dt,
    b.latest_promise_dt,
    b.n_repromise,
    rc.first_receipt_dt,
    rc.last_receipt_dt,
    coalesce(rc.n_receipts, 0)::BIGINT AS n_receipts,
    b.ordered_qty,
    coalesce(rc.qty_eventual, 0)::BIGINT AS qty_eventual,
    coalesce(rc.qty_by_requested, 0)::BIGINT AS qty_by_requested,
    coalesce(rc.qty_by_first_confirmed, 0)::BIGINT AS qty_by_first_confirmed,
    coalesce(rc.qty_by_latest_promise, 0)::BIGINT AS qty_by_latest_promise
FROM basis AS b
INNER JOIN suppliers AS s USING (supplier_id)
LEFT JOIN received AS rc USING (po_line_id)
ORDER BY b.po_line_id
