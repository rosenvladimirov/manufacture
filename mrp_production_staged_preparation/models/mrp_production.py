# Copyright 2026 BL Consulting
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    """Adds a 'preparation' gate to the MO lifecycle, expressed in native ``state``.

    State flow when ``picking_type_id.staged_preparation_enabled`` is True:

        draft
          ↓ action_confirm  (native confirm flow runs, including _action_confirm
          ↓                  on raw/finished moves)
        preparation                       ← интерфейс между планиране и
          │                                 материализация. Raw moves са MTS,
          │                                 endpoint-ите имитират 1-step:
          │                                 raw Stock→Production, finished
          │                                 Production→Stock. No Pick/Store
          │                                 pickings.
          ↓ action_prepare_production
        confirmed                         ← endpoints swap към буферните
          ↓                                 локации (pbm_loc / sam_loc),
          ↓                                 raw moves превключени на MTO и
          ↓                                 re-confirm-нати. Pick picking
          ↓                                 ражда се нативно. (3-step: Store
          ↓                                 picking се ражда автоматично на
          ↓                                 MO done от push rule sam_loc→Stock.)
        progress → to_close → done

    When ``staged_preparation_enabled`` is False, MO следва native draft →
    confirmed → progress → done flow непокътнато.
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

    # ── Helpers ─────────────────────────────────────────────────────────

    def _staged_intermediate_active(self):
        """True когато MO трябва да bypass-не буферните локации.

        Условие: staged_preparation_enabled И state='preparation'. Това е
        единственият source of truth, който controls дали _get_move_raw_values
        / _get_move_finished_values правят endpoint swap и дали
        stock.move._adjust_procure_method short-circuit-ва raw moves.
        """
        self.ensure_one()
        return bool(
            self.staged_preparation_enabled and self.state == "preparation"
        )

    def _staged_warehouse(self):
        """Връща ``stock.warehouse`` от MO source location (нативно поле).
        Empty recordset ако location_src_id не сочи към warehouse."""
        self.ensure_one()
        wh = self.location_src_id.warehouse_id
        return wh or self.env["stock.warehouse"]

    # ── Override: action_confirm ────────────────────────────────────────
    # Native action_confirm пише state='confirmed' на ред 1533 в
    # mrp/models/mrp_production.py. След като super върне, превключваме
    # state на 'preparation' за staged-enabled MO-та. Това задейства
    # _staged_intermediate_active() → bypass-нати endpoints и MTS raw moves.

    def action_confirm(self):
        result = super().action_confirm()
        for production in self:
            if (
                production.staged_preparation_enabled
                and production.state == "confirmed"
            ):
                production.state = "preparation"
        return result

    # ── Override: move endpoint construction ────────────────────────────
    # Native (Odoo 18):
    #   raw move:      location_id = self.location_src_id  (= pbm_loc when 2/3-step)
    #                  location_dest_id = property_stock_production (Production)
    #   finished move: location_id = property_stock_production (Production)
    #                  location_dest_id = self.location_dest_id (= sam_loc when 3-step)
    # При state='preparation' запазваме Production endpoint (fixed axis) и
    # заменяме отсрещната страна с warehouse.lot_stock_id (WH/Stock) —
    # bypass-ва буфера. Resulting move pair: Stock → Production → Stock,
    # no Stock↔buffer gap → pull rules не раждат Pick/Store.
    #
    # Important: action_confirm първо извиква super (което създава raw moves
    # с НАТИВНИ endpoints), после превключва state на 'preparation'.
    # Затова _get_move_raw_values НЕ вижда preparation state при initial
    # confirm — endpoint swap-ът се случва в _action_confirm на base на
    # _adjust_procure_method short-circuit override-а (стж. models/stock_move.py).
    #
    # _get_move_raw_values override остава активен за пътищата КЪМ MO в
    # preparation state, например manually добавени raw lines чрез "default_"
    # values в view-а — там state е вече 'preparation' когато user пуска MO
    # и добавя компоненти.

    def _get_move_raw_values(self, product, product_uom_qty, product_uom,
                             operation_id=False, bom_line=False):
        vals = super()._get_move_raw_values(
            product, product_uom_qty, product_uom, operation_id, bom_line,
        )
        if not self._staged_intermediate_active():
            return vals
        wh = self._staged_warehouse()
        if wh and wh.lot_stock_id:
            vals["location_id"] = wh.lot_stock_id.id
            vals["warehouse_id"] = wh.id
            # Защитна линия: ако raw move стигне до _adjust_procure_method,
            # последното ще match-не manufacture_mto_pull_id и ще го превърне
            # обратно в MTO. stock_move._adjust_procure_method override-ът
            # върши главната работа, но force-ваме MTS още при създаване.
            vals["procure_method"] = "make_to_stock"
        return vals

    def _get_move_finished_values(self, product_id, product_uom_qty, product_uom,
                                  operation_id=False, byproduct_id=False, cost_share=0):
        vals = super()._get_move_finished_values(
            product_id, product_uom_qty, product_uom,
            operation_id, byproduct_id, cost_share,
        )
        if not self._staged_intermediate_active():
            return vals
        wh = self._staged_warehouse()
        if wh and wh.lot_stock_id:
            vals["location_dest_id"] = wh.lot_stock_id.id
            vals["warehouse_id"] = wh.id
        return vals

    # ── Action: prepare for production (preparation → confirmed) ────────

    def action_prepare_production(self):
        """Transition state from 'preparation' to 'confirmed': swap endpoints
        back to warehouse buffers per ``manufacture_steps``, re-trigger
        procurement so pull rules generate Pick/Store pickings natively.

        Guards:
        - Само за MO с state='preparation' и staged_preparation_enabled.
        - mrp_one_step warehouse → no-op логистично, само state става confirmed.
        """
        for production in self:
            production._action_prepare_production_one()
        return True

    def _action_prepare_production_one(self):
        self.ensure_one()
        if not self.staged_preparation_enabled:
            raise UserError(_(
                "Staged preparation is not enabled for this picking type. "
                "Enable 'Staged Preparation' on '%s' first.",
                self.picking_type_id.display_name,
            ))
        if self.state != "preparation":
            raise UserError(_(
                "MO %(name)s is in state '%(state)s'; only MOs in "
                "'Preparation' can be prepared for production.",
                name=self.name, state=self.state,
            ))

        wh = self._staged_warehouse()
        if not wh:
            # Не би трябвало да се случи в healthy data; fail-safe — просто
            # премини в confirmed без endpoint swap.
            _logger.warning(
                "MO %s has no warehouse on location_src_id; moving to "
                "'confirmed' without endpoint swap.", self.name,
            )
            self.state = "confirmed"
            return

        # Determine target endpoint locations per warehouse step config.
        # mrp_one_step: nothing to do logistically — pull rules стартират на
        # confirm, no buffer gap.
        target_raw_src = None       # only set when warehouse е 2/3-step
        target_finished_dest = None  # only set when warehouse е 3-step
        steps = wh.manufacture_steps
        if steps == "pbm":
            target_raw_src = wh.pbm_loc_id
        elif steps == "pbm_sam":
            target_raw_src = wh.pbm_loc_id
            target_finished_dest = wh.sam_loc_id

        # Ensure procurement_group_id за MO-то, иначе новородените Pick/Store
        # се merge-ват с други MO-та (merge ключът включва group_id).
        if not self.procurement_group_id:
            self.procurement_group_id = self.env["procurement.group"].create({
                "name": self.name,
                "move_type": self.move_type or "direct",
                "partner_id": self.partner_id.id if self.partner_id else False,
            })

        raw_to_reconfirm = self.env["stock.move"]
        finished_to_reconfirm = self.env["stock.move"]

        # ── Swap raw move sources (only when target_raw_src е set) ──────
        if target_raw_src:
            raw_moves = self.move_raw_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
            )
            for move in raw_moves:
                if move.location_id == target_raw_src:
                    continue
                if move.state == "assigned":
                    move._do_unreserve()
                move.write({
                    "location_id": target_raw_src.id,
                    "group_id": self.procurement_group_id.id,
                })
                raw_to_reconfirm |= move

        # ── Swap finished move dest (only when target_finished_dest е set) ──
        if target_finished_dest:
            finished_moves = self.move_finished_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
            )
            for move in finished_moves:
                if move.location_dest_id == target_finished_dest:
                    continue
                if move.state == "assigned":
                    move._do_unreserve()
                move.write({
                    "location_dest_id": target_finished_dest.id,
                    "group_id": self.procurement_group_id.id,
                })
                finished_to_reconfirm |= move

        # ── State flip ПРЕДИ re-confirm ─────────────────────────────────
        # stock.move._adjust_procure_method short-circuit-ва за raw moves
        # докато MO е в preparation. След тоя ред MO вече не е в preparation
        # → _adjust_procure_method ще работи нативно, ще намери pbm pull rule
        # (Stock→pbm_loc) и ще set-не procure_method='make_to_order' → MTO
        # chain се задейства → Pick picking се ражда нативно.
        self.state = "confirmed"

        # ── Reset procure_method на raw moves към MTO ──────────────────
        # _get_move_raw_values вкара 'make_to_stock' при preparation. За да
        # се задейства MTO chain трябва изрично да се върне към 'make_to_order'
        # преди re-confirm.
        if raw_to_reconfirm:
            raw_to_reconfirm.write({"procure_method": "make_to_order"})

        # ── Re-trigger pull rules чрез _action_confirm ──────────────────
        # merge=False — не искаме новородените Pick/Store да се merge-нат с
        # други MO's pickings (procurement_group_id вече осигурява separation,
        # но изричен merge=False е допълнителна гаранция).
        moves_to_reconfirm = raw_to_reconfirm | finished_to_reconfirm
        if moves_to_reconfirm:
            moves_to_reconfirm._action_confirm(merge=False)
            _logger.info(
                "Staged preparation: MO %s → %d moves re-confirmed (steps=%s)",
                self.name, len(moves_to_reconfirm), steps,
            )
