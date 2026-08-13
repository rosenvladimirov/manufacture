# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
# https://www.odoo.com/documentation/user/legal/licenses/licenses.html

import json
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    """Inject a 'preparation' gate **after** Plan in the MO lifecycle.

    State flow when ``picking_type_id.staged_preparation_enabled`` is True:

        draft
          ↓ action_confirm  (native — Pick/Store pickings и PO chain
          ↓                  се раждат веднага, MTO маршрутите работят нормално;
          ↓                  glass / armouring lot-tracked продукти получават
          ↓                  своите PO drafts at confirm time)
        confirmed
          ↓ button_plan (Enterprise Plan)  — workorders се планират нативно,
          ↓                                  after super(): state flip-ва към
          ↓                                  'preparation' за staged MOs.
        preparation                       ← Pre-production gate: workorders
          │                                 имат назначени dates, материалите
          │                                 имат PO chain, но операторът не
          │                                 може да стартира progress. Visual
          │                                 marker за "planned, awaiting
          │                                 floor release".
          ↓ action_prepare_production
        confirmed                         ← Released to floor: progress е
          ↓                                 unlock-нат, нищо логистично не
          ↓                                 се мени (Pick/Store вече живи).
        progress → to_close → done

    When ``staged_preparation_enabled`` е False, MO следва native draft →
    confirmed → progress → done flow непокътнато.

    **ХИБРИД (v18.0.2.2.0):** избирателно отлагане на вътрешните компонентни
    picks до floor release, БЕЗ да чупи glass/MTO chain-а:
      • lot-tracked компоненти (стъкло, барове) → нормален make_to_order на
        Confirm → PO/MTO chain тръгва навреме (доставчиците получават поръчки
        рано — точно това, което старият full-suppress чупеше).
      • non-lot-tracked компоненти (хардуер) → форсирани make_to_stock в
        stock.move._adjust_procure_method докато ``staged_released`` е False →
        вътрешните Стока→Pre-Production picks НЕ се раждат на Confirm. Раждат
        се едва на action_prepare_production (re-confirm с make_to_order).

    Така floor-ът не получава вътрешни трансфери преди „Подготви за
    производство", а стъклото/MTO пак получават PO навреме. Дискриминаторът е
    ``product.tracking`` (none → отлага се; lot/serial → не).

    **Фаза 2 / правило B (v18.0.2.5.0) — move-level недостиг + идемпотентност:**
    при action_prepare_production консумационният парон N (Pre-Production→
    Production) е make_to_stock и при assign резервира наличния Pre-Production
    буфер ПЪРВО. Пикът ① (Stock→Pre-Production) се оразмерява на НЕДОСТИГА =
    N.demand − N.reserved. Буферът покрива всичко → пик не се прави (Prepare е
    идемпотентен: повторен натиск не дублира — лекува 161-164). Материал,
    резервиран за ЧУЖДО МО, не се краде (assign взима само свободния quant), та
    правилно остава в недостига. Стъклото/lot-tracked си остава отделно (свой
    PO/MTO chain от Confirm; не влиза в дневния Stock→Pre-Production пик).

    **История:** v18.0.1.x правеше full-suppress (всичко след Prepare) →
    чупеше glass MTO. v18.0.2.0.0 махна suppress-а изцяло (всичко на Confirm) →
    floor получаваше трансфери преди подготовка. v18.0.2.2.0 = хибридът между
    двете. v18.0.2.4.0 добави батч агрегацията (Фаза 1). v18.0.2.5.0 = правило B.
    """

    _inherit = "mrp.production"

    state = fields.Selection(
        selection_add=[
            ("confirmed",),
            ("preparation", "Preparation"),
            ("progress",),
        ],
        ondelete={"preparation": lambda recs: recs.write({"state": "confirmed"})},
    )

    staged_preparation_enabled = fields.Boolean(
        related="picking_type_id.staged_preparation_enabled",
        store=False,
        help="Mirror of the picking type's flag — drives override visibility.",
    )

    staged_released = fields.Boolean(
        string="Released to floor",
        default=False,
        copy=False,
        help=(
            "True след 'Подготви за производство'. Докато е False (intermediate "
            "фаза), не-стъклените raw moves са swap-нати на Stock→Production "
            "(1-step, make_to_stock) → резервират от WH/Stock + ордерпоинтът "
            "вижда търсенето, БЕЗ физически Стока→Pre-Production pick. На "
            "'Подготви' се swap-ват обратно към буфера и се ражда вторият пикинг."
        ),
    )
    staged_cutting_optimization_id = fields.Many2one(
        "mrp.cutting.optimization",
        string="Staged cutting optimization",
        copy=False,
        help=(
            "Живата разкройна оптимизация, изчислена в _staged_optimize_and_gate "
            "(ПРЕДИ confirm). Whole-bar планът и forced-lot пиновете четат от нея. "
            "copy=False → backorder-ите не я наследяват (нямат нов разкрой)."))

    # ── Staged endpoint-swap helpers ────────────────────────────────────
    def _staged_intermediate_active(self):
        """True докато MO е staged и още НЕ е released към пода."""
        self.ensure_one()
        return bool(self.staged_preparation_enabled and not self.staged_released)

    def _staged_warehouse(self):
        self.ensure_one()
        return (self.picking_type_id.warehouse_id
                or self.location_src_id.warehouse_id
                or self.env["stock.warehouse"])

    @staticmethod
    def _staged_is_glass(product):
        """Стъклото (категория съдържа 'Glass') остава MTO — НЕ се swap-ва."""
        return "Glass" in (product.categ_id.complete_name or "")

    # ── Override: raw/finished move endpoints в intermediate фаза ────────
    # Не-стъклените raw moves → Stock→Production (1-step, make_to_stock):
    # резервират от WH/Stock, ордерпоинтът вижда търсенето, няма буфер-pick.
    # Finished move → Production→Stock (1-step). Стъклото остава нативно (pbm,
    # make_to_order) → glass PO + pick на Confirm. На 'Подготви' се swap-ват
    # обратно към pbm/sam буфера (action_prepare_production).

    def _get_move_raw_values(self, product, product_uom_qty, product_uom,
                             operation_id=False, bom_line=False):
        vals = super()._get_move_raw_values(
            product, product_uom_qty, product_uom, operation_id, bom_line)
        if not self._staged_intermediate_active():
            return vals
        if self._staged_is_glass(product):
            return vals
        wh = self._staged_warehouse()
        if wh and wh.lot_stock_id:
            vals["location_id"] = wh.lot_stock_id.id
            vals["warehouse_id"] = wh.id
            vals["procure_method"] = "make_to_stock"
        return vals

    def _get_move_finished_values(self, product_id, product_uom_qty, product_uom,
                                  operation_id=False, byproduct_id=False,
                                  cost_share=0):
        vals = super()._get_move_finished_values(
            product_id, product_uom_qty, product_uom,
            operation_id, byproduct_id, cost_share)
        if not self._staged_intermediate_active():
            return vals
        wh = self._staged_warehouse()
        if wh and wh.lot_stock_id:
            vals["location_dest_id"] = wh.lot_stock_id.id
            vals["warehouse_id"] = wh.id
        return vals

    # ── Override: button_plan (EE Plan) ─────────────────────────────────
    # Native ``button_plan`` (mrp/models/mrp_production.py:1613):
    #     orders_to_plan = self.filtered(lambda order: not order.is_planned)
    #     orders_to_confirm = orders_to_plan.filtered(lambda mo: mo.state == 'draft')
    #     orders_to_confirm.action_confirm()
    #     for order in orders_to_plan:
    #         order._plan_workorders()
    #     return True
    #
    # След като super() мине → workorders са планирани (is_planned=True),
    # raw moves имат свои Pick pickings ако warehouse е 2/3-step, PO drafts
    # за MTO компоненти са родени. Flip-ваме state към 'preparation' за
    # staged-enabled MOs — това е post-plan gate преди progress.

    def button_plan(self):
        # Re-staging блок (#10): вече стейджнато/пуснато MO не се планира повторно.
        for production in self:
            if production.staged_released:
                raise UserError(_(
                    "MO %s is already staged/released — re-planning is blocked "
                    "(prevents duplicate transfers / negative stock).",
                    production.name))
        result = super().button_plan()
        for production in self:
            if (
                production.staged_preparation_enabled
                and production.state == "confirmed"
            ):
                production.state = "preparation"
        return result

    def button_mark_done(self):
        # Produce ГАРД (Phase 2, B+A — дизайн Любо, msg 157110): staged MO НЕ
        # може да Produce, ако whole-bar трансферът към Pre-Production още не е
        # валидиран — иначе консумацията не намира материал в буфера и (при
        # разрешен отрицателен склад) бие ТИХО на минус (най-вероятният корен на
        # предишния омазан случай). Инвариант = РЕЗЕРВАЦИЯТА; твърд (пренася
        # force, защото е ПРЕДИ super()); съобщението сочи висящия WH/PC трансфер.
        # СТРУКТУРЕН тригер (adversarна верификация): викаме за ВСЯКО MO —
        # гардът е no-op ако няма staged bar pbm-леги. Не се ключа на мутируемия
        # staged_released (copy=False → backorder-ите го губят) нито на
        # picking-type флага → backorder-и и директен Produce от 'preparation'
        # СЪЩО се охраняват (и двете заобикаляха стария флагов тригер).
        for production in self:
            production._staged_guard_pre_production()
        # Whole-bar B credit-back (Любо 157140): offcut by-product move-овете се
        # създават ПРЕДИ super() → pre_button_mark_done/_mark_byproducts_as_
        # produced ги вижда (picked=True), после _post_inventory→_cal_price
        # override ги остойностява (cost_share) → offcut намалява себестойността
        # на готовия продукт СТРОГО FIFO. Идемпотентно (guard на входа).
        for production in self:
            production._staged_create_offcut_byproducts()
        # #10: производството да работи И от 'preparation' (native очаква
        # confirmed/progress). Директен mark_done от Preparation → авто-старт.
        for production in self:
            if production.state == "preparation":
                production.state = "progress"
        return super().button_mark_done()

    def _staged_pattern_owner(self, pattern):
        """Детерминистичен owner-MO id на pattern-а (споделеният прът се брои
        ВЕДНЪЖ). Owner = MO с макс piece-метри на pattern-а, tie→най-малко id;
        fallback на product-ниво (в opt.production_ids) за unlinked patterns.
        ЕДНА логика за fresh plan / offcut leg / credit-back → нула двойно
        кредитиране при cross-MO shared бар. Връща owner id или False.
        """
        self.ensure_one()
        opt = self.staged_cutting_optimization_id
        Piece = self.env.get("mrp.cutting.piece")
        if not opt or Piece is None:
            return False
        mo_m = {}
        for pc in Piece.search([("cutting_pattern_id", "=", pattern.id),
                                ("production_id", "!=", False)]):
            mo_m[pc.production_id.id] = mo_m.get(pc.production_id.id, 0.0) \
                + (pc.length_mm or 0.0) * (pc.quantity or 0.0)
        if mo_m:
            return max(mo_m, key=lambda mid: (mo_m[mid], -mid))
        # unlinked → product-ниво fallback измежду MO-тата в оптимизацията
        opt_mo_ids = set(opt.production_ids.ids)
        same_prod = opt.pattern_ids.filtered(
            lambda p: p.bar_product_id == pattern.bar_product_id)
        prod_mo = {}
        for pc in Piece.search([("cutting_pattern_id", "in", same_prod.ids),
                                ("production_id", "!=", False)]):
            if pc.production_id.id in opt_mo_ids:
                prod_mo[pc.production_id.id] = prod_mo.get(
                    pc.production_id.id, 0.0) \
                    + (pc.length_mm or 0.0) * (pc.quantity or 0.0)
        cand = prod_mo or {mid: 0.0 for mid in opt_mo_ids}
        if not cand:
            return False
        return max(cand, key=lambda mid: (cand[mid], -mid))

    def _staged_whole_bar_plan(self):
        """Whole-bar консумация (costing A, Любо 157140) per бар-продукт, UoM=м.

        Връща {product: (whole_bar_meters, [source_lots])} за СВЕЖИ цели пръти на
        self (source_offcut_lot_id празно; offcut-ите → отделен leg). Анкер =
        staged_cutting_optimization_id. meters = Σ(usage_count × bar_capacity_mm)
        /1000 за pattern-и, чийто owner (_staged_pattern_owner) е MO∈self.
        Инвариант: Σ_batch == total_bars_used × capacity/1000 (валидирано 572/88).
        """
        self.ensure_one()
        opt = self.staged_cutting_optimization_id
        if not opt or opt.state != "done":
            return {}
        self_ids = set(self.ids)
        plan = {}
        for pattern in opt.pattern_ids.filtered(
                lambda p: not p.source_offcut_lot_id
                and p.source_model == "stock.lot" and p.source_id
                and p.bar_product_id):
            if self._staged_pattern_owner(pattern) not in self_ids:
                continue
            product = pattern.bar_product_id
            meters, lots = plan.get(product, (0.0, set()))
            meters += pattern.usage_count * pattern.bar_capacity_mm / 1000.0
            lots.add(pattern.source_id)
            plan[product] = (meters, lots)
        return {p: (m, sorted(lots)) for p, (m, lots) in plan.items()}

    def _staged_offcut_plan(self):
        """Offcut-sourced консумация per (bar_product, source_offcut_lot): метри.
        Патерни с source_offcut_lot_id SET (режат от СЪЩЕСТВУВАЩ offcut лот).
        meters = usage_count × bar_capacity_mm/1000 (за offcut pattern
        bar_capacity_mm == source_offcut_lot.offcut_length_mm). Owner attribution
        ИДЕНТИЧНА на fresh плана (_staged_pattern_owner). fresh/offcut патерните
        са взаимно изключващи се (source_offcut_lot_id gate) → без double-count.
        Връща {product: {lot: meters}}.
        """
        self.ensure_one()
        opt = self.staged_cutting_optimization_id
        if not opt or opt.state != "done":
            return {}
        self_ids = set(self.ids)
        plan = {}
        for pattern in opt.pattern_ids.filtered(
                lambda p: p.source_offcut_lot_id and p.bar_product_id):
            if self._staged_pattern_owner(pattern) not in self_ids:
                continue
            product = pattern.bar_product_id
            lot = pattern.source_offcut_lot_id
            meters = pattern.usage_count * pattern.bar_capacity_mm / 1000.0
            by_lot = plan.setdefault(product, {})
            by_lot[lot] = by_lot.get(lot, 0.0) + meters
        return plan

    def _staged_offcut_consumptions(self, offcut_plan, ref_by_product):
        """Стъпка 6: Offcut→Production консумационни леги за pattern-и с
        source_offcut_lot_id SET. Отделен, ADDITIVE leg — НЕ през Pre-Production
        буфера, а ДИРЕКТНО от 'Remnant/Offcut' локацията (adapter._offcut_
        location), forced към offcut лота, веднага резервиран (лотът физически
        седи там от credit-back на предишно MO). offcut_plan={product:{lot:m}};
        ref_by_product={product:(uom_id, wo_id, op_id)} снет ПРЕДИ мутациите.
        """
        self.ensure_one()
        Move = self.env["stock.move"]
        if not offcut_plan or "forced_lot_ids" not in Move._fields:
            return Move
        adapter = self.env.get("cutting.source.adapter.mrp_production")
        if adapter is None:
            return Move
        offcut_loc = adapter._offcut_location()
        prod_loc = self.production_location_id
        pg = self.procurement_group_id
        legs = Move
        for product, by_lot in offcut_plan.items():
            uom_id, wo_id, op_id = ref_by_product.get(
                product, (product.uom_id.id, False, False))
            for lot, meters in by_lot.items():
                if meters <= 0.0 or not lot:
                    continue
                leg = Move.create({
                    "name": self.name,
                    "product_id": product.id,
                    "product_uom": uom_id,
                    "product_uom_qty": meters,
                    "location_id": offcut_loc.id,
                    "location_dest_id": prod_loc.id,
                    "procure_method": "make_to_stock",
                    "raw_material_production_id": self.id,
                    "group_id": pg.id if pg else False,
                    "picking_type_id": self.picking_type_id.id,
                    "workorder_id": wo_id,
                    "operation_id": op_id,
                    "company_id": self.company_id.id,
                    "forced_lot_ids": [(6, 0, lot.ids)],
                    "state": "draft",
                })
                leg.manual_consumption = False
                legs |= leg
        if legs:
            legs._action_confirm(merge=False)
            legs._action_assign()   # резервира от Remnant/Offcut локацията
        return legs

    def _staged_create_offcut_byproducts(self):
        """Стъпка 7 (Whole-bar B credit-back): offcut остатъкът → by-product
        move на move_finished_ids (Production→Remnant/Offcut), forced към НОВ
        is_offcut лот. Стойността се сетва през cost_share в _cal_price → offcut
        намалява СЕБЕСТОЙНОСТТА на готовия продукт СТРОГО FIFO, ДИРЕКТНО (не
        after-super inventory gain). НЕ вика _create_offcut_lots (механизъм (a)
        = inventory adjustment = DOUBLE-VALUE). Owner attribution → само owner-MO
        ражда offcut (нула двойно кредитиране cross-MO). Спазва offcut_keep_cap.
        """
        self.ensure_one()
        Move = self.env["stock.move"]
        # ИДЕМПОТЕНТНОСТ: повторен вход (consumption/backorder wizard re-entry) →
        # не дублирай by-products/лотове.
        if self.move_byproduct_ids.filtered("is_staged_offcut"):
            return Move
        opt = self.staged_cutting_optimization_id
        if not opt or opt.state != "done":
            return Move
        if "is_staged_offcut" not in Move._fields \
                or "forced_lot_ids" not in Move._fields:
            return Move
        adapter = self.env.get("cutting.source.adapter.mrp_production")
        if adapter is None:
            return Move
        offcut_loc = adapter._offcut_location()
        prod_loc = self.production_location_id
        Lot = self.env["stock.lot"]
        self_ids = set(self.ids)
        cap = opt.offcut_keep_cap
        legs = Move
        for pattern in opt.pattern_ids.filtered(
                lambda p: p.disposition == "offcut" and p.remnant_length > 0
                and p.bar_product_id):
            if self._staged_pattern_owner(pattern) not in self_ids:
                continue
            product = pattern.bar_product_id
            meters = pattern.remnant_length / 1000.0
            for bar_num in range(pattern.usage_count):
                if cap and Lot.search_count([
                        ("product_id", "=", product.id),
                        ("is_offcut", "=", True)]) >= cap:
                    break   # cap достигнат → остатъкът е скрап (без by-product)
                lot = Lot.create({
                    "name": "OFF-%d-P%d-%d" % (
                        int(round(pattern.remnant_length)), pattern.id,
                        bar_num + 1),
                    "product_id": product.id,
                    "company_id": self.company_id.id,
                    "mrp_cutting_pattern_id": pattern.id,
                    "is_offcut": True,
                    "offcut_length_mm": pattern.remnant_length,
                    "ref": "Offcut (B credit-back) from %s / %s" % (
                        pattern.name, self.name),
                })
                leg = Move.create({
                    "name": self.name,
                    "product_id": product.id,
                    "product_uom": product.uom_id.id,
                    "product_uom_qty": meters,
                    "quantity": meters,
                    "location_id": prod_loc.id,
                    "location_dest_id": offcut_loc.id,
                    "production_id": self.id,       # → move_finished_ids link
                    "company_id": self.company_id.id,
                    "picking_type_id": self.picking_type_id.id,
                    "byproduct_id": False,          # additional → move_byproduct_ids
                    "cost_share": 0.0,              # placeholder; истинската в _cal_price
                    "is_staged_offcut": True,
                    "forced_lot_ids": [(6, 0, lot.ids)],
                    "state": "draft",
                })
                leg.picked = True                   # by-product = произведен
                legs |= leg
        if legs:
            legs._action_confirm(merge=False)
        return legs

    def _cal_price(self, consumed_moves):
        """Whole-bar B credit-back (Любо 157140): offcut by-product move-овете
        (is_staged_offcut) абсорбират ТОЧНО FIFO стойността на остатъчната
        дължина → намаляват СЕБЕСТОЙНОСТТА на готовия продукт СТРОГО FIFO, ПРЕДИ
        core да раздели. cost_share се смята ТУК (total_cost и консумационните
        SVL съществуват едва сега). stock.move.cost_share=digits=0 → пълна
        прецизност (offcut е additional move, не bom.byproduct digits=(5,2)).
        """
        self.ensure_one()
        offcut_moves = self.move_byproduct_ids.filtered(
            lambda m: m.is_staged_offcut and m.state not in ("done", "cancel")
            and m.quantity > 0)
        finished_move = self.move_finished_ids.filtered(
            lambda x: x.product_id == self.product_id
            and x.state not in ("done", "cancel") and x.quantity > 0)
        if offcut_moves and consumed_moves and finished_move:
            finished_move.ensure_one()
            # total_cost — РЕПЛИКА едно-към-едно на mrp_account._cal_price.
            work_center_cost = sum(
                wo._cal_cost() for wo in self.workorder_ids)
            quantity = finished_move.product_uom._compute_quantity(
                finished_move.quantity, finished_move.product_id.uom_id)
            extra_cost = self.extra_cost * quantity
            total_cost = (-sum(consumed_moves.sudo()
                               .stock_valuation_layer_ids.mapped("value"))
                          + work_center_cost + extra_cost)
            if float_compare(total_cost, 0.0, precision_digits=2) > 0:
                for off in offcut_moves:
                    bar = off.product_id
                    cons = consumed_moves.filtered(
                        lambda m: m.product_id == bar)
                    cons_val = -sum(cons.sudo()
                                    .stock_valuation_layer_ids.mapped("value"))
                    cons_qty = sum(
                        m.product_uom._compute_quantity(
                            m.quantity, m.product_id.uom_id) for m in cons)
                    if cons_qty <= 0 or cons_val <= 0:
                        off.cost_share = 0.0
                        continue
                    unit_cost = cons_val / cons_qty          # FIFO цена/метър
                    off_qty = off.product_uom._compute_quantity(
                        off.quantity, off.product_id.uom_id)  # остатък, метри
                    offcut_value = off_qty * unit_cost
                    off.cost_share = min(
                        offcut_value / total_cost * 100.0, 100.0)
        return super()._cal_price(consumed_moves)

    def _staged_guard_pre_production(self):
        """Produce гард (B+A): блокира Produce, докато staged Pre-Production
        bar-консумациите не са РЕЗЕРВИРАНИ (`assigned`) — т.е. материалът реално
        е в буфера (whole-bar трансферът е валидиран).

        Скоуп: САМО режещи/бар входове (продуктите с cut.piece на това MO —
        вкл. РЪЧНИ pieces). Обков/стъкло/по-късните операции са ИЗВЪН проверката
        (идват на монтаж) — adversarна верификация: старият само-стъкло филтър
        блокираше и обков, чупейки Phase-2 замисъла „режи барове сега, обков
        после". „Покрито изцяло от буфера" случаят минава (легът е assigned).
        Съобщението (A) именува висящите Stock→Pre-Production трансфери.
        """
        self.ensure_one()
        wh = self._staged_warehouse()
        pbm = wh.pbm_loc_id if wh else False
        if not pbm:
            return
        # Режещите/бар продукти = тези с cut.piece на MO-то (instance, вкл. ръчни
        # — не само BoM-темплейт). Само техните pbm-леги охраняваме.
        bar_products = self.cutting_piece_ids.mapped("product_id")
        if not bar_products:
            return
        legs = self.move_raw_ids.filtered(
            lambda m: m.location_id == pbm
            and m.state not in ("done", "cancel")
            and m.product_id in bar_products)
        unreserved = legs.filtered(lambda m: m.state != "assigned")
        if not unreserved:
            return
        # A: висящите upstream трансфери (M: Stock→Pre-Prod) за actionable текст.
        pending = unreserved.move_orig_ids.filtered(
            lambda m: m.location_dest_id == pbm
            and m.picking_id and m.picking_id.state not in ("done", "cancel")
        ).picking_id
        names = ", ".join(pending.mapped("name")) or _("the staging transfer")
        raise UserError(_(
            "Cannot produce %(mo)s — its components are not yet in "
            "Pre-Production (reservation missing). Validate the staging "
            "transfer first: %(picks)s.\n\nNot reserved: %(prods)s",
            mo=self.name, picks=names,
            prods=", ".join(unreserved.mapped("product_id.display_name")),
        ))

    # ── Action: prepare for production (preparation → confirmed) ────────
    # Release-to-floor button. Сетва staged_released=True (спира deferral-а в
    # stock.move._adjust_procure_method), после re-confirm-ва отложените
    # (non-lot-tracked) raw moves → pull rule ражда вътрешните Стока→
    # Pre-Production picks ЕДВА сега. Lot-tracked moves вече са materialized
    # на Confirm и не се пипат. Накрая flip към 'confirmed' → unlock progress.

    def action_prepare_production(self):
        # Отваря потвърждение „Confirm start the MO(s)?" — планерът решава дали
        # стейджнатото производство да СТАРТИРА веднага (In Processing) или да
        # остане в Preparation. Batch: едно потвърждение за всички.
        staged = self.filtered(
            lambda p: p.staged_preparation_enabled
            and p.state == "preparation" and not p.staged_released)
        if not staged:
            raise UserError(_(
                "No staged MO in 'Preparation' to prepare. (Already released "
                "MOs cannot be re-staged.)"))
        # Phase 2 (дизайн Любо, msg 157090): ОПТИМИЗАЦИЯ + FEASIBILITY ГЕЙТ
        # стават ТУК — ПРЕДИ потвърждението и ПРЕДИ всякакъв ангажимент. При
        # недостиг на бар-сток гейтът вдига чист UserError → транзакцията се
        # откатва, wizard изобщо не се отваря, 0 ангажимент (никакъв
        # staged_released/move/резервация/progress). Batch вече е оптимизирал
        # cross-MO → прескачаме (staged_skip_optimize), за да няма двоен разкрой.
        if not self.env.context.get("staged_skip_optimize"):
            staged._staged_optimize_and_gate()
        return {
            "type": "ir.actions.act_window",
            "name": _("Prepare for Production"),
            "res_model": "mrp.production.prepare.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_production_ids": [(6, 0, staged.ids)],
                # разкроят е cross-MO в batch → wizard-ът да не го повтаря per-MO
                "staged_skip_optimize": self.env.context.get("staged_skip_optimize", False),
            },
        }

    def _staged_do_prepare(self, start=False):
        # Ядрото на стейджинга (материализация Стока→Pre-Production). ``start``
        # идва от wizard-а: True → MO стартира (In Processing/progress + lock);
        # False → остава в Preparation (стартира се по-късно).
        for production in self:
            if not production.staged_preparation_enabled:
                raise UserError(_(
                    "Staged preparation is not enabled for this picking type. "
                    "Enable 'Staged Preparation' on '%s' first.",
                    production.picking_type_id.display_name,
                ))
            # Re-staging блок (#10): вече стейджнато MO не се стейджва повторно
            # (без дублирани трансфери/отрицателни наличности).
            if production.staged_released:
                raise UserError(_(
                    "MO %s is already staged/released — cannot re-stage.",
                    production.name))
            if production.state != "preparation":
                raise UserError(_(
                    "MO %(name)s is in state '%(state)s'; only MOs in "
                    "'Preparation' can be prepared.",
                    name=production.name, state=production.state,
                ))

            # Phase 2 (дизайн Любо): разкроят + feasibility гейтът вече минаха
            # ПРЕДИ confirm (виж action_prepare_production / _batch →
            # _staged_optimize_and_gate). Тук СЛЕД потвърждение САМО
            # материализираме — резервации/трансфер с ОПТИМИЗИРАНИТЕ количества
            # + progress. Нищо не се оптимизира тук (инверсията на реда).

            # 1) Маркираме released.
            production.staged_released = True

            wh = production._staged_warehouse()
            pbm = wh.pbm_loc_id
            prod_loc = production.production_location_id

            # mrp_one_step или липсва Pre-Production → нищо за местене (no-op).
            if wh.manufacture_steps not in ("pbm", "pbm_sam") or not pbm:
                production.state = "progress" if start else "preparation"
                if start:
                    production.is_locked = True
                continue

            # 2) Procurement група (новите picks да не merge-ват с други MO).
            if not production.procurement_group_id:
                production.procurement_group_id = self.env[
                    "procurement.group"
                ].create({
                    "name": production.name,
                    "move_type": production.move_type or "direct",
                    "partner_id": production.partner_id.id
                    if production.partner_id else False,
                })
            pg = production.procurement_group_id
            pbm_type = wh.pbm_type_id

            # 3) Кандидати: не-стъклени raw moves, които на Confirm са 1-step
            #    Stock → Virtual-Production. Чупим при ДЕСНИЯ край (Virtual-Prod).
            candidates = production.move_raw_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
                and not self._staged_is_glass(m.product_id)
                and m.location_dest_id == prod_loc
                and m.location_id == wh.lot_stock_id)

            # Whole-bar A (Любо 157140): консумацията N зарежда ЦЕЛИ ФИЗИЧЕСКИ
            # ПРЪТИ (метри) вместо дробния полезно×(1+loss). Свежият план + offcut
            # планът се четат ВЕДНАГА (offcut-ите координират override-а).
            _plan = production._staged_whole_bar_plan()
            _offcut_plan = production._staged_offcut_plan()
            # Ref (uom/workorder/operation) per продукт ПРЕДИ мутациите —
            # offcut leg-ът го ползва (fully-offcut кандидатите се cancel-ват).
            _ref_by_product = {}
            for _m in candidates:
                _ref_by_product.setdefault(_m.product_id, (
                    _m.product_uom.id, _m.workorder_id.id, _m.operation_id.id))
            # Fully-offcut продукти (в offcut-плана, но НЕ в свежия): целият
            # demand идва от offcut лотове → свежият Stock→Virtual-Production
            # кандидат е ФИКТИВЕН → cancel, за да не роди фантомен Stock→Pre-Prod
            # пик за несъществуващ свеж буфер. Offcut leg-ът покрива 100%.
            _fully_offcut = set(_offcut_plan) - set(_plan)
            if _fully_offcut:
                _drop = candidates.filtered(
                    lambda m: m.product_id in _fully_offcut)
                _drop._action_cancel()
                candidates -= _drop
            # За всеки бар-продукт делим whole-bar метрите пропорционално на
            # кандидат-move-овете; последният поема rounding остатъка. Продукт
            # БЕЗ свеж план (стъкло/обков/ръчни/fully-offcut) → без override.
            _wb_override = {}
            if _plan:
                _by_prod = {}
                for _M in candidates:
                    _by_prod.setdefault(_M.product_id, self.env["stock.move"])
                    _by_prod[_M.product_id] |= _M
                for _prod, _moves in _by_prod.items():
                    if _prod not in _plan:
                        continue
                    _target = _plan[_prod][0]           # цели свежи пръти, метри
                    if _target <= 0.0:
                        continue
                    _moves = _moves.sorted("id")
                    _old = sum(_moves.mapped("product_uom_qty")) or 0.0
                    _n, _run = len(_moves), 0.0
                    for _i, _mv in enumerate(_moves):
                        if _i == _n - 1:
                            _share = _target - _run     # остатъкът → без drift
                        else:
                            _frac = (_mv.product_uom_qty / _old) if _old > 0 \
                                else 1.0 / _n
                            _share = round(_target * _frac, 6)
                            _run += _share
                        _wb_override[_mv.id] = _share

            # B изисква РЕД: N (консумация) резервира Pre-Production буфера
            # ПРЕДИ да се закачи веригата към пика. Ако ① пикът се линкне към N
            # преди assign, N влиза в 'waiting' (чака origin-а) и НЕ резервира
            # наличния буфер. Затова: (а) създаваме N БЕЗ верига, (б) assign-ваме
            # → резервират буфера, (в) оразмеряваме пика на недостига и (г) ЧАК
            # ТОГАВА линкваме веригата (резервацията оцелява — валидирано).
            pairs = []                       # [(M пик, N консумация), ...]
            for M in candidates:
                if M.state == "assigned":
                    M._do_unreserve()
                # Планираният workorder стои на M (от button_plan). Той трябва
                # да отиде на КОНСУМАЦИЯТА (N), не на пика — иначе компонентът
                # не е закачен за никоя операция и Produce гърми с „supply
                # Lot/Serial". (operation_id се копира; workorder_id е copy=False.)
                wo_id = M.workorder_id.id
                # ② НОВ парон (консумация): Pre-Production → Virtual-Production,
                #    procure_method = make_to_stock, БЕЗ верига (move_orig=False)
                #    → при assign резервира свободния Pre-Production буфер.
                N = M.copy({
                    "location_id": pbm.id,
                    "location_dest_id": prod_loc.id,
                    "procure_method": "make_to_stock",
                    "raw_material_production_id": production.id,
                    "group_id": pg.id,
                    "picking_id": False,
                    "picking_type_id": production.picking_type_id.id,
                    "workorder_id": wo_id,
                    "move_orig_ids": False,
                    "move_dest_ids": False,
                    # Whole-bar A (Любо 157140): ИЗРИЧЕН пин на планирания бар-лот
                    # върху консумацията N — НЕ разчитаме на copy=True на
                    # forced_lot_ids. Ако forced_lot_multi flip-не copy=False, N
                    # тихо би теглил ПРОИЗВОЛЕН лот от буфера (costing/проследимост
                    # се чупят БЕЗ грешка). Източникът е M.forced_lot_ids —
                    # авторитетно пинат в _staged_optimize_and_gate = pattern
                    # .source_id (важи за fresh И offcut). Празно → без пин.
                    "forced_lot_ids": [(6, 0, M.forced_lot_ids.ids)],
                    # Whole-bar A: N консумира ЦЕЛИ пръти (метри), не дробното
                    # полезно×(1+loss). Продукт без разкроен план → native qty
                    # (нулева регресия за стъкло/обков/ръчни). Резервационният ред
                    # по-долу е ИНВАРИАНТЕН на демандната стойност (UoM=метри).
                    "product_uom_qty": _wb_override.get(M.id, M.product_uom_qty),
                    "state": "draft",
                })
                # forced-lot консумация → лотът е предопределен → авто-консумация
                # (manual_consumption=False). Иначе workorder-attached tracked
                # move става manual_consumption=True и Produce All иска ръчно
                # регистриране на лота → „supply Lot/Serial" грешка (Любо го хвана).
                if N.forced_lot_ids:
                    N.manual_consumption = False
                # ① съществуващият move → ПЪРВИ ПИКИНГ: Stock → Pre-Production.
                #    Десният край се отлепя от Virtual-Prod; Stock-краят (и
                #    procurement-ът от Confirm) ОСТАВА. Веригата към N се закача
                #    ПО-КЪСНО (виж по-долу), за да не блокира буфер-резервацията.
                M.write({
                    "location_dest_id": pbm.id,
                    "raw_material_production_id": False,
                    "workorder_id": False,
                    "group_id": pg.id,
                    "picking_type_id": pbm_type.id if pbm_type
                    else M.picking_type_id.id,
                })
                pairs.append((M, N))

            production.state = "progress" if start else "preparation"
            if start:
                production.is_locked = True  # старт → заключено (без edit/re-plan)
            if pairs:
                # ② Потвърждаваме консумациите и ги assign-ваме (още БЕЗ верига)
                #    → make_to_stock N резервира наличния Pre-Production буфер.
                #    reserved = N.quantity (core stock_move._action_assign:
                #    reserved_availability = move.quantity). Assign взима само
                #    СВОБОДНИЯ quant → материал, резервиран за ЧУЖДО МО, не се
                #    пипа → правилно остава в недостига (не крадем чуждото).
                consumptions = self.env["stock.move"].union(
                    *[N for _, N in pairs])
                consumptions._action_confirm(merge=False)
                consumptions._action_assign()
                # ① B — оразмеряваме всеки пик на НЕДОСТИГА = demand − reserved.
                kept_picks = self.env["stock.move"]
                covered = 0
                for M, N in pairs:
                    rounding = N.product_uom.rounding
                    shortage = N.product_uom_qty - N.quantity
                    if float_compare(shortage, 0.0,
                                     precision_rounding=rounding) <= 0:
                        # Буферът покрива всичко → пик НЕ е нужен (идемпотентно:
                        # повторен Prepare не дублира пик — лекува 161-164).
                        M._action_cancel()
                        covered += 1
                        continue
                    M.product_uom_qty = shortage            # само недостигът
                    # Закачаме веригата СЕГА (буфер-резервацията на N оцелява) →
                    # при done на пика native propagation дораздели N остатъка.
                    M.write({"move_dest_ids": [(6, 0, [N.id])]})
                    kept_picks |= M
                if kept_picks:
                    # пиковете → assign към Pick Components picking (за да се
                    # ПОКАЖАТ като трансфер за оператора) + резервация от Stock.
                    kept_picks.write({"state": "confirmed"})
                    kept_picks._assign_picking()
                    kept_picks._action_assign()             # резервират от Stock
                _logger.info(
                    "Staged preparation (B): MO %s → %d консумация(и); %d пик(а) "
                    "за недостига, %d покрити изцяло от Pre-Production буфер",
                    production.name, len(pairs), len(kept_picks), covered)

            # ── Стъпка 6: Offcut-sourced консумационни леги (additive) ──
            # Патерни рязани от съществуващ offcut → Offcut→Production leg,
            # резервиран ДИРЕКТНО от Remnant/Offcut локацията (не Pre-Prod буфер).
            offcut_legs = production._staged_offcut_consumptions(
                _offcut_plan, _ref_by_product)
            if offcut_legs:
                _logger.info(
                    "Staged offcut (6): MO %s → %d Offcut→Production leg(а) "
                    "(forced offcut лотове, резервирани от Remnant/Offcut).",
                    production.name, len(offcut_legs))

        # ── CROSS-MO АГРЕГАЦИЯ → 1 Stock→Pre-Production трансфер/ден (Phase 2) ──
        # Wizard-ът вика self.production_ids._staged_do_prepare на ЦЯЛАТА партида
        # наведнъж → тук (recordset ниво, СЛЕД per-MO цикъла) агрегираме
        # новородените Pick Components пикинги в ЕДИН. Преместено от
        # action_prepare_production_batch (там беше НЕДОСТИЖИМО след return —
        # „1 трансфер/ден" никога не се случваше; adversarна верификация го хвана).
        pc_pickings = self.env["stock.picking"]
        for production in self:
            wh = production._staged_warehouse()
            pbm = wh.pbm_loc_id if wh else False
            if not pbm:
                continue
            bridges = production.move_raw_ids.filtered(
                lambda m: m.location_id == pbm
                and m.state not in ("done", "cancel"))
            first_picks = bridges.move_orig_ids.filtered(
                lambda m: m.location_dest_id == pbm and m.picking_id
                and m.picking_id.state not in ("done", "cancel"))
            pc_pickings |= first_picks.picking_id
        if len(pc_pickings) > 1:
            target = pc_pickings.sorted("id")[0]
            others = pc_pickings - target
            others.move_ids.write({"picking_id": target.id})
            origins = sorted({o for o in pc_pickings.mapped("origin") if o})
            if origins:
                target.origin = ", ".join(origins)[:2000]
            others.filtered(lambda p: not p.move_ids).unlink()
            # #724: сливаме и движенията per (продукт+лот). Унифицираме
            # date_deadline (distinct поле — иначе блокира cross-MO merge).
            deadlines = [d for d in target.move_ids.mapped("date_deadline") if d]
            if deadlines:
                target.move_ids.write({"date_deadline": min(deadlines)})
            # _merge_moves пази forced_lot_ids разделно (forced_lot_multi distinct
            # поле) → лот-tracked барове НЕ се сливат cross-lot; веригата M→N оцелява.
            moves_before = len(target.move_ids)
            target.do_unreserve()
            target.move_ids._merge_moves()
            target.action_assign()  # ре-резервация (+ forced_lot fill)
            _logger.info(
                "Staged batch: %d PC пикинга → 1 агрегиран трансфер %s "
                "(#724 merge: %d → %d движения)",
                len(pc_pickings), target.name, moves_before,
                len(target.move_ids))
        return True

    def _staged_optimize_and_gate(self):
        """Phase 2 (дизайн Любо, msg 157090): ОПТИМИЗАЦИЯ + FEASIBILITY ГЕЙТ,
        изпълнени ПРЕДИ всякакъв ангажимент (инверсията на реда).

        Пуска cross-MO разкроя за self (само MO с cutting pieces). Оптимизаторът
        чете СВОБОДНАТА бар-картина — free_qty (net от паралелните резервации) +
        offcut/remnant лотове (Phase 1 „Remnant/Offcut" локацията; адаптерът чете
        is_offcut лотове). Reservation-aware (Любо 157257/157258): адаптерът вади
        вече заплютото от други MO-та (`_lot_free_qty`) → гейтът лови и частично
        покритите случаи (MO 10/11-тип), не само нулевите. При НЕДОСТИГ
        (оптимизаторът не може да покрие всички парчета срещу СВОБОДНИТЕ пръти)
        → ЧИСТ UserError с недостига; извикващата транзакция се откатва
        → 0 ангажимент. При УСПЕХ нищо не се резервира/мести — само се подготвя
        планът (patterns + loss-коефициент); материализацията идва СЛЕД confirm
        (в `_staged_do_prepare`).

        Огледало на предишния разкрой, но като ТВЪРД ГЕЙТ (не swallow-ва).
        Липсващ cutting стек (модулите не са инсталирани) → no-op (не гейтва).
        """
        Opt = self.env.get("mrp.cutting.optimization")
        adapter = self.env.get("cutting.source.adapter.mrp_production")
        if Opt is None or adapter is None:
            return None
        # MO-та, които оптимизаторът реално ще реже. Дискриминаторът е СЪЩОТО,
        # което адаптерът реже — instance `cutting_piece_ids` (вкл. РЪЧНИ pieces
        # без BoM-темплейт) ИЛИ BoM-темплейт pieces (материализират се при
        # optimize). adversarна верификация: само-BoM-темплейт филтърът
        # прескачаше MO с ръчни pieces → минаваха БЕЗ feasibility гейт.
        with_pieces = self.filtered(
            lambda p: p.cutting_piece_ids
            or (p.bom_id
                and any(p.bom_id.bom_line_ids.mapped("cutting_piece_ids"))))
        if not with_pieces:
            return None
        opt = Opt.create({
            "name": _("Cut: %s") % (", ".join(with_pieces.mapped("name"))[:60]),
            "material_domain": "mrp_production",
            "production_ids": [(6, 0, with_pieces.ids)],
        })
        try:
            opt.action_optimize()
        except UserError as exc:
            # FEASIBILITY ГЕЙТ: недостиг на бар-сток → ЧИСТ стоп. UserError-ът
            # откатва цялата транзакция (вкл. opt.create/patterns) → нищо не е
            # ангажирано. Показваме недостига на оператора (кой профил/парче).
            detail = exc.args[0] if exc.args else str(exc)
            raise UserError(_(
                "Cannot prepare for production — cutting is NOT feasible with "
                "the available bar stock (including offcuts/remnants):\n\n%s\n\n"
                "Nothing was committed. Add bar stock (or recover offcuts) and "
                "retry.", detail))
        # Whole-bar A (Любо 157140): анкерираме живия разкрой към MO-тата — от
        # него четат whole-bar планът + forced-lot пиновете СЛЕД confirm (друга
        # транзакция).
        with_pieces.write({"staged_cutting_optimization_id": opt.id})
        # Forced-lot пин за СВЕЖИ цели пръти. action_optimize НЕ вика
        # generate_piece_lots (само ръчният action_generate_lots го прави — а то
        # МИНТВА offcut лотове през inventory adjustment = costing A double-value).
        # Затова тук викаме generate_piece_lots САМО за да пинне forced_lot_ids
        # (=pattern.source_id) върху raw move-овете, БЕЗ да ражда offcut лотове.
        # Offcut-ът се кредитира при Produce (проследим лот). Offcut-sourced
        # pattern-ите се пропускат тук — те имат свой Offcut→Production leg.
        if adapter is not None:
            for pattern in opt.pattern_ids.filtered(
                    lambda p: not p.source_offcut_lot_id
                    and p.source_model == "stock.lot" and p.source_id
                    and p.bar_product_id):
                try:
                    adapter.generate_piece_lots(
                        pattern, json.loads(pattern.cuts_json or "{}"))
                except Exception as pin_err:  # noqa: BLE001 — пинът не блокира
                    _logger.warning(
                        "Staged Phase 2: forced-lot пин пропуснат за pattern %s "
                        "(%s).", pattern.id, pin_err)
        _logger.info(
            "Staged Phase 2: разкрой + feasibility OK за %s (%d МО) → confirm.",
            opt.name, len(with_pieces))
        return opt

    # ── List batch action: prepare a daily set of MOs into ONE transfer ──
    # Бутон „Prepare for Production" в header-а на СПИСЪКА (след „Plan"). Цел:
    # 1 трансфер Stock→Pre-Production на ден за цеха. Подготвя всяко избрано
    # staged МО (per-MO логиката е НЕпроменена) и после АГРЕГИРА новородените
    # Pick Components пикинги в ЕДИН — подход #1 (само picking_id се мести;
    # procurement групите, веригата M→N и forced_lot_ids остават per-MO).
    # Скоупът е МАРКИРАНАТА партида (може от различни проекти), не per-SO.

    def action_prepare_production_batch(self):
        # `not p.staged_released`: MO, „prepared only" през wizard-а, остава
        # state='preparation' + staged_released=True. БЕЗ този филтър такова MO
        # се re-гейтва/re-оптимизира тук (ПРЕДИ action_prepare_production да го
        # изхвърли) → (a) собствената му вече-резервирана консумация → фалшив
        # infeasible → блокира ЦЯЛАТА партида; (b) презапис на
        # staged_cutting_optimization_id → чупи offcut credit-back anchor-а.
        # Огледало на гарда в action_prepare_production (adversarна вал. Finding 1).
        eligible = self.filtered(
            lambda p: p.staged_preparation_enabled and p.state == "preparation"
            and not p.staged_released
        )
        if not eligible:
            raise UserError(_(
                "None of the selected manufacturing orders is in 'Preparation' "
                "with staged preparation enabled."
            ))

        # Late-component WARNING (Phase 2): само лек message_post за МО с
        # неналични ПО-КЪСНИ компоненти (стъкло/обков идват на монтаж) — БЕЗ
        # блок. Твърдият BLOCK на режещите компоненти ОТПАДНА (double-gate):
        # `_staged_optimize_and_gate` е авторитетният feasibility гейт — при
        # недостиг на бар-сток вдига чист UserError + откат. Старият forecast
        # pre-check дублираше по-слабо (forecast vs реален разкрой) → махнат.
        Piece = self.env.get("mrp.cutting.piece")
        for production in eligible:
            cut_ids = set()
            if Piece is not None and production.bom_id:
                cut_ids = set(Piece.sudo().search(
                    [("bom_line_id.bom_id", "=", production.bom_id.id)]
                ).mapped("product_id").ids)
            bad = production.move_raw_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
                and m.product_id.id not in cut_ids
                and (m.forecast_availability or 0.0)
                < m.product_uom_qty - (m.product_uom.rounding or 0.01))
            if bad:
                production.message_post(body=_(
                    "⚠ Prepared while later-operation components are not yet "
                    "available (%s). They should arrive before consumption "
                    "(e.g. glass at installation).",
                    ", ".join(bad.mapped("product_id.display_name"))))

        # РАЗКРОЙ + FEASIBILITY ГЕЙТ (единственият авторитетен гейт) ПРЕДИ
        # потвърждението. cross-MO нестване на дневната партида + forced-lot пин;
        # при недостиг → чист UserError + откат (0 ангажимент). Агрегацията към
        # 1 трансфер вече е в _staged_do_prepare (recordset ниво) — не тук.
        eligible._staged_optimize_and_gate()

        # Едно потвърждение „Confirm start?" за всички; разкроят е cross-MO →
        # wizard-ът НЕ го повтаря per-MO (staged_skip_optimize).
        return eligible.with_context(
            staged_skip_optimize=True).action_prepare_production()
