# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)

from odoo import _, api, fields, models


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

    @api.depends("origin", "lot_relabel_role")
    def _compute_reference(self):
        """Двете движения на преетикетирането носят ЕДНА референция.

        🔑 В 19 `reference` се изчислява (пикинг / брак / инвентаризация), а
        `name` на движението го няма — движение без пикинг остава без
        референция. Затова референцията на преетикетирането се взима от
        `origin`, където `stock.lot._relabel` я пише. Без нея и счетоводният
        запис на ядрото (`reference + ' - ' + продукт`) би паднал.
        """
        super()._compute_reference()
        for move in self:
            if move.lot_relabel_role and not move.picking_id:
                move.reference = move.origin

    def _skip_push(self):
        # Преетикетирането връща стоката там, откъдето е излязла — правило за
        # избутване от тази локация не бива да я понесе нататък.
        if self.lot_relabel_role:
            return True
        return super()._skip_push()

    def _get_value_from_returns(self, quantity, at_date=None):
        """Входящото движение на преетикетирането влиза с ТОЧНО стойността,
        с която е излязло изходящото — до стотинка.

        🔑 Порт на 18 `_get_in_svl_vals`: в 19 слоевете ги няма, стойността е
        `stock.move.value`. Ядрото би оценило входа от виртуална локация по
        `standard_price` × количество (`_get_value_from_std_price`) — при изход
        от ДВА FIFO слоя с различна цена това се разминава с изхода. Затова
        стойността се взима от самото изходящо движение.

        Куката е тук (след ръчната преоценка `product.value`, сметките,
        производството и офертите; преди стандартната цена) — същото място, на
        което ядрото оценява връщане по стойността на оригиналното движение.
        ⛔ `standard_price` на продукта НЕ се пипа тук.
        """
        if self.lot_relabel_role == "in" and self.lot_relabel_pair_id:
            out_move = self.lot_relabel_pair_id.sudo()
            out_qty = out_move._get_valued_qty()
            uom = self.product_id.uom_id    # количествата тук са в мярката на продукта
            if uom.compare(quantity, out_qty) == 0:
                value = out_move.value
            elif uom.is_zero(out_qty):
                value = 0.0
            else:
                value = out_move.value * quantity / out_qty
            return {
                "value": value,
                "quantity": quantity,
                "description": _(
                    "Value of the lot relabel move %(reference)s",
                    reference=out_move.reference),
            }
        return super()._get_value_from_returns(quantity, at_date=at_date)
