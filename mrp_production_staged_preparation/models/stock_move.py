# Copyright 2026 Rosen Vladimirov
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

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
