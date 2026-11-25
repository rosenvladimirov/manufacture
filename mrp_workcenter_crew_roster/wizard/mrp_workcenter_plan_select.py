# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from odoo import api, fields, models


class MrpWorkcenterPlanSelect(models.TransientModel):
    """„Планирай център“: планиращият първо избира центровете (Р12, Р40).

    След избора: Гантът „Планирай център“ или нарядът на центровете. Менюто
    „Crew Roster“ отваря същия избор с ключа `crew_plan_target='roster'` в
    контекста — тогава основният бутон е нарядът (№5).

    Р40 (Росен 09.10): изборът е много към много; избран център довлича
    алтернативите си (`alternative_workcenter_ids`), за да се виждат всички
    наведнъж. Махната алтернатива не се връща сама — довличат се само
    алтернативите на НОВО добавените центрове (`crew_expanded_ids` помни
    вече разгънатите).
    """

    _name = "mrp.workcenter.plan.select"
    _description = "Select Work Center to Plan"

    workcenter_ids = fields.Many2many(
        "mrp.workcenter",
        "mrp_workcenter_plan_select_workcenter_rel",
        "wizard_id",
        "workcenter_id",
        string="Work Centers",
        required=True,
        domain="[('company_id', 'in', allowed_company_ids)]",
        help="The work centers to plan. A selected work center adds its "
        "alternative work centers, so that all of them are shown at once.",
    )
    crew_expanded_ids = fields.Many2many(
        "mrp.workcenter",
        "mrp_workcenter_plan_select_expanded_rel",
        "wizard_id",
        "workcenter_id",
        string="Expanded Work Centers",
    )

    @api.onchange("workcenter_ids")
    def _onchange_workcenter_ids_alternatives(self):
        """Р40: новите центрове довличат алтернативите си (едно ниво;
        алтернатива от друга фирма Odoo не допуска); вече разгънатите не
        се разгъват пак."""
        for wizard in self:
            new = wizard.workcenter_ids - wizard.crew_expanded_ids
            if not new:
                continue
            added = new.alternative_workcenter_ids - wizard.workcenter_ids
            wizard.workcenter_ids |= added
            wizard.crew_expanded_ids |= new | added

    def _crew_names(self):
        return ", ".join(self.workcenter_ids.mapped("display_name"))

    def action_open_roster(self):
        """Нарядът на избраните центрове. С един център — контекстът
        `crew_workcenter_id` (центърът на нов наряд, бутоните в хедъра); с
        няколко — само домейнът, центърът на новия наряд се избира.

        Без `default_*` в контекста (Ф3): префиксът изтича към всяко create
        на модел с поле `workcenter_id`.
        """
        self.ensure_one()
        workcenters = self.workcenter_ids
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "mrp_workcenter_crew_roster.mrp_workcenter_roster_action"
        )
        if len(workcenters) == 1:
            action["domain"] = [("workcenter_id", "=", workcenters.id)]
            action["context"] = {"crew_workcenter_id": workcenters.id}
        else:
            action["domain"] = [("workcenter_id", "in", workcenters.ids)]
            action["context"] = {}
        action["name"] = self.env._("Crew Roster: %(wc)s", wc=self._crew_names())
        action["target"] = "current"
        return action

    def action_open_gantt(self):
        """Гантът „Планирай център“ (TECH_DESIGN §4). Един център — както
        smart бутона „Plan“; няколко (Р40) — всички наведнъж: домейн по
        центровете, `crew_workcenter_ids` за „Rearrange Plan“ и без
        `crew_workcenter_id` („Recompute“ е за един център)."""
        self.ensure_one()
        workcenters = self.workcenter_ids
        if len(workcenters) == 1:
            return workcenters.action_crew_plan_gantt()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_action"
        )
        action["domain"] = [
            ("workcenter_id", "in", workcenters.ids),
            *self.env["mrp.workcenter"]._crew_short_term_domain(),
        ]
        action["context"] = {"crew_workcenter_ids": workcenters.ids}
        action["name"] = self.env._("Plan: %(wc)s", wc=self._crew_names())
        action["target"] = "current"
        return action
