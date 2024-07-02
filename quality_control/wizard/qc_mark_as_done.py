# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from itertools import groupby

import logging

_logger = logging.getLogger(__name__)


class QualityControlConfirm(models.TransientModel):
    _name = "wiz.quality.control.confirm"

    inspection_ids = fields.Many2many('qc.inspection', string='Inspections')
    del_inspection = fields.Boolean('Delete inspection')
    # inspection_lines = fields.Many2many('qc.inspection.line', string='Inspection lines')

    @api.model
    def default_get(self, fields_list):
        res = super(QualityControlConfirm, self).default_get(fields_list)
        if not res.get('inspection_ids') and self._context.get('active_model') == 'qc.inspection':
            inspection_ids = self.env['qc.inspection'].browse(self._context['active_ids'])
            res['inspection_ids'] = [(6, False, inspection_ids.ids)]

        return res

    @api.multi
    def action_confirms(self):
        for record in self:
            for inspection in record.inspection_ids:
                if inspection.state == 'ready' and not record.del_inspection:
                    inspection.action_confirm()
                elif inspection.state == 'ready' and record.del_inspection:
                    inspection.with_context(dict(self._context, force_unlink=True)).unlink()
        return {'type': 'ir.actions.act_window_close'}
