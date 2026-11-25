# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Ръчното генериране на смените (Росен 14.10.2026: само ръчно). Първо
„Преглед“ — броячите без запис, после „Генерирай“."""
from odoo import fields, models


class PlanningCrewRotationGenerate(models.TransientModel):
    _name = "planning.crew.rotation.generate"
    _description = "Generate Crew Shifts"

    rotation_id = fields.Many2one("planning.crew.rotation", required=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    previewed = fields.Boolean(readonly=True)
    count_created = fields.Integer("To Create", readonly=True)
    count_updated = fields.Integer("To Update", readonly=True)
    count_deleted = fields.Integer("To Delete", readonly=True)
    count_kept = fields.Integer("Unchanged", readonly=True)
    count_conflicts = fields.Integer(
        "Conflicts", readonly=True,
        help="Published shifts or shifts changed by hand that differ from the "
             "rotation; they are left as they are.")
    count_open = fields.Integer(
        "Open Shifts", readonly=True,
        help="Shifts of employees on leave without a free substitute.")
    count_substituted = fields.Integer("By Substitutes", readonly=True)
    count_warnings = fields.Integer(
        "Labour Code Warnings", readonly=True,
        help="Shifts that break a rule of the Labour Code for the employee (rest, weekly "
             "hours, night work); they are created with a warning.")

    def _write_counts(self, counts):
        self.write({"previewed": True, **{"count_%s" % k: v for k, v in counts.items()}})

    def action_preview(self):
        self.ensure_one()
        self._write_counts(self.rotation_id._crew_generate(
            self.date_from, self.date_to, dry_run=True))
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_generate(self):
        self.ensure_one()
        counts = self.rotation_id._crew_generate(self.date_from, self.date_to)
        self.rotation_id.message_post(body=self.env._(
            "Shifts from %(date_from)s to %(date_to)s: %(created)s created, "
            "%(updated)s updated, %(deleted)s deleted, %(conflicts)s conflicts, "
            "%(open)s open.",
            date_from=self.date_from, date_to=self.date_to, **counts))
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Crew Shifts"),
            "res_model": "planning.slot",
            "view_mode": "list,form",
            "domain": [("crew_rotation_id", "=", self.rotation_id.id),
                       ("crew_date", ">=", self.date_from),
                       ("crew_date", "<=", self.date_to)],
        }
