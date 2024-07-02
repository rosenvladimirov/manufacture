# -*- coding: utf-8 -*-

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    production_id = fields.Many2one('mrp.production', string='Production order')
