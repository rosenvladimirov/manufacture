# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

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
        vals = super()._get_move_raw_values(
            product, product_uom_qty, product_uom, operation_id, bom_line)
        if bom_line and bom_line.default_forced_lot_id and not vals.get(
                "forced_lot_ids"):
            lot = bom_line.default_forced_lot_id
            if lot.product_id == product:
                vals["forced_lot_ids"] = [(6, 0, [lot.id])]
        return vals
