# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from odoo import fields, models


class MrpWorkcenterRoster(models.Model):
    _inherit = "mrp.workcenter.roster"

    crew_rotation_id = fields.Many2one(
        "planning.crew.rotation", string="Crew Rotation", readonly=True, index=True,
        ondelete="set null")
    crew_id = fields.Many2one("planning.crew", string="Crew", readonly=True, ondelete="set null")
    crew_manual = fields.Boolean(
        string="Changed by Hand", copy=False,
        help="The crew of this roster was changed by hand after the crew rotation "
             "filled it; generating the shifts again does not touch it.")

    def write(self, vals):
        if "employee_ids" in vals and not self.env.context.get("crew_rotation_sync"):
            filled = self.filtered(lambda r: r.crew_rotation_id and not r.crew_manual)
            if filled:
                super(MrpWorkcenterRoster, filled).write({"crew_manual": True})
        return super().write(vals)
