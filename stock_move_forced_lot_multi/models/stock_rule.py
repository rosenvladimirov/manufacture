# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, models


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
        """Propagate forced_lot_ids from procurement to the stock move."""
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
        forced_lots = values.get("forced_lot_ids")
        if forced_lots:
            lot_ids = forced_lots.ids if hasattr(forced_lots, "ids") else list(forced_lots)
            move_values["forced_lot_ids"] = [(6, 0, lot_ids)]
        return move_values

    @api.model
    def _get_procurements_to_merge_groupby(self, procurement):
        """Prevent merging procurements with different forced_lot_ids."""
        base_key = super()._get_procurements_to_merge_groupby(procurement)
        forced_lot_ids = procurement.values.get("forced_lot_ids")
        if forced_lot_ids:
            ids = forced_lot_ids.ids if hasattr(forced_lot_ids, "ids") else list(forced_lot_ids)
            lot_key = frozenset(ids)
        else:
            lot_key = frozenset()
        if not isinstance(base_key, tuple):
            base_key = (base_key,)
        return base_key + (lot_key,)

    def _update_purchase_order_line(
        self, product_id, product_qty, product_uom, company_id, values, line
    ):
        """Add forced_lot_ids from values to the existing PO line on merge.

        Core Odoo's ``_update_purchase_order_line`` only carries ``product_qty``,
        ``price_unit`` and ``move_dest_ids`` forward — forced lots from the
        incoming procurement would be dropped. Here we append them to the
        line (Command.link, so existing lots stay) and extend ``name`` with
        the new lot descriptions if they aren't already listed.
        """
        res = super()._update_purchase_order_line(
            product_id, product_qty, product_uom, company_id, values, line
        )
        forced_lot_ids = values.get("forced_lot_ids")
        if not forced_lot_ids:
            return res
        if hasattr(forced_lot_ids, "ids"):
            lots = forced_lot_ids
            lot_ids = forced_lot_ids.ids
        else:
            lot_ids = list(forced_lot_ids)
            lots = self.env["stock.lot"].browse(lot_ids)
        new_lot_ids = [lid for lid in lot_ids if lid not in line.forced_lot_ids.ids]
        if not new_lot_ids:
            return res
        res["forced_lot_ids"] = [(4, lid) for lid in new_lot_ids]
        new_lots = lots.filtered(lambda l: l.id in new_lot_ids)
        descriptions = []
        for lot in new_lots:
            desc = lot.name
            if lot.ref:
                desc += f" ({lot.ref})"
            descriptions.append(desc)
        if descriptions:
            existing_name = line.name or ""
            if "\nLots:\n" in existing_name:
                res["name"] = existing_name + "\n" + "\n".join(descriptions)
            else:
                res["name"] = existing_name + "\n\nLots:\n" + "\n".join(descriptions)
        return res
