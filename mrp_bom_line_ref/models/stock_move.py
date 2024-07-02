# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
import math

from odoo import api, fields, models, _

class MrpProduction(models.Model):
    _inherit = 'stock.move'

    ref = fields.Text('Notes', related="bom_line_id.ref")
    ref_ref = fields.Char('REF', related="bom_line_id.ref_ref")
