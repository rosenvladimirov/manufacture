# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
# https://www.odoo.com/documentation/user/legal/licenses/licenses.html

from odoo import api, _, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


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

    # №93: движението, с което се ражда остатъкът на един прът от разкроя.
    # Integer, не Many2one: модулът НЕ зависи от mrp_cutting_optimization.
    # Пази идемпотентността — повторна подготовка не ражда втори остатък.
    staged_remnant_bar_ref = fields.Integer(
        "Staged Remnant Bar", copy=False, index=True,
        help="Cutting-plan bar whose remnant this move carries from the "
             "component location to the remnant location.")
    staged_remnant_lot_id = fields.Many2one(
        "stock.lot", string="Staged Remnant Lot", copy=False,
        help="Lot of the remnant, named after its length in millimetres.")
    # №93 (18.0.2.23.0): лотът, от който остатъкът е отрязан („6500"). Докато
    # в буфера не е сменен към `staged_remnant_lot_id`, движението не резервира.
    staged_remnant_src_lot_id = fields.Many2one(
        "stock.lot", string="Staged Remnant Source Lot", copy=False,
        help="Lot of the bar the remnant is cut from. The remnant transfer "
             "waits until this lot has been relabelled to the remnant lot.")
    # №93 (18.0.2.24.0): движение на PC, което носи СТАР остатък („4640")
    # от Remnant / Offcut в буфера — като цял прът (Любо, ТГ 167875).
    # Резервира само този лот и само в остатъчната локация.
    staged_offcut_src_lot_id = fields.Many2one(
        "stock.lot", string="Staged Old Remnant Lot", copy=False, index=True,
        help="Existing remnant lot this preparation pick carries from the "
             "remnant location into the buffer, like a full bar.")
    staged_offcut_production_id = fields.Many2one(
        "mrp.production", string="Staged Old Remnant Order", copy=False,
        index=True, ondelete="set null",
        help="Manufacturing order whose preparation carries this old "
             "remnant into the buffer.")
    # Следата на смяната на лота (движенията на `stock.lot._relabel`) към
    # пръта, чийто остатък е — и дали е обратна смяна (Undo Preparation).
    staged_relabel_bar_ref = fields.Integer(
        "Staged Relabel Bar", copy=False, index=True,
        help="Cutting-plan bar whose remnant this lot relabel belongs to.")
    staged_relabel_undo = fields.Boolean(
        "Staged Relabel Undo", copy=False,
        help="This lot relabel reverses an earlier one (Undo Preparation).")

    # ── Hybrid staged endpoint-swap (виж mrp_production._get_move_raw_values) ─
    # В intermediate фазата (staged_preparation_enabled и НЕ staged_released)
    # не-стъклените raw moves са swap-нати на Stock→Production (1-step,
    # make_to_stock) — резервират от WH/Stock, ордерпоинтът вижда търсенето.
    # Native _adjust_procure_method обаче би ги match-нал срещу manufacture
    # pull rule и върнал на make_to_order → тук short-circuit-ваме, за да
    # запазим make_to_stock. Стъклото (категория Glass) минава нативно (MTO).

    # 🔑 Следата пик → консумация, БЕЗ резервационна верига (④, 10.09).
    # Дотук връзката се пазеше през `move_orig_ids`, но тя не е само следа: тя
    # НАЛАГА ТАВАН — вързано движение резервира само каквото веригата му е
    # доставила. Мерено по WH/MO/01641: буферът има 7,02 м свободни от верния
    # лот в вярната локация, а консумацията стои на 1,03, защото толкова е
    # останало от пика. Полето пази следата; резервацията вече е свободна.
    staged_pick_move_id = fields.Many2one(
        "stock.move", string="Staged Pick Move", index=True, copy=False,
        ondelete="set null",
        help="Preparation pick that was created to top up the buffer for this "
             "consumption. A trace only — it does not cap the reservation.")
    staged_consumption_ids = fields.One2many(
        "stock.move", "staged_pick_move_id", string="Staged Consumptions",
        help="Buffer consumptions this preparation pick tops up.")

    def _action_done(self, cancel_backorder=False):
        """Пикът кацна в буфера → консумациите му се резервират наново.

        ⚠️ БЕЗ това разкачането е половинчато. При ВЪРЗАНО движение ядрото
        дораздава при `done` на пика; разкачено — никой. Консумацията щеше да
        чака човек да натисне „Check availability", а точно това чакане беше
        симптомът, от който тръгнахме.

        🔑 Locationът е срещата: пикът пълни Pre-Production, консумацията взима
        оттам. Тук само подсещаме ядрото да погледне пак.
        """
        res = super()._action_done(cancel_backorder=cancel_backorder)
        # №93: ПЪРВО смяната на лота на остатъците — метрите им се запазват
        # под своя лот, преди консумациите да гребнат свободното.
        self._staged_relabel_after_landing(res)
        chakashti = (res.mapped("staged_consumption_ids")
                     | res._staged_offcut_consumers()).filtered(
            lambda m: m.state not in ("done", "cancel"))
        if chakashti:
            chakashti._action_assign()
        return res

    def _staged_offcut_consumers(self):
        """Консумациите, които чакат кацналите стари остатъци (№93).

        Старият остатък е ЕДНО движение за pattern-а, а го режат парчета на
        няколко поръчки от разкроя — следата `staged_pick_move_id` сочи само
        една. Затова: всички живи консумации на разкроя за същия продукт от
        буфера, в който е кацнал."""
        Production = self.env["mrp.production"]
        out = self.env["stock.move"]
        for pick in self.filtered(
                lambda m: m.staged_offcut_src_lot_id and m.state == "done"):
            mo = pick.staged_offcut_production_id
            opt = mo.staged_cutting_optimization_id
            mos = (Production._staged_run_productions(opt) if opt else mo)
            out |= mos.move_raw_ids.filtered(
                lambda m: m.product_id == pick.product_id
                and m.location_id == pick.location_dest_id
                and m.state not in ("done", "cancel") and not m.picked)
        return out

    def _staged_relabel_after_landing(self, moves):
        """Прътите кацнаха в буфера ⇒ сменя се лотът на остатъците на разкроя.

        🔑 Разкроят се намира по пикинга, от който е кацнало: по следата към
        консумациите (`staged_consumption_ids`, `move_dest_ids`) и по
        `cutting_optimization_id`. Backorder-ът не носи нито едното — затова се
        качваме до първия пикинг по `backorder_id`. Дали целият PC е кацнал,
        решава `mrp.production._staged_relabel_remnants`.
        """
        landed = moves.filtered(
            lambda m: m.state == "done" and m.picking_id
            and not m.staged_remnant_lot_id and not m.lot_relabel_role
            and m.location_dest_id.usage == "internal")
        if not landed:
            return
        roots = landed.picking_id
        parents = roots.backorder_id - roots
        while parents:
            roots |= parents
            parents = roots.backorder_id - roots
        family = roots.move_ids
        mos = (family.staged_consumption_ids
               | family.move_dest_ids).raw_material_production_id \
            | family.staged_offcut_production_id
        opts = mos.staged_cutting_optimization_id
        if "cutting_optimization_id" in self.env["stock.picking"]._fields:
            opts |= roots.cutting_optimization_id
        Production = self.env["mrp.production"]
        for opt in opts:
            if not Production._staged_run_productions(opt):
                continue
            run = Production._staged_run_productions(opt).filtered(
                lambda p: p.staged_cutting_optimization_id == opt)
            if run and opt in run._staged_remnant_runs():
                run._staged_relabel_remnants(opt)

    def _action_assign(self, force_qty=False):
        # №93: движенията на трансфера на остатъците резервират САМО своя лот
        # („4630") и само след смяната му — не каквото ядрото намери в буфера.
        remnant = self.filtered(
            lambda m: m.staged_remnant_lot_id
            and m.state in ("confirmed", "waiting", "partially_available"))
        # №93: PC на подготовката — заковано към лота и подлокацията.
        pc = (self - remnant).filtered(lambda m: m._staged_is_pc())
        rest = self - remnant - pc
        res = super(StockMove, rest)._action_assign(force_qty=force_qty) \
            if rest else None
        if pc:
            pc._staged_assign_pc()
        if remnant:
            remnant._staged_assign_remnant()
        return res

    def _staged_is_pc(self):
        """Движение на PC на подготовката (Stock → Pre-Production)?

        Пикът за цели пръти (сочи го консумация — `staged_consumption_ids`)
        или старият остатък (`staged_offcut_src_lot_id`). Само свободно
        попълване: без верига (`move_orig_ids`) — заварените вързани пикове
        отпреди ④ остават на ядрото."""
        self.ensure_one()
        return bool(
            (self.staged_consumption_ids or self.staged_offcut_src_lot_id)
            and not self.raw_material_production_id
            and not self.move_orig_ids
            and self.state in ("confirmed", "waiting", "partially_available")
            and self.location_dest_id.usage == "internal")

    def _staged_assign_pc(self):
        """Резервацията на PC: правилният лот от правилната подлокация.

        🔴 ЗАЩО НЕ ЯДРОТО (ТГ 167877): PC тръгва от WH/Stock, а на живо
        буферът (WH/Stock/Pre-Production) е ПОД WH/Stock — ядрото търси
        `child_of` и може да „вземе" кванти, които вече са в самата
        дестинация; а `forced_lot_ids` не ограничава резервацията (пълни лот
        само на празните редове СЛЕД ядрото).

        ⇒ Тук, по квантова локация и `strict=True`:
          • никога от поддървото на дестинацията (буфера);
          • старият остатък (`staged_offcut_src_lot_id`) — САМО този лот и
            САМО в Remnant / Offcut;
          • цял прът — само форсираните лотове (ако ги има) и НЕ от
            Remnant / Offcut (там лежат остатъци с лот на прът след
            компенсацията, 24.09).
        """
        Quant = self.env["stock.quant"]
        off = self.env["mrp.production"]._staged_offcut_location()

        def under(location, root):
            return bool(root) and (location.parent_path or "").startswith(
                root.parent_path or "/-/")

        s_lot = "forced_lot_ids" in self._fields
        for move in self:
            rounding = move.product_id.uom_id.rounding
            need = move.product_qty - sum(
                move.move_line_ids.mapped("quantity_product_uom"))
            if float_compare(need, 0.0, precision_rounding=rounding) <= 0:
                continue
            lots = move.staged_offcut_src_lot_id or (
                move.forced_lot_ids if s_lot else self.env["stock.lot"])
            domain = [
                ("product_id", "=", move.product_id.id),
                ("location_id", "child_of", move.location_id.id),
                ("location_id.usage", "=", "internal"),
                ("quantity", ">", 0),
            ]
            if lots:
                domain.append(("lot_id", "in", lots.ids))
            quants = Quant.search(domain, order="in_date, id").filtered(
                lambda q: not under(q.location_id, move.location_dest_id)
                and (not q.owner_id
                     or q.owner_id == move.restrict_partner_id))
            if move.staged_offcut_src_lot_id:
                quants = quants.filtered(lambda q: under(q.location_id, off))
            elif off:
                quants = quants.filtered(
                    lambda q: not under(q.location_id, off))
            seen = set()
            for quant in quants:
                if float_compare(need, 0.0, precision_rounding=rounding) <= 0:
                    break
                key = (quant.location_id, quant.lot_id, quant.package_id,
                       quant.owner_id)
                if key in seen:
                    continue
                seen.add(key)
                need -= move._update_reserved_quantity(
                    need, quant.location_id, lot_id=quant.lot_id,
                    package_id=quant.package_id, owner_id=quant.owner_id,
                    strict=True) or 0.0
        self._recompute_state()

    def _staged_assign_remnant(self):
        """Резервира ТОЧНО лота на остатъка под локацията на движението.

        ⏳ Докато лотът на пръта не е сменен (`staged_remnant_src_lot_id` и
        нето смени = 0) — нищо: трансферът чака. Заварените движения отпреди
        18.0.2.23.0 (без лот-източник) не чакат смяна — лотът им е готов.
        ⛔ Без остатъчната локация (дете на буфера на живо): там лежат вече
        валидирани остатъци със същото име на лота.
        """
        Quant = self.env["stock.quant"]
        Production = self.env["mrp.production"]
        off = Production._staged_offcut_location()
        for move in self:
            if move.staged_remnant_src_lot_id and \
                    Production._staged_bar_relabel_net(
                        move.staged_remnant_bar_ref) <= 0:
                continue
            lot = move.staged_remnant_lot_id
            rounding = move.product_id.uom_id.rounding
            need = move.product_qty - sum(
                move.move_line_ids.mapped("quantity_product_uom"))
            if float_compare(need, 0.0, precision_rounding=rounding) <= 0:
                continue
            root = move.location_id
            quants = Quant.search([
                ("product_id", "=", move.product_id.id),
                ("lot_id", "=", lot.id),
                ("location_id", "child_of", root.id),
                ("location_id.usage", "=", "internal"),
                ("quantity", ">", 0),
            ], order="in_date, id")
            if off and not (root.parent_path or "").startswith(
                    off.parent_path or "/-/"):
                quants = quants.filtered(
                    lambda q: not (q.location_id.parent_path or "").startswith(
                        off.parent_path or "/-/"))
            for location in quants.location_id.sorted(lambda l: l != root):
                if float_compare(need, 0.0, precision_rounding=rounding) <= 0:
                    break
                need -= move._update_reserved_quantity(
                    need, location, lot_id=lot, strict=True) or 0.0
        self._recompute_state()

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
        res = super().write(vals)
        # №117: количеството на реда се сменя при обновяване на подготовката —
        # опаковката-прът трябва да стои и тогава.
        if {"product_uom_qty", "picking_type_id", "product_id"} & set(vals):
            self._staged_set_bar_packaging()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._staged_set_bar_packaging()
        return moves

    def _staged_set_bar_packaging(self):
        """№117 (Любо, 01.10): редът на Pick Components носи опаковката-прът.

        Складът вижда пръти, не само метри (PC/00458: HUS 72770 420 m = 70
        пръта по „6000“). Опаковката-прът е по ADR-0050: ЕДИНСТВЕНАТА опаковка
        на продукта, по-голяма от 1 единица (прът 6 m = qty 6.0) — две опаковки
        значат две дължини и нищо не казва коя. Не се закръгля нищо: нецял
        брой пръти се вижда като дроб в колона „Пръти“ (product_packaging_qty).
        Сложена на ръка опаковка не се пипа.
        """
        for move in self:
            if move.product_packaging_id or move.state in ("done", "cancel"):
                continue
            wh = move.picking_type_id.warehouse_id
            if not wh or not wh.pbm_type_id or move.picking_type_id != wh.pbm_type_id:
                continue
            # №117 т.2 (тест 02.10, PC/00499): само мерки за ДЪЛЖИНА. Стъклопакетите
            # излизаха с опаковка „2.0 m2“ и брой 0,35 — прът е само в метри.
            if move.product_id.uom_id.category_id != self.env.ref(
                    "uom.product_uom_meter").category_id:
                continue
            opakovki = move.product_id.packaging_ids
            if len(opakovki) == 1 and opakovki.qty > 1.0:
                move.product_packaging_id = opakovki

    def _staged_keep_mts(self):
        """Суровинните движения на staged поръчка остават make_to_stock — ВИНАГИ.

        🔑 ЗАЩО И СЛЕД ОСВОБОЖДАВАНЕ (заглушаване на бродещия маршрут, 11.09):
        стане ли движението `make_to_order`, ядрото иска снабдяване за
        Pre-Production и правилото на склада ражда трансфер — зад гърба на
        подготовката. Мерено на fulltest:
        ```
        правило 136 „Стока → Pre-Production (MTO)"    7 движения
        правило 146 „Стока → Pre-Production"         10 движения
                                                     ────
                                                      17
        ```
        Дотук пазачът спираше само ДОКАТО поръчката не е освободена. Но точно
        там броди маршрутът: СЛЕД подготовката движението е Pre-Production →
        Production, ядрото вижда правило към тази локация, вдига го на MTO и
        снабдяването тръгва. Така се роди WH/PC/00341 — от смяна на количество
        по вече освободена поръчка, при празен WH/Stock.

        ⇒ Условието `not mo.staged_released` отпада. Буферът е локация: движението
        резервира от него, не си вика доставка. Това е същият принцип, по който
        падна веригата (`staged_pick_move_id`, 18.0.2.16.0).

        ⛔ Правилата НЕ се пипат — те важат и за други потоци. Заглушава се
        ПОВОДЪТ, не механизмът.

        ⚠️ Цената е избрана: staged МО вече не вика автоматично снабдяване за
        липсващ компонент. По замисъл — ПфП гейтва осъществимостта, а „колко да
        купя" е работа на точките за поръчка върху WH/Stock.
        """
        self.ensure_one()
        mo = self.raw_material_production_id
        if not (mo and mo.picking_type_id.staged_preparation_enabled):
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
