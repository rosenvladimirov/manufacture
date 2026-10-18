# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    lot_width = fields.Float(string="Lot Width")
    lot_height = fields.Float(string="Lot Height")
    lot_thickness = fields.Float(string="Lot Thickness")
    lot_pcs_qty = fields.Float(
        string="Pieces (calc.)",
        compute="_compute_lot_pcs_qty",
        help="Calculated pieces from m² or bar length, based on lot dimensions.",
    )

    # ------------------------------------------------------------------
    # Мерни единици (19: без uom.category — роднините се познават по
    # общата референтна единица, relative_uom_id / parent_path)
    # ------------------------------------------------------------------
    @api.model
    def _get_square_meter_uom(self):
        """Връща m² по xmlid на 19 (uom.product_uom_square_meter).

        В 18 същият запис беше uom.uom_square_meter; пазим го като резервен
        вариант за мигрирани бази, където xmlid-ът не е преименуван.
        """
        return self.env.ref(
            "uom.product_uom_square_meter", raise_if_not_found=False
        ) or self.env.ref("uom.uom_square_meter", raise_if_not_found=False)

    @api.model
    def _get_meter_uom(self):
        """Връща m (xmlid-ът е еднакъв в 18 и 19)."""
        return self.env.ref("uom.product_uom_meter", raise_if_not_found=False)

    @api.model
    def _uom_is_related(self, uom, ref_uom):
        """True ако uom и ref_uom са от едно семейство (обща референция).

        Заменя сравнението по category_id от 18. В 19 _compute_quantity НЕ
        вдига грешка при несъвместими единици, затова проверката е
        задължителна преди всяко преобразуване.
        """
        if not uom or not ref_uom:
            return False
        return uom._has_common_reference(ref_uom)

    @api.model
    def _prepare_purchase_order_line_from_procurement(
        self, product_id, product_qty, product_uom, location_dest_id,
        name, origin, company_id, values, po,
    ):
        """SET product_qty = lot total m² при създаване на нова PO линия за
        po_split лотове.

        Симетричен с stock.rule._update_purchase_order_line override-а:
        и двете точки (нова линия + update съществуваща) трябва да се
        държат идентично, иначе първият procurement би създал линия с
        procurement_qty, а следващите ще я set-ват към lot total — race
        според реда на confirmation.
        """
        vals = super()._prepare_purchase_order_line_from_procurement(
            product_id, product_qty, product_uom, location_dest_id,
            name, origin, company_id, values, po,
        )
        forced_lot_ids = values.get("forced_lot_ids")
        if not forced_lot_ids:
            return vals
        if hasattr(forced_lot_ids, "_name"):
            lots = forced_lot_ids
        else:
            lots = self.env["stock.lot"].browse(list(forced_lot_ids))
        total_area = self.env["stock.rule"]._po_split_total_area(lots)
        if total_area is not None:
            vals["product_qty"] = total_area
        return vals

    @api.depends(
        "product_qty",
        "product_uom_id",
        "forced_lot_ids",
        "forced_lot_ids.width",
        "forced_lot_ids.height",
        "lot_width",
        "lot_height",
    )
    def _compute_lot_pcs_qty(self):
        square_meter_uom = self._get_square_meter_uom()
        meter_uom = self._get_meter_uom()

        for line in self:
            if not line.product_uom_id:
                line.lot_pcs_qty = 0.0
                continue

            lot_area_sqm = 0.0
            lots = line.forced_lot_ids.filtered(lambda l: l.width and l.height)
            if lots:
                areas = {(lot.width * lot.height) / 1_000_000 for lot in lots}
                if len(areas) == 1:
                    lot_area_sqm = areas.pop()
            elif line.lot_width and line.lot_height:
                lot_area_sqm = (line.lot_width * line.lot_height) / 1_000_000
            lot_width = 0.0
            lot_height = 0.0
            if line.forced_lot_ids:
                lots_with_dims = line.forced_lot_ids.filtered(lambda l: l.width and l.height)
                if lots_with_dims:
                    width_values = {lot.width for lot in lots_with_dims}
                    height_values = {lot.height for lot in lots_with_dims}
                    if len(width_values) == 1:
                        lot_width = width_values.pop()
                    if len(height_values) == 1:
                        lot_height = height_values.pop()
            if not lot_width:
                lot_width = line.lot_width or 0.0
            if not lot_height:
                lot_height = line.lot_height or 0.0

            if self._uom_is_related(line.product_uom_id, square_meter_uom):
                if not lot_area_sqm:
                    line.lot_pcs_qty = 0.0
                    continue

                qty_sqm = line.product_uom_id._compute_quantity(
                    line.product_qty or 0.0, square_meter_uom, round=False
                )
                line.lot_pcs_qty = qty_sqm / lot_area_sqm
                continue

            if self._uom_is_related(line.product_uom_id, meter_uom):
                bar_length_m = lot_width / 1000 if lot_width else 0.0
                if not bar_length_m:
                    line.lot_pcs_qty = 0.0
                    continue

                qty_m = line.product_uom_id._compute_quantity(
                    line.product_qty or 0.0, meter_uom, round=False
                )
                line.lot_pcs_qty = qty_m / bar_length_m
                continue

            line.lot_pcs_qty = 0.0

    def _update_qty_from_lots_if_area(self, vals):
        """Ако единицата е от семейството на m² и има ширина и височина,
        връща vals с product_qty = m² / (ш × в) — брой парчета."""
        square_meter_uom = self._get_square_meter_uom()
        if not square_meter_uom:
            return vals

        uom = self.env["uom.uom"].browse(
            vals.get("product_uom_id") or self.product_uom_id.id
        )
        if not self._uom_is_related(uom, square_meter_uom):
            return vals

        lot_width = lot_height = 0.0
        lots_with_dims = self.forced_lot_ids.filtered(lambda l: l.width and l.height)
        if lots_with_dims:
            width_values = {lot.width for lot in lots_with_dims}
            height_values = {lot.height for lot in lots_with_dims}
            if len(width_values) == 1:
                lot_width = width_values.pop()
            if len(height_values) == 1:
                lot_height = height_values.pop()
        if not lot_width:
            lot_width = self.lot_width or 0.0
        if not lot_height:
            lot_height = self.lot_height or 0.0

        if lot_width and lot_height:
            area_sqm = (lot_width * lot_height) / 1_000_000
            if area_sqm > 0:
                qty_sqm = uom._compute_quantity(
                    vals.get("product_qty", self.product_qty), square_meter_uom, round=False
                )
                pcs_qty = qty_sqm / area_sqm
                vals = dict(vals)
                vals["product_qty"] = pcs_qty
        return vals
