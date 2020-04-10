# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    costs_hour = fields.Float(string='Cost per hour', help="Specify cost of work center per hour.")
    costs_hour_account_id = fields.Many2one('account.analytic.account', string="Analytic Account",
                                             help="Fill this only if you want automatic analytic accounting entries on production orders.")
