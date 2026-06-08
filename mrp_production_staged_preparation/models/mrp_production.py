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

            # 1) Маркираме released → _staged_intermediate_active() става False.
            production.staged_released = True

            wh = production._staged_warehouse()

            # 2) Procurement група (иначе новородените picks се merge-ват с
            #    други MO-та — merge ключът включва group_id).
            if not production.procurement_group_id:
                production.procurement_group_id = self.env[
                    "procurement.group"
                ].create({
                    "name": production.name,
                    "move_type": production.move_type or "direct",
                    "partner_id": production.partner_id.id
                    if production.partner_id else False,
                })

            # 3) Цел-локации според warehouse steps. mrp_one_step → no-op
            #    (нямаше буфер swap). pbm/pbm_sam → raw към pbm_loc; pbm_sam →
            #    finished към sam_loc.
            target_raw_src = False
            target_finished_dest = False
            if wh.manufacture_steps in ("pbm", "pbm_sam"):
                target_raw_src = wh.pbm_loc_id
            if wh.manufacture_steps == "pbm_sam":
                target_finished_dest = wh.sam_loc_id

            raw_to_reconfirm = self.env["stock.move"]
            # 4) Не-стъклените raw moves: swap Stock → pbm_loc + make_to_order
            #    + re-confirm → pull rule ражда Стока→Pre-Production pick
            #    (вторият пикинг). Стъклените са вече на pbm — не ги пипаме.
            if target_raw_src:
                for move in production.move_raw_ids.filtered(
                        lambda m: m.state not in ("done", "cancel")):
                    if self._staged_is_glass(move.product_id):
                        continue
                    if move.location_id == target_raw_src:
                        continue
                    if move.state == "assigned":
                        move._do_unreserve()
                    move.write({
                        "state": "draft",
                        "location_id": target_raw_src.id,
                        "procure_method": "make_to_order",
                        "group_id": production.procurement_group_id.id,
                    })
                    raw_to_reconfirm |= move

            finished_to_reconfirm = self.env["stock.move"]
            if target_finished_dest:
                for move in production.move_finished_ids.filtered(
                        lambda m: m.state not in ("done", "cancel")):
                    if move.location_dest_id == target_finished_dest:
                        continue
                    if move.state == "assigned":
                        move._do_unreserve()
                    move.write({
                        "location_dest_id": target_finished_dest.id,
                        "group_id": production.procurement_group_id.id,
                    })
                    finished_to_reconfirm |= move

            production.state = "confirmed"

            moves = raw_to_reconfirm | finished_to_reconfirm
            if moves:
                moves._action_confirm(merge=False)
                _logger.info(
                    "Staged preparation: MO %s released → %d moves swapped back "
                    "to buffer + re-confirmed (second picking generated)",
                    production.name, len(moves),
                )
            else:
                _logger.info(
                    "Staged preparation: MO %s released (1-step, no buffer swap)",
                    production.name,
                )
        return True
