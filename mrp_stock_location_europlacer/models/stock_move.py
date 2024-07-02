# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from itertools import groupby
from odoo.exceptions import UserError, RedirectWarning
from odoo.tools import float_is_zero
import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    filename = fields.Char("File name")
