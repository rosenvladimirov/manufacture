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
        """True ако този raw move трябва да мине през ОРДЕРПОИНТ логиката (МТС),
        вместо да се chain-ва на per-MO MTO в pbm маршрута.

        Дизайн (Росен): ВСИЧКО без стъклата → make_to_stock → ордерпоинтът
        (reordering rule) поема репленишмънта (МТС+МТО на ниво ордерпоинт).
        Само СТЪКЛОТО остава make_to_order (per-project, без склад).

        В pbm (2-step) raw moves по подразбиране са make_to_order (за да
        chain-ват Стока→Pre-Production pick). Това форсира не-стъклените на
        make_to_stock → НЕ се ражда вътрешен pick на Confirm (отложен до
        „Подготви") + ордерпоинтът прави PO-то по форкаст. Стъклото (lot,
        категория Glass) → native make_to_order → glass PO на Confirm.

        Дискриминатор: глас = product.tracking != 'none' И категорията съдържа
        'Glass'. Барове (lot, Profiles) НЕ са глас → също минават през МТС.
        """
        # ВРЕМЕННО ИЗКЛЮЧЕНО (2026-06-08): форсирането на make_to_stock стои
        # в Pre-Production (pbm_loc) и НЕ задейства WH/Stock ордерпоинта →
        # компонентите оставаха без PO. „Без трансфер преди подготовка" + „PO
        # през ордерпоинт" са несъвместими с procure_method трик в pbm (pick-ът
        # е сигналът за търсене към Stock). Правилното решение е release-
        # management (PO на confirm, физическо освобождаване на pick на
        # „Подготви"). Докато се реши — native pbm: pick + ордерпоинт + PO
        # работят (трансфери на confirm). Visual gate + reset бутон остават.
        return False

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
