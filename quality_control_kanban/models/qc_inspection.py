# Copyright 2014 Serv. Tec. Avanzados - Pedro M. Baeza
# Copyright 2018 Simone Rubino - Agile Business Group
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class QcInspection(models.Model):
    _inherit = 'qc.inspection'

    color = fields.Integer("Color", compute="_compute_color")

    @api.onchange('inspection_lines')
    def _compute_color(self):
        for record in self:
            record.color = all([x.success for x in record.inspection_lines]) and 1 or 4
