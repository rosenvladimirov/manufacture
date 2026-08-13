# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = "stock.move"

    def _get_forecast_availability_outgoing(self, warehouse, location_id=False):
        """Derive forecast for MTO moves from their `move_orig_ids` chain
        instead of the global forecast report allocation.

        Why
        ---
        Standard Odoo computes the per-move forecast via
        `stock.forecasted_product_product._get_report_lines`, which
        reconciles ALL outgoing demands of a product against ALL incoming
        receipts in the warehouse, chronologically
        (stock/models/stock_move.py:_get_forecast_availability_outgoing,
        ~2469-2490).

        For a 3-step manufacturing MTO chain this allocation is
        non-deterministic at the per-move level: several identical raw
        moves, all fully reserved by their own origs, get paired with a
        `move_in` (→ a future `date_expected`) or not, essentially at
        random, because incoming == demand on the same date (`date_start`).
        Result: the MO `forecast_widget` flickers identical, fully-reserved
        components between "Available" (green) and "Exp DATE" (orange),
        while a genuinely unreserved component (origs still `waiting`,
        qty=0) can be masked as "Available". The badge stops correlating
        with the real chain state. (Reported MO/00655, db dev-teo-2305,
        2026-05-29; earlier MO 493-500 / S00216, 2026-05-13.)

        For an MTO move the only meaningful source of truth is its own
        chain — the origs that physically feed it — not the global product
        forecast. So for such moves we replace the report's value with one
        derived from the chain.

        Scope guard
        -----------
        We only override moves that are BOTH `make_to_order` AND have
        `move_orig_ids` AND are still upstream-bound (`waiting`,
        `confirmed`, `partially_available`). Non-MTO moves keep super()'s
        result untouched — their `(qty>0, date=False)` "available from
        current stock" semantics are valid and must not be overwritten
        (the v3 regression).

        Warehouse scope
        ---------------
        Standard Odoo computes forecast for
        `child_of(warehouse.view_location_id)` only. We respect the same
        scope: only origs delivering into this warehouse's view-location
        subtree count, so multi-warehouse setups are not cross-counted.

        Derivation (per move, same product, in-scope origs)
        ---------------------------------------------------
        - ready_qty = Σ product_qty of origs in state `assigned`/`done`
          (reserved or already arrived → physically committed to us);
        - chain_qty = Σ product_qty of origs not `cancel`
          (everything the chain is planned to deliver);
        - expected_date = max scheduled date among pending (non-done,
          non-cancel) origs, falling back to the move's own date.

        Then:
        - ready_qty >= demand        → (demand, False)          "Available"
        - chain_qty >= demand        → (demand, expected_date)  "Exp DATE"
        - chain_qty  > 0             → (ready_qty, expected_date) partial
                                                                "Not Available"
        - otherwise                  → leave super()'s value

        This is deterministic (depends only on the move's own chain),
        subsumes the old qty==0 fallback, fixes the flicker, and unmasks
        unreserved components. Idempotent and reversible (uninstall
        restores Odoo behavior).
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
            if move.procure_method != "make_to_order":
                continue
            if move.state not in ("waiting", "confirmed", "partially_available"):
                continue
            if not move.move_orig_ids:
                continue

            demand = move.product_qty
            in_scope = move.move_orig_ids.filtered(
                lambda o: o.product_id == move.product_id
                and o.state != "cancel"
                and o.location_dest_id.id in wh_location_ids
            )
            if not in_scope:
                continue

            ready_qty = sum(
                o.product_qty
                for o in in_scope
                if o.state in ("assigned", "done")
            )
            chain_qty = sum(in_scope.mapped("product_qty"))
            pending = in_scope.filtered(lambda o: o.state != "done")
            expected_date = max(
                (o.date for o in pending if o.date),
                default=False,
            ) or move.date

            if ready_qty >= demand:
                new_value = (demand, False)
            elif chain_qty >= demand:
                new_value = (demand, expected_date)
            elif chain_qty > 0:
                new_value = (ready_qty, expected_date)
            else:
                continue

            if result.get(move, (0.0, False)) != new_value:
                _logger.debug(
                    "Forecast chain-override: move %s (%s) %s → %s "
                    "[ready=%s chain=%s demand=%s, %d in-scope orig(s)]",
                    move.id, move.product_id.display_name,
                    result.get(move), new_value,
                    ready_qty, chain_qty, demand, len(in_scope),
                )
            result[move] = new_value
        return result
