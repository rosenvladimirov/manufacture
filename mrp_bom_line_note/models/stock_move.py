# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
import math

from odoo import api, fields, models, _

class MrpProduction(models.Model):
    _inherit = 'stock.move'

    notes = fields.Text('Notes', related="bom_line_id.notes", store=True)
    ref_notes = fields.Char('REF', related="bom_line_id.notes", store=True)
