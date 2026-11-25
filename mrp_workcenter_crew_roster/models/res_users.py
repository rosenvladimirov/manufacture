# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Изборът на потребителя за Ганта „Планирай център“ (№142 на Теолино).

Гантът по подразбиране скрива неработното време на показаните центрове;
който иска да вижда нощите, почивките и уикендите, си го пуска. Изборът е
на потребителя (не на браузъра) — помни се и на друг компютър."""
from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    crew_gantt_show_off_time = fields.Boolean(
        "Show non-working time in planning",
        help="In the Plan Work Center Gantt, show the nights, breaks, weekends and holidays of the work "
        "centers instead of hiding them.",
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ["crew_gantt_show_off_time"]

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ["crew_gantt_show_off_time"]

    @api.model
    def crew_gantt_set_show_off_time(self, show):
        """Превключвателят на Ганта: записва избора на текущия потребител."""
        self.env.user.write({"crew_gantt_show_off_time": bool(show)})
        return bool(show)
