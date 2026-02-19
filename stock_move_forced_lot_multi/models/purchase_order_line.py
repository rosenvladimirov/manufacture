# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    forced_lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        relation="purchase_order_line_forced_lot_rel",
        column1="line_id",
        column2="lot_id",
        string="Forced Lots",
        help="Lots that will be created/used in the incoming shipment. "
        "These lots come from the manufacturing order that triggered this purchase.",
        copy=True,
    )

    forced_lot_ids_display = fields.Char(
        string="Lots",
        compute="_compute_forced_lot_ids_display",
        store=False,
    )

    @api.depends("forced_lot_ids")
    def _compute_forced_lot_ids_display(self):
        for line in self:
            if line.forced_lot_ids:
                line.forced_lot_ids_display = ", ".join(
                    line.forced_lot_ids.mapped("name")
                )
            else:
                line.forced_lot_ids_display = ""

    def _prepare_stock_move_vals(
        self, picking, price_unit, product_uom_qty, product_uom
    ):
        """Pass forced_lot_ids to stock move when creating from PO line."""
        vals = super()._prepare_stock_move_vals(
            picking, price_unit, product_uom_qty, product_uom
        )
        if self.forced_lot_ids:
            vals["forced_lot_ids"] = [(6, 0, self.forced_lot_ids.ids)]
        return vals

    @api.model
    def _prepare_purchase_order_line_from_procurement(
        self,
        product_id,
        product_qty,
        product_uom,
        location_dest_id,
        name,
        origin,
        company_id,
        values,
        po,
    ):
        """Alternative hook for procurement values - fallback method."""
        # This method might be called in some Odoo versions/flows
        vals = super()._prepare_purchase_order_line_from_procurement(
            product_id=product_id,
            product_qty=product_qty,
            product_uom=product_uom,
            location_dest_id=location_dest_id,
            name=name,
            origin=origin,
            company_id=company_id,
            values=values,
            po=po,
        )
        forced_lot_ids = values.get("forced_lot_ids")
        if forced_lot_ids:
            if hasattr(forced_lot_ids, "ids"):
                lot_ids = forced_lot_ids.ids
            else:
                lot_ids = list(forced_lot_ids)
            vals["forced_lot_ids"] = [(6, 0, lot_ids)]

            # Build description with lot names (and refs when present)
            lot_descriptions = []
            for lot in forced_lot_ids:
                lot_desc = lot.name
                if lot.ref:
                    lot_desc += f" ({lot.ref})"
                lot_descriptions.append(lot_desc)

            if lot_descriptions:
                existing_name = vals.get("name", "")
                lot_info = "\n".join(lot_descriptions)
                vals["name"] = f"{existing_name}\n\nLots:\n{lot_info}"
        return vals


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def _prepare_picking(self):
        """Prepare picking values from PO."""
        vals = super()._prepare_picking()
        return vals
