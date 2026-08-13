# Copyright 2025 Rosen Vladimirov, Terraros Commerce Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    forced_lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        relation="stock_move_forced_lot_rel",
        column1="move_id",
        column2="lot_id",
        string="Forced Lots",
        help="Lots that must be used for this move. "
        "When set, the move will only accept these specific lots.",
        copy=True,
    )

    @api.model
    def _prepare_merge_moves_distinct_fields(self):
        """Prevent merging moves with different forced lots."""
        distinct_fields = super()._prepare_merge_moves_distinct_fields()
        distinct_fields.append("forced_lot_ids")
        return distinct_fields

    def _prepare_procurement_values(self):
        """Pass forced_lot_ids to procurement for propagation to PO."""
        values = super()._prepare_procurement_values()
        if self.forced_lot_ids:
            values["forced_lot_ids"] = self.forced_lot_ids
        return values

    def _action_assign(self, force_qty=False):
        """Override to handle forced lots on incoming moves."""
        res = super()._action_assign(force_qty=force_qty)
        for move in self.filtered(
            lambda m: m.forced_lot_ids
            and m.picking_type_id.code == "incoming"
            and m.state in ("confirmed", "partially_available", "assigned")
        ):
            move._create_forced_lot_move_lines()
        return res

    def _create_forced_lot_move_lines(self):
        """Create stock.move.line records for each forced lot."""
        self.ensure_one()
        if not self.forced_lot_ids:
            return

        lines_to_remove = self.move_line_ids.filtered(
            lambda l: not l.lot_id or l.lot_id not in self.forced_lot_ids
        )
        lines_to_remove.unlink()

        existing_lots = self.move_line_ids.mapped("lot_id")
        lots_to_create = self.forced_lot_ids - existing_lots
        if not lots_to_create:
            return

        total_qty = self.product_uom_qty
        existing_qty = sum(self.move_line_ids.mapped("quantity"))
        remaining_qty = total_qty - existing_qty

        if remaining_qty <= 0:
            return

        for lot in lots_to_create:
            qty_per_lot = self._get_qty_per_lot(remaining_qty, lots_to_create, lot)
            self.env["stock.move.line"].create({
                "move_id": self.id,
                "product_id": self.product_id.id,
                "product_uom_id": self.product_uom.id,
                "location_id": self.location_id.id,
                "location_dest_id": self.location_dest_id.id,
                "picking_id": self.picking_id.id,
                "lot_id": lot.id,
                "quantity": qty_per_lot,
            })

    def _get_qty_per_lot(self, remaining_qty, lots_to_create, lot=None):
        """Return the quantity to use per lot when creating move lines."""
        self.ensure_one()
        return remaining_qty / len(lots_to_create)

    def action_open_forced_lot_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.move.forced.lot.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_move_id": self.id,
                "default_product_id": self.product_id.id,
            },
        }
