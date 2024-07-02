# -*- coding: utf-8 -*-
# Copyright 2015-2017 See manifest
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

import pytz
import datetime
from odoo import models, fields, api, _

import logging
_logger = logging.getLogger(__name__)


class WizardMrpRegenerateSubLevels(models.TransientModel):
    _name = "wizard.mrp.regenerate.sub.levels"

    production_ids = fields.Many2many('mrp.production', string='Productions')

    @api.model
    def default_get(self, fields_list):
        res = super(WizardMrpRegenerateSubLevels, self).default_get(fields_list)
        productions = False
        if self._context.get('active_ids') and self._context.get('active_model') == 'mrp.production':
            productions = self.env['mrp.production'].browse(self._context['active_ids'])
        if productions.filtered(lambda r: r.sub_production == 'normal'):
            res.update({
                'production_ids': [(6, False, productions.ids)]
            })
        return res

    @api.multi
    def action_regenerate_sub_levels(self):
        for record in self:
            productions = record.production_ids
            if len(productions.ids) > 0:
                for production in productions:
                    production.write({'sub_production': 'sub'})
                productions.with_delay().server_update_procurement_for_moves()
        return {'type': 'ir.actions.act_window_close'}
