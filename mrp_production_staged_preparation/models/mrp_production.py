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

    @staticmethod
    def _staged_is_glass(product):
        """Стъклото (категория съдържа 'Glass') се поръчва на Confirm (нативно
        MTO); всичко друго е ЗАМРАЗЕНО до 'Подготви за производство'."""
        return "Glass" in (product.categ_id.complete_name or "")

    # ── Замразяване (без endpoint-swap) ─────────────────────────────────
    # Не-стъклените raw moves ОСТАВАТ в Pre-Production (pbm_loc) и се форсират
    # make_to_stock в stock.move._adjust_procure_method → НЕ се ражда pick,
    # търсенето остава в pbm_loc → ордерпоинтът (на WH/Stock) е сляп →
    # 0 поръчки на Confirm. Стъклото минава нативно (make_to_order) → glass PO
    # + pick на Confirm. На 'Подготви' не-стъклените се re-confirm-ват като
    # СТАНДАРТНО поведение (нативен pbm pick + ордерпоинт) — виж
    # action_prepare_production.

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

            # 1) Release → _staged_intermediate_active() става False (размразява).
            production.staged_released = True

            # 2) Procurement група (новородените picks да не merge-ват с други MO).
            if not production.procurement_group_id:
                production.procurement_group_id = self.env[
                    "procurement.group"
                ].create({
                    "name": production.name,
                    "move_type": production.move_type or "direct",
                    "partner_id": production.partner_id.id
                    if production.partner_id else False,
                })

            production.state = "confirmed"

            # 3) Размразяваме не-стъклените raw moves → АБСОЛЮТНО СТАНДАРТЕН
            #    ОРДЕРПОИНТ модел (НЕ MTO): swap location → WH/Stock + force
            #    make_to_stock (1-step Stock→Production) + re-confirm. Така:
            #    консумират от Stock, търсенето става ВИДИМО на WH/Stock →
            #    ордерпоинтът поръчва ТОГАВА (по форкаст), точно като стандартно
            #    едностепенно. БЕЗ make_to_order → няма MTO „заобикаляне" на
            #    ордерпоинта. Стъклото е пропуснато (то си направи MTO на Confirm).
            #    draft reset е нужен, иначе re-confirm на вече-confirmed move не
            #    регенерира procurement/reservation.
            wh = (production.picking_type_id.warehouse_id
                  or production.location_src_id.warehouse_id)
            frozen = production.move_raw_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
                and not self._staged_is_glass(m.product_id)
                and m.procure_method == "make_to_stock"
            )
            if frozen and wh and wh.lot_stock_id:
                frozen._do_unreserve()
                frozen.write({
                    "state": "draft",
                    "location_id": wh.lot_stock_id.id,
                    "procure_method": "make_to_stock",
                    "group_id": production.procurement_group_id.id,
                })
                frozen._action_confirm(merge=False)
                _logger.info(
                    "Staged preparation: MO %s released → %d non-glass moves to "
                    "standard 1-step/orderpoint (Stock, make_to_stock)",
                    production.name, len(frozen),
                )
        return True
