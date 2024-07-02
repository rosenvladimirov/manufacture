# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.addons import decimal_precision as dp

import logging

_logger = logging.getLogger(__name__)


class MecMrpProduction(models.Model):
    _inherit = 'mrp.production'

    oring_product_qty = fields.Float(
        'Origin Quantity To Produce',
        digits=dp.get_precision('Product Unit of Measure'),
        readonly=True, track_visibility='onchange',
    )
