# -*- coding: utf-8 -*-
# Откат на стейджинга: планерът решава ДОКЪДЕ да се върне поръчката —
# само до Confirmed (стейджингът пада, поръчката си остава потвърдена) или
# чак до Draft (пълно отваряне, за да се пипне рецептата). Искане на Росен,
# 19.08 — дотук откатът винаги връщаше в Draft, което е по-грубо от нужното.
from odoo import _, fields, models


class MrpProductionUnprepareWizard(models.TransientModel):
    _name = "mrp.production.unprepare.wizard"
    _description = "Undo staged preparation"

    production_ids = fields.Many2many(
        comodel_name="mrp.production", string="Manufacturing Orders")
    production_count = fields.Integer(
        string="Orders", compute="_compute_summary")
    picking_count = fields.Integer(
        string="Transfers to delete", compute="_compute_summary")

    def _compute_summary(self):
        """Показваме на човека КОЛКО поръчки и КОЛКО трансфера ще бъдат
        засегнати — откатът трие пикинги, а това не се вижда от бутона."""
        for wizard in self:
            productions = wizard.production_ids
            wizard.production_count = len(productions)
            # №93: същото правило като самия откат — по старата верига
            # (`move_orig_ids`) броят беше винаги 0 след ④ (10.09).
            wizard.picking_count = len(productions._staged_prep_pickings())

    def _do(self, target_state):
        self.ensure_one()
        self.production_ids.action_unprepare_production(
            target_state=target_state)
        return {"type": "ir.actions.act_window_close"}

    def action_back_to_confirmed(self):
        # Стейджингът пада, поръчката остава потвърдена — за пренареждане
        # на подготовката без да се разглобява поръчката.
        return self._do("confirmed")

    def action_back_to_draft(self):
        # Пълно отваряне — когато трябва да се пипне рецептата или редовете.
        return self._do("draft")
