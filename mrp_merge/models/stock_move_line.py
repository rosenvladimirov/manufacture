# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, exceptions, fields, models, _


class StockMove(models.Model):
    _inherit = 'stock.move.line'

    qty_dome_merged = fields.Float('MO Merged quantity')
