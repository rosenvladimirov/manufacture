# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from odoo import api, fields, models


class MrpWorkcenter(models.Model):
    _inherit = "mrp.workcenter"

    crew_rotation_id = fields.Many2one(
        "planning.crew.rotation", string="Crew Rotation", index=True,
        check_company=True,
        help="The work center works the shifts of this crew rotation: its working "
             "schedule becomes the schedule of the rotation and the crew on shift "
             "fills its roster when the shifts are generated.")

    # Росен 14.10.2026: „казваме на центъра кои са смените“ — календарът
    # идва от ротацията, не се поддържа отделно.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._crew_rotation_calendar_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._crew_rotation_calendar_vals(vals)
        return super().write(vals)

    def _crew_rotation_calendar_vals(self, vals):
        if vals.get("crew_rotation_id"):
            rotation = self.env["planning.crew.rotation"].browse(vals["crew_rotation_id"])
            if rotation.calendar_id:
                vals["resource_calendar_id"] = rotation.calendar_id.id
