# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Нарядът по център от смяната на бригадата (Росен 14.10.2026).

Нарядът на (център, ден, смяна) = всички, които имат смяна от ротацията в
този ден по този шаблон: бригадата на смяна, със заместниците при отпуск и
без хората в отпуск. Ръчно поправен наряд не се пипа.
"""
from collections import defaultdict

from odoo import Command, fields, models

from odoo.addons.mrp_workcenter_crew_roster.models.mrp_workcenter import crew_hours_to_key


class PlanningCrewRotation(models.Model):
    _inherit = "planning.crew.rotation"

    workcenter_ids = fields.One2many(
        "mrp.workcenter", "crew_rotation_id", string="Work Centers",
        help="Work centers that work the shifts of this rotation.")

    def write(self, vals):
        res = super().write(vals)
        if "calendar_id" in vals:
            for rotation in self.filtered("calendar_id"):
                rotation.workcenter_ids.resource_calendar_id = rotation.calendar_id
        return res

    def _crew_generate(self, date_from, date_to, dry_run=False):
        counts = super()._crew_generate(date_from, date_to, dry_run=dry_run)
        counts.update(self._crew_fill_rosters(date_from, date_to, dry_run=dry_run))
        return counts

    def _crew_fill_rosters(self, date_from, date_to, dry_run=False):
        """Нарядите на центровете на ротацията за периода."""
        self.ensure_one()
        counts = {"rosters_created": 0, "rosters_updated": 0, "rosters_deleted": 0,
                  "rosters_manual": 0}
        if not self.workcenter_ids:
            return counts
        slots = self.env["planning.slot"].search([
            ("crew_rotation_id", "=", self.id),
            ("crew_date", ">=", date_from),
            ("crew_date", "<=", date_to),
            ("resource_id", "!=", False),
        ])
        # (ден, ключ на смяната) -> (бригада, служители)
        wanted = defaultdict(lambda: [self.env["planning.crew"], self.env["hr.employee"]])
        for slot in slots:
            employee = slot.resource_id.employee_id
            if not (employee and slot.template_id):
                continue
            entry = wanted[(slot.crew_date, crew_hours_to_key(slot.template_id.start_time))]
            entry[0] |= slot.crew_id
            entry[1] |= employee
        Roster = self.env["mrp.workcenter.roster"].with_context(crew_rotation_sync=True)
        existing = Roster.search([
            ("workcenter_id", "in", self.workcenter_ids.ids),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
        ])
        by_key = {(r.workcenter_id.id, r.date, r.shift_key): r for r in existing}
        to_create = []
        for workcenter in self.workcenter_ids:
            for (day, key), (crew, employees) in wanted.items():
                roster = by_key.pop((workcenter.id, day, key), None)
                if not roster:
                    to_create.append({
                        "workcenter_id": workcenter.id,
                        "date": day,
                        "shift_key": key,
                        "employee_ids": [Command.set(employees.ids)],
                        "crew_rotation_id": self.id,
                        "crew_id": crew[:1].id,
                    })
                elif roster.crew_manual or not roster.crew_rotation_id:
                    counts["rosters_manual"] += 1
                elif roster.employee_ids != employees or roster.crew_id != crew[:1]:
                    counts["rosters_updated"] += 1
                    if not dry_run:
                        roster.write({"employee_ids": [Command.set(employees.ids)],
                                      "crew_id": crew[:1].id})
        # Наряди от ротацията без хора в смяната (напр. всички в отпуск без заместник)
        for roster in by_key.values():
            if roster.crew_rotation_id == self and not roster.crew_manual:
                counts["rosters_deleted"] += 1
                if not dry_run:
                    roster.unlink()
        counts["rosters_created"] = len(to_create)
        if not dry_run and to_create:
            Roster.create(to_create)
        return counts


class PlanningCrewRotationGenerate(models.TransientModel):
    _inherit = "planning.crew.rotation.generate"

    count_rosters_created = fields.Integer("Rosters to Create", readonly=True)
    count_rosters_updated = fields.Integer("Rosters to Update", readonly=True)
    count_rosters_deleted = fields.Integer("Rosters to Delete", readonly=True)
    count_rosters_manual = fields.Integer(
        "Rosters Kept", readonly=True,
        help="Rosters changed by hand or made without the rotation; they are left "
             "as they are.")
