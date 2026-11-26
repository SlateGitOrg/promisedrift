-- Bridge from D1 (ERP headline) to D3 (first confirmed date), one row per line.
--
-- delta = d3 - d1 is -1 when the headline passes a line that D3 fails, +1 when D3 passes a line
-- the headline fails (a pull-in: the supplier promised earlier, then delivered on the original
-- date), and 0 when both agree. Each line with a non-zero delta gets exactly one cause, the first
-- that applies in this order:
--   early      first receipt more than 3 days before the first confirmed date
--   repromise  first receipt after the first confirmed date (headline passes only because the
--              promise moved), or, for a pull-in, a latest promise earlier than the receipt
--   partial    less than 98% received by the first confirmed date
--   other      anything else; the rules above leave it empty, it stays as a guard so that the
--              components still sum to d3 - d1 if a definition changes
-- Because every non-zero delta lands in exactly one bucket, the components sum to D3 - D1 exactly,
-- overall and for any subset of lines.
WITH joined AS (
    SELECT
        s.po_line_id,
        s.supplier_id,
        o.d1_otif,
        o.d3_otif,
        o.d3_otif - o.d1_otif AS delta,
        CASE
            WHEN o.d3_otif - o.d1_otif = 0 THEN NULL
            WHEN o.d3_otif - o.d1_otif < 0 THEN
                CASE
                    WHEN s.first_receipt_dt < s.first_confirmed_dt - 3 THEN 'early'
                    WHEN s.first_receipt_dt > s.first_confirmed_dt THEN 'repromise'
                    WHEN NOT qty_complete(s.qty_by_first_confirmed, s.ordered_qty) THEN 'partial'
                    ELSE 'other'
                END
            ELSE
                CASE
                    WHEN s.latest_promise_dt < s.first_receipt_dt THEN 'repromise'
                    ELSE 'other'
                END
        END AS cause
    FROM line_status AS s
    INNER JOIN line_otif AS o USING (po_line_id)
)
SELECT
    po_line_id,
    supplier_id,
    d1_otif,
    d3_otif,
    delta,
    cause,
    CAST(CASE WHEN cause = 'early' THEN delta ELSE 0 END AS INTEGER) AS bridge_early,
    CAST(CASE WHEN cause = 'repromise' THEN delta ELSE 0 END AS INTEGER) AS bridge_repromise,
    CAST(CASE WHEN cause = 'partial' THEN delta ELSE 0 END AS INTEGER) AS bridge_partial,
    CAST(CASE WHEN cause = 'other' THEN delta ELSE 0 END AS INTEGER) AS bridge_other
FROM joined
ORDER BY po_line_id
