# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
# https://www.odoo.com/documentation/user/legal/licenses/licenses.html

from odoo import _, fields, models
from odoo.exceptions import UserError


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

    def write(self, vals):
        """⛔ `picked` не се вдига на поръчка, която още не е освободена.

        🔑 ЗАЩО ТУК, а не при прехода на състоянието: в ядрото `state` на МО-то е
        ИЗЧИСЛЯЕМО поле, а не действие —
        ```python
        @api.depends(..., 'qty_producing', 'move_raw_ids.picked')
        elif any(production.move_raw_ids.mapped('picked')):
            production.state = 'progress'
        ```
        ⇒ Вдигне ли се `picked` където и да е, ядрото ИЗТЛАСКВА поръчката от
        „подготовка" при следващото преизчисление. Гард „в прехода" няма къде да
        застане; пази се входът.

        ⚠️ Мерено на 10.09 (Клаудио): МО в `progress` със `staged_released =
        False`, дванайсет неразпределени парчета и нито един разкроен прът — с
        достъпен бутон „Produce All". Отказът на подготовката поне се вижда;
        това минаваше ТИХО и поръчката изглеждаше наред.

        ✅ Прякото производство от „подготовка" НЕ се спира: `button_mark_done`
        вдига състоянието на `progress` ПРЕДИ да пипне движенията, тъй че щом
        стигнат дотук, поръчката вече не е в `preparation`. Гардът лови само
        страничното вдигане — ръчна отметка в списъка с движения, скрипт,
        сървърно действие.
        """
        if vals.get("picked"):
            zaduryani = self.env["mrp.production"]
            for move in self:
                mo = move.raw_material_production_id
                if (mo and mo.staged_preparation_enabled
                        and not mo.staged_released
                        and mo.state == "preparation"):
                    zaduryani |= mo
            if zaduryani:
                raise UserError(_(
                    "These manufacturing orders are still in Preparation and "
                    "have not been released:\n\n%(orders)s\n\n"
                    "Marking a component as picked would move them into "
                    "In Progress without ever passing through preparation — "
                    "no cutting run, no transfer, no reservation. Press "
                    "\"Prepare for Production\" first, or reset the order to "
                    "draft if it should not be produced.",
                    orders="\n".join(
                        "  - %s" % mo.display_name for mo in zaduryani),
                ))
        return super().write(vals)

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

    def _staged_pin_offcut_lot(self):
        """Заковава остатъчния лот върху реда на движението.

        📍 Методът е на `stock.move`, защото работи върху ДВИЖЕНИЯ. Първата
        версия го сложи на `mrp.production` и се викаше като
        `legs._staged_pin_offcut_lot()`, където `legs` е recordset от движения —
        тоест не се изпълняваше изобщо. Хванато от теста, не от кода.

        🔴 БЕЗ ТОВА ОСТАТЪКЪТ КАЦА С ПАРТИДАТА НА ЦЕЛИЯ ПРЪТ. Мерено на живо
        (03.09, WH/MO/00298):
        ```
        stock.move 8743   is_staged_offcut=True · forced_lot_ids=[312]   иска новия
        stock.move.line   lot_id = 5 („6500")                            каца със стария
        quant за OFF- лотовете 308–312                                   НУЛА записа
        quant в Remnant/Offcut                8.39 м „6500" · 5.35 м „6500"
        ```
        ⇒ Партида „6500" твърди „това са пръти 6500 мм". Остатък от 8 метра с
        такава партида се брои за наличност и влиза във „Free Stock in Transit",
        а за рязане не става — мерено: 6 от 7 количества в склада не са кратни
        на дължината на пръта.

        🔑 ЗАЩО `forced_lot_ids` НЕ СТИГА САМ: модулът го прилага в
        `_action_assign`, и то САМО върху редове с празен `lot_id` — нарочно, за
        да не пренаписва резервация на Odoo. Това движение обаче тръгва от
        ВИРТУАЛНА локация (Production) с готово `quantity` и `picked=True`, тъй
        че `_action_assign` не се вика изобщо. Няма кой да сложи лота.

        ⚠️ Тук се пише ИЗРИЧНО и се ПРЕЗАПИСВА, ако Odoo вече е сложил друг лот:
        за by-product от виртуална локация „заварената" стойност не е нечия
        резервация, а произволният лот, който складът е намерил.
        ⛔ Пипа се САМО движение с `is_staged_offcut` — нищо друго.
        """
        # ⚠️ Модулът НЕ зависи от `stock_move_forced_lot_multi` (виж manifest:
        # depends = mrp, stock). Затова полето се пита, както се прави навсякъде
        # другаде тук — инак ъпгрейд само на този модул гърми с
        # „Invalid field 'forced_lot_ids' on model 'stock.move'".
        if "forced_lot_ids" not in self.env["stock.move"]._fields:
            return
        for move in self.filtered("is_staged_offcut"):
            lot = move.forced_lot_ids[:1]
            if not lot:
                continue
            if move.move_line_ids:
                gresh = move.move_line_ids.filtered(lambda l: l.lot_id != lot)
                if gresh:
                    gresh.write({"lot_id": lot.id})
            else:
                # Линия още няма (движението е само потвърдено) — правим я сами,
                # инак Odoo ще я роди при приключването и пак ще избере лот сам.
                self.env["stock.move.line"].create({
                    "move_id": move.id,
                    "product_id": move.product_id.id,
                    "product_uom_id": move.product_uom.id,
                    "location_id": move.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                    "lot_id": lot.id,
                    "quantity": move.product_uom_qty,
                    "company_id": move.company_id.id,
                })
