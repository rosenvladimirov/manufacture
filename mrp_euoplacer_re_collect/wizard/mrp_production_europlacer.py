# coding: utf-8
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _

import logging

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MrpProductionEuroplacer(models.TransientModel):
    _name = 'mrp.production.europlacer'
    _description = 'Re collect europlacer files'
    # _inherit = ['barcodes.barcode_events_mixin']

    production_ids = fields.Many2many('mrp.production', string='Manufacture Production', required=True)
    rule = fields.Char('Rule')
    overwrite = fields.Char('Overwrite')
    path = fields.Char('Path/Program')

    @api.model
    def default_get(self, default_fields):
        res = super(MrpProductionEuroplacer, self).default_get(default_fields)
        if not res.get('production_ids') and self._context.get('active_model') == 'mrp.production':
            production_ids = self.env['mrp.production'].browse(self._context['active_ids'])
            res['production_ids'] = [(6, False, production_ids.ids)]
        return res

    @api.multi
    def action_fs(self):
        self.ensure_one()
        if self._context.get('active_model') == 'mrp.production' and self._context.get('active_ids'):
            production_ids = self.env['mrp.production'].browse(self._context['active_ids'])
        else:
            production_ids = self.production_ids

        if production_ids:
            for production_id in production_ids:
                self.env['europlacer.fs'].with_delay().\
                    action_restore(production_id.name, self.rule, self.overwrite, self.path)
        else:
            return {'type': 'ir.actions.act_window_close'}
