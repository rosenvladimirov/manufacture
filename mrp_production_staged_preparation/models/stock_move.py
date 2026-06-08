# Copyright 2026 Rosen Vladimirov
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    # ── Hybrid staged deferral ──────────────────────────────────────────
    # При staged MO компонентните вътрешни picks (Стока→Pre-Production) НЕ
    # бива да се раждат на Confirm — операторът ги иска чак след „Подготви за
    # производство" (floor release). НО стъкло/барове/lot-tracked компоненти
    # ТРЯБВА да получат своя PO/MTO chain навреме на Confirm (иначе доставките
    # закъсняват — точно проблемът, заради който старият full-suppress беше
    # премахнат). Затова отлагаме ИЗБИРАТЕЛНО: само не-lot-tracked компоненти.
    #
    # Дискриминатор: product.tracking == 'none'  → отлага се (make_to_stock,
    # без upstream pull → без pick). lot-tracked (tracking != 'none', т.е.
    # стъкло/барове) → нормален make_to_order → PO/pick на Confirm.

    def _staged_should_defer(self):
        """True ако този raw move трябва да се отложи до floor release.

        Отлагаме САМО ако компонентът е (а) не-lot-tracked И (б) ВЕЧЕ наличен
        в склада. Тогава деферирането държи само вътрешния Стока→Pre-Production
        pick — нищо не се блокира. Ако компонентът НЕ е наличен (трябва покупка,
        напр. Formteil), връщаме False → make_to_order остава → MTO/buy chain
        създава PO навреме, точно както при lot-tracked профилите. Така
        отлагаме трансфери, БЕЗ да блокираме покупки.
        """
        self.ensure_one()
        mo = self.raw_material_production_id
        if not (mo
                and mo.picking_type_id.staged_preparation_enabled
                and not mo.staged_released
                and self.product_id.tracking == "none"):
            return False
        warehouse = mo.picking_type_id.warehouse_id or mo.warehouse_id
        product = self.product_id
        if warehouse:
            product = product.with_context(warehouse=warehouse.id)
        # free_qty = налично - вече резервирано; ако покрива нуждата → отлагаме.
        return product.free_qty >= self.product_uom_qty

    # ВАЖНО: сигнатурата трябва да приема *args/**kwargs — core/repair викат
    # _adjust_procure_method(picking_type_code='...') с keyword аргумент.
    def _adjust_procure_method(self, *args, **kwargs):
        # Отложените raw moves се форсират на make_to_stock → не задействат
        # upstream pull rule → не се ражда Стока→Pre-Production pick на Confirm.
        # Остатъкът минава нативно (incl. lot-tracked → make_to_order → PO/pick).
        deferred = self.filtered(lambda m: m._staged_should_defer())
        if deferred:
            deferred.procure_method = "make_to_stock"
        return super(StockMove, self - deferred)._adjust_procure_method(
            *args, **kwargs)
