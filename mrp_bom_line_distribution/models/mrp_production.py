#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class MRPProduction(models.Model):
    _inherit = "mrp.production"

    def _get_move_raw_values(
        self,
        product,
        product_uom_qty,
        product_uom,
        operation_id=False,
        bom_line=False,
    ):
        values = super()._get_move_raw_values(
            product,
            product_uom_qty,
            product_uom,
            operation_id=operation_id,
            bom_line=bom_line,
        )
        if bom_line:
            values["distribution_coefficient"] = bom_line.distribution_coefficient
            values["is_distribution_master"] = bom_line.is_distribution_master
            base_qty = 0.0
            bom = bom_line.bom_id
            if bom and bom.product_qty:
                qty_in_bom_uom = self.product_uom_id._compute_quantity(
                    self.product_qty, bom.product_uom_id, round=False
                )
                factor = qty_in_bom_uom / bom.product_qty
                base_qty = bom.base_distribution_qty * factor
            values["base_distribution_qty"] = base_qty
        return values
