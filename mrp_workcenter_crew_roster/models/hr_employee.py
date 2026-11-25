# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from odoo import fields, models


class HrEmployee(models.Model):
    """Нарядите на служителя — от картата му (№146 на Теолино, ADR-0071)."""

    _inherit = "hr.employee"

    crew_roster_count = fields.Integer(
        compute="_compute_crew_roster_count",
        string="Crew Rosters",
        groups="mrp.group_mrp_user",
    )

    def _compute_crew_roster_count(self):
        Roster = self.env["mrp.workcenter.roster"]
        for employee in self:
            employee.crew_roster_count = Roster.search_count(
                [("employee_ids", "in", employee.id)]
            )

    def action_crew_rosters(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "mrp_workcenter_crew_roster.mrp_workcenter_roster_action"
        )
        action["domain"] = [("employee_ids", "in", self.id)]
        action["context"] = {}
        return action
