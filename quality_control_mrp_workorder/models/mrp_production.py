# Copyright 2014 Serv. Tec. Avanzados - Pedro M. Baeza
# Copyright 2018 Simone Rubino - Agile Business Group
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.addons.quality_control.models.qc_trigger_line import \
    _filter_trigger_lines


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    @api.multi
    @api.depends('qc_inspections_ids')
    def _compute_count_inspections(self):
        for production in self:
            production.created_inspections = len(production.qc_inspections_ids.filtered(lambda r: not r.workorder_id))

    created_inspections = fields.Integer(compute="_compute_count_inspections")
