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
            "True след 'Подготви за производство'. Докато е False, не-lot-tracked "
            "компонентите на staged MO се форсират make_to_stock в "
            "stock.move._adjust_procure_method → вътрешните Стока→Pre-Production "
            "picks се отлагат до floor release. Lot-tracked (стъкло/барове) не се "
            "влияят — техният PO/MTO chain тръгва на Confirm."
        ),
    )

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

            # 1) Спираме deferral-а за този MO.
            production.staged_released = True

            # 2) Гарантираме procurement група (иначе новородените picks се
            #    merge-ват с други MO-та — merge ключът включва group_id).
            if not production.procurement_group_id:
                production.procurement_group_id = self.env[
                    "procurement.group"
                ].create({
                    "name": production.name,
                    "move_type": production.move_type or "direct",
                    "partner_id": production.partner_id.id
                    if production.partner_id else False,
                })

            # 3) Re-confirm отложените raw moves → make_to_order → pull rule
            #    ражда Стока→Pre-Production picks сега (на floor release).
            deferred = production.move_raw_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
                and m.product_id.tracking == "none"
                and m.procure_method == "make_to_stock"
            )
            if deferred:
                deferred._do_unreserve()
                # state='draft' → _action_confirm третира moves като нови и
                # ПУСКА наново procurement (pull rule). Без draft reset,
                # _action_confirm на вече-confirmed move не регенерира pick.
                deferred.write({
                    "state": "draft",
                    "procure_method": "make_to_order",
                    "group_id": production.procurement_group_id.id,
                })
                deferred._action_confirm(merge=False)
                _logger.info(
                    "Staged preparation: MO %s released → %d deferred raw moves "
                    "re-confirmed (picks generated)",
                    production.name, len(deferred),
                )

            production.state = "confirmed"
            _logger.info(
                "Staged preparation: MO %s released → state=confirmed",
                production.name,
            )
        return True
