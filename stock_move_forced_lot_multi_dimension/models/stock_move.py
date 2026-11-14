# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    # Бройките на хода по размера на лотовете (стъкла в м², профили в м) — в таба
    # „Операции“ на приемането, където иначе се вижда само м² (Теолино, TG 174900).
    lot_pcs_qty = fields.Float(
        string="Pieces (calc.)",
        digits=(16, 2),
        compute="_compute_lot_pcs_qty",
        help="Pieces by the size of the lots: square metres over the area of one piece, "
        "metres over the length of one bar. A fraction is shown as it is, not rounded.",
    )

    @api.depends(
        "product_uom_qty",
        "product_uom",
        "move_line_ids.quantity",
        "move_line_ids.lot_id.width",
        "move_line_ids.lot_id.height",
        "forced_lot_ids.width",
        "forced_lot_ids.height",
    )
    def _compute_lot_pcs_qty(self):
        # 19: няма uom.category — семейството на мярката се познава по общата
        # референция; помощниците са на реда на покупката (същият модул)
        Line = self.env["purchase.order.line"]
        square = Line._get_square_meter_uom()
        meter = Line._get_meter_uom()
        for move in self:
            total = 0.0
            # редовете с лот: всеки по своя размер; без редове — лотовете на хода, ако са с един размер
            parts = [(line.quantity, line.product_uom_id, line.lot_id) for line in move.move_line_ids if line.lot_id]
            if not parts:
                lots = move.forced_lot_ids.filtered(lambda lot: lot.width)
                sizes = {(lot.width, lot.height) for lot in lots}
                if len(sizes) == 1:
                    # в 19 stock.move пази единицата в product_uom, а move.line — в product_uom_id
                    parts = [(move.product_uom_qty, move.product_uom, lots[:1])]
            for qty, uom, lot in parts:
                if not uom or not lot.width:
                    continue
                if Line._uom_is_related(uom, square) and lot.height:
                    total += uom._compute_quantity(qty or 0.0, square, round=False) / (lot.width * lot.height / 1e6)
                elif Line._uom_is_related(uom, meter):
                    total += uom._compute_quantity(qty or 0.0, meter, round=False) / (lot.width / 1000)
            move.lot_pcs_qty = total
