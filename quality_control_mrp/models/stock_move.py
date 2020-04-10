# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class StockMove(models.Model):
    _inherit = 'stock.move'

    qc_test_id = fields.Many2one("qc.test", related="operation_id.qc_test_id")

