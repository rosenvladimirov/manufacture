# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, exceptions, fields, models, _

import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    skip_alternative = fields.Boolean('Skip using material',
                                      related='move_id.bom_line_id.skip_alternative',
                                      related_sudo=True,
                                      store=True)
