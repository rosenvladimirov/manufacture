# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""M15.6: прекият запис в leave-а на поръчка синхронизира датите ѝ (К3) и
минава през M15; leave `other` без поръчка върху ресурс на център не бива
да застъпва незапочнати поръчки (Р30)."""
from odoo import api, models
from odoo.exceptions import ValidationError
from odoo.tools import SQL
from odoo.tools.misc import format_datetime

from .mrp_workcenter_lanes import CREW_LANE_DEFER
from .mrp_workorder_lanes import CREW_LANE_WO_WRITE

# Полетата на leave-а, чиято промяна мести поръчката или заетостта.
CREW_LEAVE_FIELDS = {"date_from", "date_to", "resource_id", "time_type"}


class ResourceCalendarLeaves(models.Model):
    _inherit = "resource.calendar.leaves"

    def _crew_lane_skip(self):
        context = self.env.context
        return context.get(CREW_LANE_DEFER) or context.get(CREW_LANE_WO_WRITE)

    @api.model_create_multi
    def create(self, vals_list):
        leaves = super().create(vals_list)
        if not self._crew_lane_skip():
            leaves._crew_check_free_leaves()
        return leaves

    def write(self, vals):
        res = super().write(vals)
        if not self._crew_lane_skip() and CREW_LEAVE_FIELDS.intersection(vals):
            WorkOrder = self.env["mrp.workorder"]
            workorders = WorkOrder.sudo().search([("leave_id", "in", self.ids)])
            if workorders:
                # К3: датите на поръчката зависят само от leave_id —
                # прекият запис в leave-а иначе ги разсинхронизира.
                for name in ("date_start", "date_finished"):
                    self.env.add_to_compute(WorkOrder._fields[name], workorders)
                workorders._crew_check_lane_overlap()
            self._crew_check_free_leaves()
        return res

    def _crew_check_free_leaves(self):
        """Leave `other` без поръчка върху ресурса (или календара) на център,
        който застъпва незапочнати поръчки → отказ със списъка."""
        leaves = self.filtered(lambda leave: leave.time_type == "other")
        if not leaves:
            return
        WorkOrder = self.env["mrp.workorder"]
        WorkOrder._crew_lane_flush()
        # Печатът на засегнатите центрове (ресурсът или — глобален leave —
        # календарът, К2): едновременен запис на поръчка в тях чака този
        # ред и се повтаря със свеж снимък, вместо да не види leave-а.
        WorkOrder._crew_lane_stamp(leaves._crew_free_leave_workcenter_ids())
        self.env.cr.execute(
            SQL(
                """
                SELECT l.id, a.id
                  FROM resource_calendar_leaves l
                  JOIN mrp_workcenter w
                    ON (l.resource_id = w.resource_id OR l.resource_id IS NULL)
                   AND (l.calendar_id = w.resource_calendar_id OR l.calendar_id IS NULL)
                  JOIN mrp_workorder a
                    ON a.workcenter_id = w.id
                   AND a.state IN ('pending', 'waiting', 'ready')
                   AND DATE_TRUNC('second', l.date_from) < DATE_TRUNC('second', a.date_finished)
                   AND DATE_TRUNC('second', a.date_start) < DATE_TRUNC('second', l.date_to)
                 WHERE l.id = ANY(%(ids)s)
                   AND NOT EXISTS (
                       SELECT 1 FROM mrp_workorder o WHERE o.leave_id = l.id)
                   AND NOT EXISTS (
                       SELECT 1 FROM mrp_workcenter_productivity p
                        WHERE p.workorder_id = a.id)
                 ORDER BY l.id, a.date_start
                """,
                ids=leaves.ids,
            )
        )
        rows = self.env.cr.fetchall()
        if not rows:
            return
        workorders = self.env["mrp.workorder"].sudo().browse([row[1] for row in rows])
        leave = self.sudo().browse(rows[0][0])
        raise ValidationError(
            self.env._(
                "The time off %(leave)s (%(start)s – %(stop)s) overlaps work orders "
                "that are not started: %(wos)s.",
                leave=leave.name or leave.display_name,
                start=format_datetime(self.env, leave.date_from),
                stop=format_datetime(self.env, leave.date_to),
                wos=", ".join(workorders.mapped("display_name")),
            )
        )

    def _crew_free_leave_workcenter_ids(self):
        """Центровете, чиято заетост засягат leave-овете без поръчка в
        `self` (наборът от К2)."""
        self.env.cr.execute(
            SQL(
                """
                SELECT DISTINCT w.id
                  FROM resource_calendar_leaves l
                  JOIN mrp_workcenter w
                    ON (l.resource_id = w.resource_id OR l.resource_id IS NULL)
                   AND (l.calendar_id = w.resource_calendar_id OR l.calendar_id IS NULL)
                 WHERE l.id = ANY(%(ids)s)
                   AND NOT EXISTS (
                       SELECT 1 FROM mrp_workorder o WHERE o.leave_id = l.id)
                """,
                ids=self.ids,
            )
        )
        return [row[0] for row in self.env.cr.fetchall()]
