# Copyright 2026 Rosen Vladimirov
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

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

    **История:** v18.0.1.x правеше full-suppress (всичко след Prepare) →
    чупеше glass MTO. v18.0.2.0.0 махна suppress-а изцяло (всичко на Confirm) →
    floor получаваше трансфери преди подготовка. v18.0.2.2.0 = хибридът между
    двете.
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

            bridges = self.env["stock.move"]
            for M in candidates:
                if M.state == "assigned":
                    M._do_unreserve()
                # ② НОВ парон (консумация): Pre-Production → Virtual-Production.
                #    move_orig = M → чака първия пикинг (без нов pull).
                N = M.copy({
                    "location_id": pbm.id,
                    "location_dest_id": prod_loc.id,
                    "procure_method": "make_to_order",
                    "raw_material_production_id": production.id,
                    "group_id": pg.id,
                    "picking_id": False,
                    "picking_type_id": production.picking_type_id.id,
                    "move_orig_ids": False,
                    "move_dest_ids": False,
                    "state": "draft",
                })
                # ① съществуващият move → ПЪРВИ ПИКИНГ: Stock → Pre-Production.
                #    Десният край се отлепя от Virtual-Prod; Stock-краят (и
                #    procurement-ът от Confirm) ОСТАВА. Вече не е raw консумация.
                M.write({
                    "location_dest_id": pbm.id,
                    "raw_material_production_id": False,
                    "group_id": pg.id,
                    "picking_type_id": pbm_type.id if pbm_type
                    else M.picking_type_id.id,
                    "move_dest_ids": [(6, 0, [N.id])],
                })
                bridges |= N

            production.state = "confirmed"
            if bridges:
                first_picks = bridges.move_orig_ids  # бившите M (Stock→Pre-Prod)
                bridges._action_confirm(merge=False)        # ② мостовете (waiting)
                # ① пиковете → assign към Pick Components picking (за да се
                #    ПОКАЖАТ като трансфер за оператора) + резервация от Stock.
                first_picks.write({"state": "confirmed"})
                first_picks._assign_picking()
                first_picks._action_assign()                # резервират от Stock
                _logger.info(
                    "Staged preparation: MO %s released → %d component(s): десен "
                    "край откачен Stock→Pre-Production (① пикинг) + нов парон "
                    "Pre-Production→Production (② консумация)",
                    production.name, len(bridges))
        return True
