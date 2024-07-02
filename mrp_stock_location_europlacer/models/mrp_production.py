# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp

import logging

_logger = logging.getLogger(__name__)


class MrpConcernedPattern(models.Model):
    _name = 'mrp.concerned.pattern'
    _description = 'Concerned pattern info'
    _order = 'sequence'

    def _get_sequence(self):
        return len(self.production_id.concerned_pattern_ids.ids) + 1

    production_id = fields.Many2one('mrp.production', 'Production', index=True, required=True)
    sequence = fields.Integer('Sequence', default=_get_sequence)
    right_concerned_pattern = fields.Char('Concerned Pattern')

    @api.model
    def create(self, vals):
        if 'production_id' in vals:
            production_id = self.env['mrp.production'].browse(vals['production_id'])
            vals['sequence'] = len(production_id.concerned_pattern_ids.ids) + 1
        return super(MrpConcernedPattern, self).create(vals)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    concerned_pattern_ids = fields.One2many('mrp.concerned.pattern', 'production_id', 'Concerned Pattern')
