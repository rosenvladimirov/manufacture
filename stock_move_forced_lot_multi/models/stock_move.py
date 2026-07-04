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
        """Auto-fill на move_line.lot_id от forced_lot_ids след резервация.

        Върви СЛЕД super()._action_assign(), така че лот избран от quant
        резервацията печели. Пълни само празни линии (виж helper-а).
        """
        res = super()._action_assign(force_qty=force_qty)
        self._forced_lot_fill_empty_lines()
        return res

    def _action_done(self, cancel_backorder=False):
        """Forced_lot fill и по immediate-transfer пътя (lot-gap фикс).

        При mark_done БЕЗ предварителен _action_assign (напр. МО raw
        consumption в интегрирания Prepare/Optimize поток) move_line-ите
        се раждат тук без lot_id → core-ът вдига „You need to supply a
        Lot/Serial Number" (stock_move_line._action_done). Пълним от
        forced_lot_ids ПРЕДИ super(), със същата семантика като fill-а
        в _action_assign.
        """
        self._forced_lot_fill_empty_lines()
        return super()._action_done(cancel_backorder=cancel_backorder)

    def _forced_lot_fill_empty_lines(self):
        """Пълни lot_id на празните move_lines от forced_lot_ids.

        Пише САМО по линии без lot_id и без lot_name — никога не
        презаписва избор на резервацията или ръчно въведена стойност.

        Един forced лот → попълва lot_id на всички празни линии.
        Няколко forced лота → действа само при ТОЧНО една празна линия;
        разцепва я pro-rata на по една линия per лот. Други форми
        (няколко празни линии + няколко лота) се оставят на потребителя.

        Прескача лотове, които вече имат непразна move_line на move-а —
        предпазва от дублирани zero-qty линии, когато друг поток (напр.
        LogiKal importer-ът) е pre-seed-нал линиите.
        """
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
