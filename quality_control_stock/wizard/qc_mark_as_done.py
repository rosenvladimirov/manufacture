# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from itertools import groupby

import logging

_logger = logging.getLogger(__name__)


class QualityControlConfirm(models.TransientModel):
    _inherit = "wiz.quality.control.confirm"

    picking_ids = fields.Many2many('stock.picking', string='Stock pickings')
    recreate_inspection = fields.Boolean('Create inspection')
    # inspection_lines = fields.Many2many('qc.inspection.line', string='Inspection lines')

    @api.model
    def default_get(self, fields_list):
        res = super(QualityControlConfirm, self).default_get(fields_list)
        if not res.get('picking_ids') and self._context['active_model'] == 'qc.inspection':
            inspection_ids = self.env['qc.inspection'].browse(self._context['active_ids'])
            picking_ids = inspection_ids.mapped('picking_id')
            if picking_ids:
                res['picking_ids'] = [(6, False, picking_ids.ids)]
        return res

    @api.multi
    def action_recreate(self):
        for record in self:
            for inspection in record.inspection_ids:
                if inspection.state == 'ready' and record.del_inspection:
                    inspection.state = 'draft'
                    inspection.auto_generated = False
                    # _logger.info("INSPEKTION %s:%s" % (inspection.state, inspection.auto_generated))
                    inspection.with_context(dict(self._context, force_unlink=True)).unlink()
                elif inspection.state == 'ready' and not record.del_inspection:
                    inspection.state = 'draft'
                    inspection.toggle_active()
            record.picking_ids._create_inspection()
            record.picking_ids._compute_count_inspections()
        return {'type': 'ir.actions.act_window_close'}
