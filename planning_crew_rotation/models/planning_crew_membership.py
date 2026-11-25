# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Кой служител в коя бригада е и от кога (Росен 14.10.2026: „както е в
договора“). Назначението стои в договора (`hr.contract` — в 18 няма версии на
договора; Росен 07.11.2026: „върху договора“); периодът е отделен, защото човек
може да мине в друга бригада, без да се сменя договорът."""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PlanningCrewMembership(models.Model):
    _name = "planning.crew.membership"
    _description = "Crew Membership"
    _order = "date_from desc, id desc"

    contract_id = fields.Many2one(
        "hr.contract", string="Contract", required=True,
        ondelete="cascade", index=True)
    employee_id = fields.Many2one(
        "hr.employee", related="contract_id.employee_id", store=True, index=True)
    crew_id = fields.Many2one("planning.crew", required=True, ondelete="restrict")
    rotation_id = fields.Many2one(
        "planning.crew.rotation", related="crew_id.rotation_id", store=True, index=True)
    company_id = fields.Many2one(related="crew_id.company_id", store=True)
    date_from = fields.Date(string="From", required=True)
    date_to = fields.Date(string="To", help="Empty means until further notice.")

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for membership in self:
            if membership.date_to and membership.date_to < membership.date_from:
                raise ValidationError(self.env._(
                    "The end of the crew membership is before its start."))

    @api.constrains("employee_id", "crew_id", "date_from", "date_to")
    def _check_overlap(self):
        """В една ротация служителят е в най-много една бригада на ден."""
        for membership in self:
            others = self.search([
                ("id", "!=", membership.id),
                ("employee_id", "=", membership.employee_id.id),
                ("rotation_id", "=", membership.rotation_id.id),
            ])
            for other in others:
                if (not other.date_to or other.date_to >= membership.date_from) and (
                        not membership.date_to or membership.date_to >= other.date_from):
                    raise ValidationError(self.env._(
                        "%(employee)s is already in crew %(crew)s from %(date)s.",
                        employee=membership.employee_id.name,
                        crew=other.crew_id.display_name, date=other.date_from))
