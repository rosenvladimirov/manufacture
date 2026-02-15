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

    def _prepare_purchase_order_line(
        self, product_id, product_qty, product_uom, company_id, values, po
    ):
        """Pass forced_lot_ids to purchase order line."""
        line_values = super()._prepare_purchase_order_line(
            product_id, product_qty, product_uom, company_id, values, po
        )

        forced_lot_ids = values.get("forced_lot_ids")
        if forced_lot_ids:
            line_values["forced_lot_ids"] = [(6, 0, forced_lot_ids.ids)]

            # Build description with lot names
            lot_descriptions = []
            for lot in forced_lot_ids:
                lot_desc = lot.name
                if lot.ref:
                    lot_desc += f" ({lot.ref})"
                lot_descriptions.append(lot_desc)

            if lot_descriptions:
                existing_name = line_values.get("name", "")
                lot_info = "\n".join(lot_descriptions)
                line_values["name"] = f"{existing_name}\n\nLots:\n{lot_info}"

        return line_values

    def _run_buy(self, procurements):
        """Ensure forced_lot_ids are passed through buy rule."""
        # The parent method will call _prepare_purchase_order_line
        # which we've already overridden above
        return super()._run_buy(procurements)
