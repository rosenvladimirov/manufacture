# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"

    val_own_in_account_id = fields.Many2one('account.account', 'Own Stock Valuation Account (Incoming)',
                                            company_dependent=True)
