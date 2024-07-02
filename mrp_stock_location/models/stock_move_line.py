# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, exceptions, fields, models, _

import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    production_raw_id = fields.Many2one('stock.location', 'Raw material stock location',
                                        related='move_id.raw_material_production_id.location_src_id')
    production_final_id = fields.Many2one('stock.location', 'Final product stock location',
                                          related='move_id.production_id.location_dest_id')
