# -*- coding: utf-8 -*-
# Потвърждение при стейджинг: планерът решава дали да СТАРТИРА производството
# сега (In Processing) или само да го подготви (остава Preparation). #10.
from odoo import _, api, fields, models


class MrpProductionPrepareWizard(models.TransientModel):
    _name = "mrp.production.prepare.wizard"
    _description = "Confirm start of staged production"

    production_ids = fields.Many2many(
        comodel_name="mrp.production", string="Manufacturing Orders")
    # №116 (Любо, 01.10; искано още на 16.07, TG 2128): прозорецът за старт
    # показва разкроя — дотук планерът пускаше на сляпо. Разкроят е вече
    # записан тук: гейтът е минал, преди прозорецът да се отвори.
    cutting_optimization_id = fields.Many2one(
        comodel_name="mrp.cutting.optimization", string="Cutting Run",
        compute="_compute_cutting_optimization_id")
    cutting_bars = fields.Integer(
        string="Bars", related="cutting_optimization_id.total_bars_used")
    cutting_waste_pct = fields.Float(
        string="Waste %", related="cutting_optimization_id.waste_percentage")
    cutting_pattern_count = fields.Integer(
        string="Cutting Patterns",
        related="cutting_optimization_id.pattern_count")

    @api.depends("production_ids.staged_cutting_optimization_id")
    def _compute_cutting_optimization_id(self):
        # Партидата е ЕДИН разкрой (cross-MO). Смесени разкрои не се показват
        # наслуки — тогава полето е празно и резюмето не се вижда.
        for wiz in self:
            opts = wiz.production_ids.mapped("staged_cutting_optimization_id")
            wiz.cutting_optimization_id = opts if len(opts) == 1 else False

    def action_view_cutting(self):
        """„Виж разкроя“ — отваря разкроя над прозореца, без да го затваря."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Cutting Run"),
            "res_model": "mrp.cutting.optimization",
            "res_id": self.cutting_optimization_id.id,
            "view_mode": "form",
            "target": "new",
        }

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
