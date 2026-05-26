# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class StockRule(models.Model):
    _inherit = "stock.rule"

    def _get_stock_move_values(
        self,
        product_id,
        product_qty,
        product_uom,
        location_dest_id,
        name,
        origin,
        company_id,
        values,
    ):
        """Pass forced_lot_ids from procurement to stock move."""
        move_values = super()._get_stock_move_values(
            product_id,
            product_qty,
            product_uom,
            location_dest_id,
            name,
            origin,
            company_id,
            values,
        )
        # Propagate forced_lot_ids if present in procurement values
        if values.get("forced_lot_ids"):
            move_values["forced_lot_ids"] = [
                (6, 0, values["forced_lot_ids"].ids)
            ]
        return move_values
