# Copyright 2025 Your Company
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

    def _prepare_procurement_values(self):
        """Pass forced_lot_ids to procurement for propagation to PO."""
        values = super()._prepare_procurement_values()
        if self.forced_lot_ids:
            values["forced_lot_ids"] = self.forced_lot_ids
        return values

    def _get_new_picking_values(self):
        """Include forced lots info when creating new picking."""
        values = super()._get_new_picking_values()
        return values

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        """Prepare move line values - will be extended for lot population."""
        vals = super()._prepare_move_line_vals(
            quantity=quantity, reserved_quant=reserved_quant
        )
        return vals

    def _action_assign(self, force_qty=False):
        """Override to handle forced lots on incoming moves."""
        res = super()._action_assign(force_qty=force_qty)
        # For incoming moves with forced lots, create move lines per lot
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

        # Remove existing move lines without lot or with lots not in forced_lot_ids
        lines_to_remove = self.move_line_ids.filtered(
            lambda l: not l.lot_id or l.lot_id not in self.forced_lot_ids
        )
        lines_to_remove.unlink()

        # Get existing lots in move lines
        existing_lots = self.move_line_ids.mapped("lot_id")

        # Calculate quantity per lot (equal distribution or based on lot info)
        lots_to_create = self.forced_lot_ids - existing_lots
        if not lots_to_create:
            return

        # Distribute quantity equally among lots for now
        # This can be enhanced to use lot-specific quantities
        total_qty = self.product_uom_qty
        existing_qty = sum(self.move_line_ids.mapped("quantity"))
        remaining_qty = total_qty - existing_qty

        if remaining_qty <= 0:
            return

        qty_per_lot = remaining_qty / len(lots_to_create)

        for lot in lots_to_create:
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

    def _merge_moves(self, merge_into=False):
        """Prevent merging moves with different forced lots."""
        # Group moves by forced_lot_ids to prevent incorrect merging
        moves_to_merge = self.filtered(lambda m: not m.forced_lot_ids)
        moves_with_lots = self - moves_to_merge

        result = super(StockMove, moves_to_merge)._merge_moves(merge_into=merge_into)

        # Don't merge moves with forced lots - return them as-is
        return result | moves_with_lots

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
