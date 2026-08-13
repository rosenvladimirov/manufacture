# Copyright 2025 Rosen Vladimirov, Terraros Commerce Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    forced_lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        compute="_compute_forced_lot_ids",
        string="Forced Lots",
        help="Lots forced on moves in this picking.",
    )

    @api.depends("move_ids.forced_lot_ids")
    def _compute_forced_lot_ids(self):
        for picking in self:
            picking.forced_lot_ids = (
                picking.move_ids.mapped("forced_lot_ids")
            )
