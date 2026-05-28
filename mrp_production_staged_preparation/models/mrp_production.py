# Copyright 2026 BL Consulting
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

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

    **Семантика спрямо предходна версия (v18.0.1.x):** preparation се местеше
    между confirm и progress, и override-ваше endpoint-ите на raw/finished
    moves към WH/Stock + force-ваше make_to_stock, за да suppress-не
    Pick/Store pickings до Prepare button. Това чупеше MTO chain за glass и
    други lot-tracked продукти, защото PO се раждаше едва на Prepare.
    Сегашната версия (v18.0.2.0.0) измества preparation **след** Plan; MTO
    chain работи нативно на confirm; preparation е чист visual gate без
    endpoint manipulation.
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
    # Release-to-floor button. Не пипа move endpoints или procure_method —
    # тези са вече materialized от Plan/Confirm стъпките. Прави само state
    # flip обратно към 'confirmed', което unlock-ва native progress flow.

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
            production.state = "confirmed"
            _logger.info(
                "Staged preparation: MO %s released → state=confirmed",
                production.name,
            )
        return True
