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

    # TG 173288: предупрежденията от фоновата задача — над „Да/Не“.
    prep_warnings = fields.Text(
        string="Warnings", compute="_compute_prep_warnings")

    @api.depends("production_ids.staged_prep_warnings")
    def _compute_prep_warnings(self):
        for wiz in self:
            seen = []
            for text in wiz.production_ids.mapped("staged_prep_warnings"):
                for line in (text or "").splitlines():
                    if line and line not in seen:
                        seen.append(line)
            wiz.prep_warnings = "\n".join(seen) or False

    @api.depends("production_ids.staged_cutting_optimization_id")
    def _compute_cutting_optimization_id(self):
        # Партидата е ЕДИН разкрой (cross-MO). Смесени разкрои не се показват
        # наслуки — тогава полето е празно и резюмето не се вижда.
        for wiz in self:
            opts = wiz.production_ids.mapped("staged_cutting_optimization_id")
            wiz.cutting_optimization_id = opts if len(opts) == 1 else False

    def action_view_cutting(self):
        """„Виж разкроя“ — справката с прътите в НОВ раздел (Любо 21.10).

        Прозорецът за одобрение остава отворен — дотук разкроят го заместваше
        и нямаше връщане към потвърждението (TG 173278).
        """
        self.ensure_one()
        opt = self.cutting_optimization_id
        if hasattr(opt, "_cut_layout_url_action"):
            return opt._cut_layout_url_action()
        return {
            "type": "ir.actions.act_window",
            "name": _("Cutting Run"),
            "res_model": "mrp.cutting.optimization",
            "res_id": opt.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_approve_cutting(self):
        """„Да“ — задача Б: резервиране, Pre-Production, старт на позициите."""
        self.production_ids._staged_release_enqueue(start=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "info",
                "title": _("Cutting approved"),
                "message": _("Preparing in the background: %s. You will be "
                             "notified when it is ready.",
                             ", ".join(self.production_ids.mapped("name"))),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_reject_cutting(self):
        """„Не“ — разкроят се маха, нищо не остава."""
        self.production_ids._staged_reject_cutting()
        return {"type": "ir.actions.act_window_close"}
