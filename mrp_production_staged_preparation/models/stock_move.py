# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
# https://www.odoo.com/documentation/user/legal/licenses/licenses.html

from odoo import fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    # Whole-bar B credit-back marker (Любо 157140): отделя нашите offcut
    # by-product moves от РЪЧНО дефинираните by-products на потребителя —
    # _cal_price override-ът сетва cost_share САМО на маркираните. copy=False →
    # backorder не наследява.
    is_staged_offcut = fields.Boolean(
        "Staged Offcut By-product", default=False, copy=False,
        help="Whole-bar credit-back offcut by-product (variant B). Its value "
             "is set via cost_share in mrp.production._cal_price so the offcut "
             "reduces the finished product cost strictly FIFO.")

    # ── Hybrid staged endpoint-swap (виж mrp_production._get_move_raw_values) ─
    # В intermediate фазата (staged_preparation_enabled и НЕ staged_released)
    # не-стъклените raw moves са swap-нати на Stock→Production (1-step,
    # make_to_stock) — резервират от WH/Stock, ордерпоинтът вижда търсенето.
    # Native _adjust_procure_method обаче би ги match-нал срещу manufacture
    # pull rule и върнал на make_to_order → тук short-circuit-ваме, за да
    # запазим make_to_stock. Стъклото (категория Glass) минава нативно (MTO).

    def _staged_keep_mts(self):
        """True ако този move трябва да остане make_to_stock (staged не-глас)."""
        self.ensure_one()
        mo = self.raw_material_production_id
        if not (mo
                and mo.picking_type_id.staged_preparation_enabled
                and not mo.staged_released):
            return False
        return "Glass" not in (self.product_id.categ_id.complete_name or "")

    # ВАЖНО: *args/**kwargs — core/repair викат с picking_type_code= kwarg.
    def _adjust_procure_method(self, *args, **kwargs):
        keep = self.filtered(lambda m: m._staged_keep_mts())
        if keep:
            keep.procure_method = "make_to_stock"
        return super(StockMove, self - keep)._adjust_procure_method(
            *args, **kwargs)
