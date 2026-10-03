# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models


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
        else:
            self._forced_lot_note_missing(product_id, po)
        return vals

    @api.model
    def _forced_lot_note_missing(self, product, po, on_confirm=False):
        """Прът по лот влиза в покупка БЕЗ форсиран лот — казва се (№118).

        Точката за поръчка носи лот само ако чакащите движения го носят, а
        суровото движение на МО го получава от Default Forced Lot на реда в
        рецептата. Празен ли е лотът там, покупката излиза без лот и спира
        чак при приемането — мерено на fulltest 01.10: покупка 1741 за
        ETE E 41103, 7 от 7 сурови движения без лот.

        Прът = продукт по лот с лот с дължина на прът (`bar_length_mm`, ADR-0050).
        Полето е на плъгина за разкроя — без него проверката мълчи. Една
        бележка за продукт на поръчка: има ли вече ред без лот за същия
        продукт, бележката е писана при него (сливането в него не минава оттук).
        """
        if not po or product.tracking != "lot":
            return
        Lot = self.env["stock.lot"]
        if "bar_length_mm" not in Lot._fields or not Lot.search_count(
                [("product_id", "=", product.id), ("bar_length_mm", ">", 0)],
                limit=1):
            return
        marker = "[%s]" % (product.default_code or product.id)
        if on_confirm:
            # №118 т.2: при потвърждаване редът вече е в поръчката — питаме
            # дали бележката за продукта е писана, не дали има ред без лот.
            if self.env["mail.message"].search_count([
                    ("model", "=", "purchase.order"), ("res_id", "=", po.id),
                    ("body", "ilike", marker)], limit=1):
                return
        elif po.order_line.filtered(
                lambda l: l.product_id == product and not l.forced_lot_ids):
            return
        po.message_post(body=_(
            "%(product)s %(marker)s is a bar tracked by lot, but this purchase "
            "line has no forced lot. The receipt will stop and ask for one. "
            "Check the Default Forced Lot on the bill of materials lines of "
            "this product.",
            product=product.name, marker=marker))
