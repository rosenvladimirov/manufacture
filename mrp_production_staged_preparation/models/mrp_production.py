# Copyright 2026 Rosen Vladimirov
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

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
        result = super().button_plan()
        for production in self:
            if (
                production.staged_preparation_enabled
                and production.state == "confirmed"
            ):
                production.state = "preparation"
        return result

    # ── Action: prepare for production (preparation → confirmed) ────────
    # Release-to-floor button. Сетва staged_released=True (спира deferral-а в
    # stock.move._adjust_procure_method), после re-confirm-ва отложените
    # (non-lot-tracked) raw moves → pull rule ражда вътрешните Стока→
    # Pre-Production picks ЕДВА сега. Lot-tracked moves вече са materialized
    # на Confirm и не се пипат. Накрая flip към 'confirmed' → unlock progress.

    def action_prepare_production(self):
        for production in self:
            if not production.staged_preparation_enabled:
                raise UserError(_(
                    "Staged preparation is not enabled for this picking type. "
                    "Enable 'Staged Preparation' on '%s' first.",
                    production.picking_type_id.display_name,
                ))
            if production.state != "preparation":
                raise UserError(_(
                    "MO %(name)s is in state '%(state)s'; only MOs in "
                    "'Preparation' can be released to production.",
                    name=production.name, state=production.state,
                ))

            # 1) Маркираме released.
            production.staged_released = True

            wh = production._staged_warehouse()
            pbm = wh.pbm_loc_id
            prod_loc = production.production_location_id

            # mrp_one_step или липсва Pre-Production → нищо за местене (no-op).
            if wh.manufacture_steps not in ("pbm", "pbm_sam") or not pbm:
                production.state = "confirmed"
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

            production.state = "confirmed"
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
        return True

    # ── List batch action: prepare a daily set of MOs into ONE transfer ──
    # Бутон „Prepare for Production" в header-а на СПИСЪКА (след „Plan"). Цел:
    # 1 трансфер Stock→Pre-Production на ден за цеха. Подготвя всяко избрано
    # staged МО (per-MO логиката е НЕпроменена) и после АГРЕГИРА новородените
    # Pick Components пикинги в ЕДИН — подход #1 (само picking_id се мести;
    # procurement групите, веригата M→N и forced_lot_ids остават per-MO).
    # Скоупът е МАРКИРАНАТА партида (може от различни проекти), не per-SO.

    def action_prepare_production_batch(self):
        eligible = self.filtered(
            lambda p: p.staged_preparation_enabled and p.state == "preparation"
        )
        if not eligible:
            raise UserError(_(
                "None of the selected manufacturing orders is in 'Preparation' "
                "with staged preparation enabled."
            ))

        # 0) PRE-CHECK наличност (искане на Любо): ПРЕДУПРЕЖДЕНИЕ, НЕ блок, ако
        #    някое МО няма всичките компоненти Available. Не блокираме, защото
        #    стъклото се потребява чак на монтажа (дни по-късно) → има още време
        #    за доставка. Само информираме (chatter сега + sticky notification
        #    накрая), за да не се изненада операторът. Разкроят/пиковете
        #    продължават нормално за всички избрани МО.
        not_ready = eligible.filtered(
            lambda p: p.components_availability_state
            and p.components_availability_state != 'available')
        for production in not_ready:
            _logger.warning(
                "Staged preparation: МО %s подготвено с НЕналични компоненти (%s)",
                production.name, production.components_availability)
            production.message_post(body=_(
                "⚠ Prepared for production while components are not yet available "
                "(%s). Make sure they arrive before consumption.",
                production.components_availability or _("Not Available")))

        # 1) РАЗКРОЙ ПЪРВО (при Preparation, ПРЕДИ пиковете).  Оптимизацията
        #    коригира КОЕФИЦИЕНТА (bom_line.loss) и преоразмерява bar move-овете
        #    (product_uom_qty = полезни × (1+loss)) → пиковете в стъпка 2 се
        #    генерират за КОРЕКТНОТО количество.  cross-MO нестване на цялата
        #    дневна партида + forced_lot пиниране.  GUARDED: само ако
        #    mrp_cutting_optimization + MRP plugin-ът са инсталирани; неуспех
        #    (напр. барове още не получени) НЕ блокира подготовката — пуска се
        #    ръчно по-късно (бутон „Optimize Cutting“ на МО).
        Opt = self.env.get("mrp.cutting.optimization")
        adapter = self.env.get("cutting.source.adapter.mrp_production")
        if Opt is not None and adapter is not None:
            try:
                opt = Opt.create({
                    "name": _("Daily cut: %s") % ", ".join(
                        eligible.mapped("name"))[:60],
                    "material_domain": "mrp_production",
                    "production_ids": [(6, 0, eligible.ids)],
                })
                opt.action_optimize()
                _logger.info(
                    "Staged preparation batch: cross-MO разкрой %s за %d МО-та "
                    "(loss коригиран ПРЕДИ пиковете)", opt.name, len(eligible))
            except Exception as exc:  # noqa: BLE001 — разкроят не бива да блокира
                _logger.warning(
                    "Staged preparation batch: разкроят пропуснат (%s) — "
                    "вероятно барове още не са в наличност; пусни ръчно "
                    "(бутон „Optimize Cutting“ на МО) щом пристигнат.", exc)

        # 2) Подготвяме всяко избрано МО (per-MO release).  Пиковете вече се
        #    размерват от коригираните (от разкроя) количества.
        eligible.action_prepare_production()

        # 3) Събираме новородените Stock→Pre-Production пикинги на партидата.
        #    Бридж парон (N): Pre-Production→Production в move_raw_ids; неговият
        #    move_orig (M) е първият пик Stock→Pre-Production → неговият picking.
        pc_pickings = self.env["stock.picking"]
        for production in eligible:
            pbm = production._staged_warehouse().pbm_loc_id
            if not pbm:
                continue
            bridges = production.move_raw_ids.filtered(
                lambda m: m.location_id == pbm
                and m.state not in ("done", "cancel")
            )
            first_picks = bridges.move_orig_ids.filtered(
                lambda m: m.location_dest_id == pbm
                and m.picking_id
                and m.picking_id.state not in ("done", "cancel")
            )
            pc_pickings |= first_picks.picking_id

        # 4) Агрегация: всички PC пикинги на партидата → ЕДИН трансфер.
        if len(pc_pickings) > 1:
            target = pc_pickings.sorted("id")[0]
            others = pc_pickings - target
            others.move_ids.write({"picking_id": target.id})
            origins = sorted({o for o in pc_pickings.mapped("origin") if o})
            if origins:
                target.origin = ", ".join(origins)[:2000]
            others.filtered(lambda p: not p.move_ids).unlink()
            target.action_assign()  # резервира слетите редове (stock.picking API)
            _logger.info(
                "Staged preparation batch: %d МО → 1 агрегиран PC трансфер %s "
                "(%d пикинга слети в дневна партида)",
                len(eligible), target.name, len(pc_pickings),
            )
        # Не-блокиращо предупреждение за МО с неналични компоненти (виж стъпка 0).
        if not_ready:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _("Prepared — some components not yet available"),
                    'message': _(
                        "Optimization and transfers were created. These MOs have "
                        "components not yet in stock (e.g. glass arriving before "
                        "installation):\n%s",
                        "\n".join(
                            "• %s — %s" % (
                                p.name, p.components_availability or _("Not Available"))
                            for p in not_ready)),
                    'sticky': True,
                },
            }
        return True
