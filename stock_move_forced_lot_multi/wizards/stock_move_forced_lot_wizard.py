# Copyright 2025 Rosen Vladimirov, Terraros Commerce Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

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
