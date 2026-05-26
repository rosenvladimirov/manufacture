# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = "stock.move"

    def _get_forecast_availability_outgoing(self, warehouse, location_id=False):
        """Fallback to the MTO `move_orig_ids` chain ONLY when the forecast
        report fully drops an outgoing move that the chain will fulfill.

        Standard Odoo (stock/models/stock_move.py:2469-2490):

            result = defaultdict(lambda: (0.0, False))
            for line in forecast_lines:
                ...
                result[move_out] = (qty_expected, date_expected)
            return result

        Single failure mode covered (Case 1 — qty == 0):

        When the whole demand of an outgoing move is reconciled
        (reserved + stock + transit + incoming) inside
        `_get_report_lines`, no row is emitted for that move, so it
        keeps the defaultdict value `(0.0, False)` — read by callers as
        "Not Available" even though a confirmed/waiting incoming receipt
        is queued. UI shows fake "Not Available"; operator clears it
        with Unreserve + Check Availability.

        NOT covered (deliberately): `(qty>0, date=False)`. That tuple is
        a valid "available now from current stock" signal — overwriting
        its date with a future chain date is wrong and produces fake
        "Expected" badges (regression removed in this version).

        Warehouse scope: standard Odoo computes forecast for
        `child_of(warehouse.view_location_id)` only. The fallback MUST
        respect the same scope — summing `move_orig_ids` globally counts
        incoming receipts destined for OTHER warehouses, giving wrong
        results in multi-warehouse setups. We therefore only count orig
        moves whose `location_dest_id` is inside this warehouse's view
        location subtree.

        Behavior:

        - super() as the primary source of truth;
        - only touch moves where result is `(0.0, *)` AND the move is
          still upstream-bound (`waiting`, `confirmed`,
          `partially_available`);
        - sum `move_orig_ids.product_qty` for orig moves that are
          pending (not done/cancel) AND deliver into this warehouse's
          locations;
        - never overwrites a non-zero primary result.

        Idempotent and reversible (uninstall restores Odoo behavior).
        """
        result = super()._get_forecast_availability_outgoing(
            warehouse, location_id=location_id,
        )
        wh_location_ids = set(
            self.env["stock.location"]._search(
                [("id", "child_of", warehouse.view_location_id.id)]
            )
        )
        for move in self:
            qty, date = result.get(move, (0.0, False))
            if qty > 0:
                continue  # primary report produced a value — leave alone
            if move.state not in ("waiting", "confirmed", "partially_available"):
                continue
            if not move.move_orig_ids:
                continue
            chain_pending = move.move_orig_ids.filtered(
                lambda o: o.state not in ("done", "cancel")
                and o.location_dest_id.id in wh_location_ids
            )
            if not chain_pending:
                continue
            chain_qty = sum(chain_pending.mapped("product_qty"))
            if chain_qty <= 0:
                continue
            chain_date = max(
                (o.date for o in chain_pending if o.date),
                default=False,
            )
            result[move] = (chain_qty, date or chain_date or move.date)
            _logger.debug(
                "Forecast fallback (qty=0): move %s (%s) → qty=%s date=%s "
                "from %d in-scope orig move(s)",
                move.id, move.product_id.display_name,
                chain_qty, chain_date, len(chain_pending),
            )
        return result
