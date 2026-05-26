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
            line.forced_lot_ids_display = (
                ", ".join(line.forced_lot_ids.mapped("name"))
                if line.forced_lot_ids
                else ""
            )

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

    def _find_candidate(self, product_id, product_qty, product_uom,
                        location_id, name, origin, company_id, values):
        """Prevent cross-batch merging of different forced-lot sets.

        Core ``_find_candidate`` only checks product + orderpoint + description,
        so a procurement carrying lot B will merge into an existing PO line
        that was created for lot A of the same product. When any incoming lot
        has ``po_split=True`` we restrict the candidate search to PO lines
        whose ``forced_lot_ids`` set is identical — forcing a new line instead.
        Lots without ``po_split`` keep the stock behavior (backward-compatible).
        """
        incoming = values.get("forced_lot_ids")
        if incoming is None:
            return super()._find_candidate(
                product_id, product_qty, product_uom,
                location_id, name, origin, company_id, values,
            )
        if hasattr(incoming, "_name"):
            lots = incoming
        else:
            lots = self.env["stock.lot"].browse(list(incoming))
        if not any(lots.mapped("po_split")):
            return super()._find_candidate(
                product_id, product_qty, product_uom,
                location_id, name, origin, company_id, values,
            )
        incoming_key = frozenset(lots.ids)
        candidates = self.filtered(
            lambda l: frozenset(l.forced_lot_ids.ids) == incoming_key
        )
        return super(PurchaseOrderLine, candidates)._find_candidate(
            product_id, product_qty, product_uom,
            location_id, name, origin, company_id, values,
        )

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
            lot_ids = (
                forced_lot_ids.ids
                if hasattr(forced_lot_ids, "ids")
                else list(forced_lot_ids)
            )
            vals["forced_lot_ids"] = [(6, 0, lot_ids)]

            if hasattr(forced_lot_ids, "mapped"):
                descriptions = []
                for lot in forced_lot_ids:
                    desc = lot.name
                    if lot.ref:
                        desc += f" ({lot.ref})"
                    descriptions.append(desc)
                if descriptions:
                    existing_name = vals.get("name", "")
                    vals["name"] = (
                        f"{existing_name}\n\nLots:\n" + "\n".join(descriptions)
                    )
        return vals
