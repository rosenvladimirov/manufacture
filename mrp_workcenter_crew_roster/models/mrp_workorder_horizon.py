# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Датите на дългосрочния план (Росен 14.10.2026).

В Odoo 19 непланираната работна поръчка е без дати (МО е „планирано“, щом
поне една поръчка има дати — `_compute_is_planned`), затова Гантът не може да
я покаже. Дългосрочният план показва и непланираните: Гантът му стъпва на
„началото/края в плана“ — датите на поръчката, а за непланираната — началото
на МО-то и продължителността ѝ. Влачене от нашия Гант минава през
`crew_drop` и я планира; разтягане пише обратно истинските дати.
"""
from datetime import timedelta

from odoo import api, fields, models

# Непланирана поръчка без очаквана продължителност — колкото да се вижда.
CREW_UNPLANNED_MINUTES = 60.0


class MrpWorkorderHorizon(models.Model):
    _inherit = "mrp.workorder"

    crew_gantt_start = fields.Datetime(
        string="Start in the Plan",
        compute="_compute_crew_gantt_dates",
        inverse="_inverse_crew_gantt_dates",
        store=True,
        readonly=False,
        help="The start of the work order, or the start of its manufacturing "
        "order while it is not planned.",
    )
    crew_gantt_stop = fields.Datetime(
        string="End in the Plan",
        compute="_compute_crew_gantt_dates",
        inverse="_inverse_crew_gantt_dates",
        store=True,
        readonly=False,
    )
    crew_is_unplanned = fields.Boolean(
        string="Not Planned",
        compute="_compute_crew_gantt_dates",
        store=True,
    )

    @api.depends("date_start", "date_finished", "duration_expected", "production_id.date_start")
    def _compute_crew_gantt_dates(self):
        for wo in self:
            if wo.date_start and wo.date_finished:
                wo.crew_gantt_start = wo.date_start
                wo.crew_gantt_stop = wo.date_finished
                wo.crew_is_unplanned = False
                continue
            start = wo.production_id.date_start
            minutes = wo.duration_expected or CREW_UNPLANNED_MINUTES
            wo.crew_gantt_start = start
            wo.crew_gantt_stop = start and start + timedelta(minutes=minutes)
            wo.crew_is_unplanned = True

    def _inverse_crew_gantt_dates(self):
        """Разтягане/запис в дългосрочния Гант = нови дати на поръчката (през
        нашия `write` — пистите, избутването, залепването)."""
        for wo in self:
            if not (wo.crew_gantt_start and wo.crew_gantt_stop):
                continue
            # Само сменената дата: с двете наведнъж ядрото смята края наново
            # от продължителността (`mrp_workorder.write`) и разтягането се губи.
            vals = {}
            if wo.crew_gantt_start != wo.date_start:
                vals["date_start"] = wo.crew_gantt_start
            if wo.crew_gantt_stop != wo.date_finished:
                vals["date_finished"] = wo.crew_gantt_stop
            if vals:
                wo.write(vals)
