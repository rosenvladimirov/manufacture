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
