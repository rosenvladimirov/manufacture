# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    forced_lot_extra_data = fields.Json(
        string="Extra Data",
        help="Arbitrary JSON data attached to this move for propagation purposes.",
    )

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
        """Pass forced_lot_ids to procurement for propagation to PO/MO."""
        values = super()._prepare_procurement_values()
        if self.forced_lot_ids:
            values["forced_lot_ids"] = self.forced_lot_ids
        return values

    @api.model
    def _prepare_merge_moves_distinct_fields(self):
        """Prevent merging moves with different forced_lot_ids."""
        distinct_fields = super()._prepare_merge_moves_distinct_fields()
        distinct_fields.append("forced_lot_ids")
        return distinct_fields

    def _action_assign(self, force_qty=False):
        """Auto-fill move_line.lot_id from forced_lot_ids when empty.

        Runs after super()._action_assign() so any lot picked by quant
        reservation wins. Only writes on move_lines that have neither
        lot_id nor lot_name set — never overrides Odoo's reservation
        choice or a value the user typed.

        Single forced lot → fills lot_id on all empty lines.
        Multiple forced lots → only acts when there is exactly one empty
        line; splits it pro-rata into one line per forced lot. Other
        shapes (multiple empty lines and multiple forced lots) are left
        untouched for the user to resolve.

        Skips creation for any forced lot that already has a non-empty
        move_line on the move — prevents duplicate zero-qty lines when
        another flow (e.g. LogiKal importer) pre-seeded the lines.
        """
        res = super()._action_assign(force_qty=force_qty)
        MoveLine = self.env["stock.move.line"]
        for move in self:
            if not move.forced_lot_ids:
                continue
            if move.product_id.tracking == "none":
                continue
            forced_lots = move.forced_lot_ids
            empty_lines = move.move_line_ids.filtered(
                lambda ml: not ml.lot_id and not ml.lot_name
            )
            if not empty_lines:
                continue

            already_seeded_lot_ids = set(
                move.move_line_ids.filtered("lot_id").mapped("lot_id").ids
            )

            if len(forced_lots) == 1:
                if forced_lots.id in already_seeded_lot_ids:
                    continue
                empty_lines.write({"lot_id": forced_lots[0].id})
                continue

            if len(empty_lines) != 1:
                continue
            first = empty_lines[0]
            total_qty = first.quantity or move.product_uom_qty
            if total_qty <= 0:
                continue

            lots_to_seed = forced_lots.filtered(
                lambda l: l.id not in already_seeded_lot_ids
            )
            if not lots_to_seed:
                continue
            qty_per_lot = total_qty / len(lots_to_seed)
            first.write({
                "lot_id": lots_to_seed[0].id,
                "quantity": qty_per_lot,
            })
            for lot in lots_to_seed[1:]:
                MoveLine.create({
                    "move_id": move.id,
                    "product_id": move.product_id.id,
                    "product_uom_id": move.product_uom.id,
                    "location_id": move.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                    "picking_id": move.picking_id.id,
                    "lot_id": lot.id,
                    "quantity": qty_per_lot,
                    "company_id": move.company_id.id,
                })
        return res

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
