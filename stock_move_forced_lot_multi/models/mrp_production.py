# Copyright 2025-2026 Rosen Vladimirov
#
# This file is available under a DUAL LICENSE:
#   1. GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)
#      https://www.gnu.org/licenses/agpl-3.0.html
#   2. A commercial license from Rosen Vladimirov, for use without the obligations
#      of the AGPL. See LICENSE-COMMERCIAL.md. Contact: vladimirov.rosen@gmail.com
#
# Unless you hold a valid commercial license, your use of this file is governed
# by the AGPL-3.0-or-later.


from odoo import api, fields, models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    forced_lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        compute="_compute_forced_lot_ids",
        string="Forced Lots",
        help="Lots forced on raw material moves in this MO.",
    )

    @api.depends("move_raw_ids.forced_lot_ids")
    def _compute_forced_lot_ids(self):
        for production in self:
            production.forced_lot_ids = (
                production.move_raw_ids.mapped("forced_lot_ids")
            )

    def _get_move_raw_values(self, product, product_uom_qty, product_uom,
                             operation_id=False, bom_line=False):
        """Default forced lot от BoM реда (ръчни PRK BoM-ове).

        Ако bom_line има `default_forced_lot_id`, сетваме forced_lot_ids на
        raw move-а при създаване → MO консумира само от тоя лот (резервация,
        без split). Само ако още няма forced_lot_ids (LogiKal / друг източник
        има приоритет) и лотът пасва на продукта.
        """
        # Сигнатурата е същата в 19: mrp/models/mrp_production.py:1360
        vals = super()._get_move_raw_values(
            product, product_uom_qty, product_uom, operation_id, bom_line)
        if bom_line and bom_line.default_forced_lot_id and not vals.get(
                "forced_lot_ids"):
            lot = bom_line.default_forced_lot_id
            if lot.product_id == product:
                vals["forced_lot_ids"] = [(6, 0, [lot.id])]
        return vals
