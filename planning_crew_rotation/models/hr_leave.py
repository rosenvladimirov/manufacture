# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from odoo import models


class HrLeave(models.Model):
    _inherit = "hr.leave"

    def action_validate(self, check_state=True):
        """Утвърденият отпуск само СИГНАЛИЗИРА (Росен 14.10.2026): ротацията
        се маркира „нужно презареждане“, а пренареждането със заместници е при
        следващото ръчно генериране. (В 18 утвърждаването е action_validate, в 19 —
        _action_validate.)"""
        res = super().action_validate(check_state=check_state)
        self._crew_flag_reload()
        return res

    def action_refuse(self):
        res = super().action_refuse()
        self._crew_flag_reload()
        return res

    def _crew_flag_reload(self):
        Slot = self.env["planning.slot"].sudo()
        for leave in self:
            if not (leave.employee_id and leave.request_date_from and leave.request_date_to):
                continue
            # по дните на смяната, както генераторът (нощната е извън 8–17)
            slots = Slot.search([
                ("crew_generated", "=", True),
                "|", ("resource_id", "=", leave.employee_id.resource_id.id),
                ("crew_substitute_for_id", "=", leave.employee_id.id),
                ("crew_date", ">=", leave.request_date_from),
                ("crew_date", "<=", leave.request_date_to),
            ])
            for rotation in slots.crew_rotation_id.filtered(lambda r: not r.reload_needed):
                rotation.reload_needed = True
                rotation.message_post(body=self.env._(
                    "Leave of %(employee)s from %(date_from)s to %(date_to)s touches "
                    "generated shifts; generate the shifts again.",
                    employee=leave.employee_id.name,
                    date_from=leave.request_date_from, date_to=leave.request_date_to))
