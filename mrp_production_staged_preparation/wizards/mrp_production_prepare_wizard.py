# -*- coding: utf-8 -*-
# Потвърждение при стейджинг: планерът решава дали да СТАРТИРА производството
# сега (In Processing) или само да го подготви (остава Preparation). #10.
from odoo import fields, models


class MrpProductionPrepareWizard(models.TransientModel):
    _name = "mrp.production.prepare.wizard"
    _description = "Confirm start of staged production"

    production_ids = fields.Many2many(
        comodel_name="mrp.production", string="Manufacturing Orders")

    def _do(self, start):
        # Пренасяме staged_skip_optimize (batch вече е оптимизирал cross-MO).
        skip = self.env.context.get("staged_skip_optimize", False)
        self.production_ids.with_context(
            staged_skip_optimize=skip)._staged_do_prepare(start=start)
        return {"type": "ir.actions.act_window_close"}

    def action_prepare_and_start(self):
        # YES → стейджинг + In Processing (progress) + заключено.
        return self._do(True)

    def action_prepare_only(self):
        # NO → стейджинг, но остава в Preparation (стартира се по-късно).
        return self._do(False)
