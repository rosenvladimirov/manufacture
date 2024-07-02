# -*- coding: utf-8 -*-
# Copyright 2015-2017 See manifest
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

import pytz
import datetime
from odoo import models, fields, api, _

import logging
_logger = logging.getLogger(__name__)


class WizardMrpRegenerateSubLevels(models.TransientModel):
    _inherit = "wizard.mrp.regenerate.sub.levels"

    sale_order_ids = fields.Many2many('sale.order', string='Sale orders')

    @api.model
    def default_get(self, fields_list):
        res = super(WizardMrpRegenerateSubLevels, self).default_get(fields_list)
        productions = False
        if self._context.get('active_ids') and self._context.get('active_model') == 'sale.order':
            res.update({
                'sale_order_ids': [(6, False, self._context['active_ids'])]
            })
            partner_ids = self.env[self._context['active_model']].browse(self._context['active_ids']).mapped('partner_id')
            productions = self.env['mrp.production'].\
                search([('sale_id', 'in', self._context['active_ids']), ('partner_id', 'in', partner_ids.ids)])
        if productions:
            res.update({
                'production_ids': [(6, False, productions.ids)]
            })
        return res
