# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from odoo import api, fields, models

# Полетата, чиято промяна на ръка значи „началникът е решил друго“ —
# генераторът не пипа такава смяна повече.
CREW_MANUAL_FIELDS = {"resource_id", "start_datetime", "end_datetime", "template_id"}


class PlanningSlot(models.Model):
    _inherit = "planning.slot"

    crew_rotation_id = fields.Many2one(
        "planning.crew.rotation", string="Crew Rotation", index=True, readonly=True,
        ondelete="set null")
    crew_id = fields.Many2one("planning.crew", string="Crew", readonly=True, ondelete="set null")
    crew_membership_id = fields.Many2one(
        "planning.crew.membership", readonly=True, ondelete="set null")
    crew_date = fields.Date(string="Crew Day", readonly=True, index=True)
    crew_generated = fields.Boolean(readonly=True, copy=False)
    crew_manual = fields.Boolean(
        string="Changed by Hand", copy=False,
        help="Changed by hand after the crew rotation generated it; generating "
             "again does not touch it.")
    crew_substitute_for_id = fields.Many2one(
        "hr.employee", string="Substitute For", readonly=True, ondelete="set null")
    # кодовете се пазят, текстът е на езика на гледащия (генерирането може да е по RPC)
    crew_warning_codes = fields.Char(readonly=True, copy=False)
    crew_warning = fields.Char(
        string="Labour Code Warning", compute="_compute_crew_warning",
        help="What the shift breaks in the Labour Code for this employee (rest, weekly "
             "hours, night work). Warning only — the shift is kept.")
    crew_has_warning = fields.Boolean(compute="_compute_crew_has_warning", store=True)

    @api.depends("crew_warning_codes")
    def _compute_crew_has_warning(self):
        for slot in self:
            slot.crew_has_warning = bool(slot.crew_warning_codes)

    @api.depends("crew_warning_codes")
    @api.depends_context("lang")
    def _compute_crew_warning(self):
        labels = self.env["planning.crew.rotation"]._crew_issue_labels()
        for slot in self:
            codes = (slot.crew_warning_codes or "").split(",")
            slot.crew_warning = "; ".join(labels.get(c, c) for c in codes if c) or False

    def write(self, vals):
        if not self.env.context.get("crew_rotation_sync") and CREW_MANUAL_FIELDS & set(vals):
            generated = self.filtered(lambda s: s.crew_generated and not s.crew_manual)
            if generated:
                super(PlanningSlot, generated).write({"crew_manual": True})
        return super().write(vals)
