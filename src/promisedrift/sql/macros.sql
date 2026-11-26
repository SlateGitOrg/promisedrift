-- Shared OTIF rules, defined once so every definition uses the same arithmetic.
--
-- A line is quantity-complete at 98% of the ordered quantity. The test is done in integers
-- (received * 100 >= 98 * ordered) so a line at exactly 98% passes and 97.9% fails, with no
-- floating-point rounding in either direction.
CREATE OR REPLACE MACRO qty_complete(received, ordered) AS received * 100 >= 98 * ordered;

-- Windowed definitions (D2-D4): the first receipt may be at most 3 days before the basis date
-- and 98% of the quantity must be in by the basis date. Arriving after the basis date fails the
-- quantity test, so the window needs no separate upper bound.
CREATE OR REPLACE MACRO otif_window(first_receipt_dt, qty_by_basis, ordered, basis_dt) AS
    first_receipt_dt >= basis_dt - 3 AND qty_complete(qty_by_basis, ordered);
