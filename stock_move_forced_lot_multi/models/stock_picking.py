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
