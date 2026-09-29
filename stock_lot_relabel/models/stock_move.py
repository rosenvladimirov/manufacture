# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)

from odoo import fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    # Следата на преетикетирането: двете движения се сочат взаимно и носят
    # двата лота, за да се чете от самото движение „от кой в кой".
    lot_relabel_role = fields.Selection(
        [("out", "Out (source lot)"), ("in", "In (target lot)")],
        string="Lot Relabel Role", copy=False, readonly=True,
        help="Set on the two moves of a lot relabel: the one that takes the "
             "source lot out, and the one that brings the target lot back.")
    lot_relabel_pair_id = fields.Many2one(
        "stock.move", string="Lot Relabel Counterpart", copy=False,
        readonly=True, index="btree_not_null",
        help="The other move of the same lot relabel.")
    lot_relabel_src_lot_id = fields.Many2one(
        "stock.lot", string="Relabelled From", copy=False, readonly=True)
    lot_relabel_dst_lot_id = fields.Many2one(
        "stock.lot", string="Relabelled To", copy=False, readonly=True)

    def _skip_push(self):
        # Преетикетирането връща стоката там, откъдето е излязла — правило за
        # избутване от тази локация не бива да я понесе нататък.
        if self.lot_relabel_role:
            return True
        return super()._skip_push()

    def _get_in_svl_vals(self, forced_quantity):
        """Входящото движение на преетикетирането влиза с ТОЧНО стойността,
        с която е излязло изходящото — до стотинка.

        🔑 Ядрото би оценило входа по `price_unit` (FIFO/AVCO) или по
        `standard_price` (стандартна цена) и би закръглило `цена × количество`.
        При изход от ДВА FIFO слоя с различна цена средната цена е безкрайна
        дроб и произведението може да се размине с изхода в последната
        стотинка. Затова стойността се взима от самия изходен слой и се пише в
        `value` / `remaining_value`; единичната цена е само производна.
        ⛔ `standard_price` на продукта НЕ се пипа тук.
        """
        vals_list = super()._get_in_svl_vals(forced_quantity)
        if forced_quantity:
            return vals_list
        pairs = {
            move.id: move.lot_relabel_pair_id for move in self
            if move.lot_relabel_role == "in" and move.lot_relabel_pair_id
        }
        if not pairs:
            return vals_list
        for vals in vals_list:
            out_move = pairs.get(vals.get("stock_move_id"))
            if not out_move:
                continue
            value = -sum(out_move.sudo().stock_valuation_layer_ids.mapped("value"))
            quantity = vals.get("quantity") or 0.0
            vals["value"] = value
            vals["remaining_value"] = value
            vals["unit_cost"] = value / quantity if quantity else 0.0
        return vals_list
