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


class StockMoveForcedLotWizard(models.TransientModel):
    _name = "stock.move.forced.lot.wizard"
    _description = "Add Forced Lots to Stock Move"

    move_id = fields.Many2one(
        comodel_name="stock.move",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        related="move_id.product_id",
        readonly=True,
    )
    lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        string="Forced Lots",
        domain="[('product_id', '=', product_id)]",
    )

    def action_apply(self):
        self.ensure_one()
        if self.lot_ids:
            self.move_id.forced_lot_ids |= self.lot_ids
            if (
                self.move_id.picking_type_id.code == "incoming"
                and self.move_id.state in ("confirmed", "partially_available", "assigned")
            ):
                self.move_id._create_forced_lot_move_lines()
        return {"type": "ir.actions.act_window_close"}
