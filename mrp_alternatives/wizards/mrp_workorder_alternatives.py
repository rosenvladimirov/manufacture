# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from itertools import groupby

import logging

_logger = logging.getLogger(__name__)


class WizMrpWorkorderAlternatives(models.TransientModel):
    _name = "wiz.mrp.workorder.alternatives"
    _description = "Wizard for MRP alternatives"

    workorder_ids = fields.Many2many('mrp.workorder', string='Work order')
    alternatives_line = fields.One2many('wiz.mrp.alternatives.line', inverse_name='wiz_alternatives', string='Alternatives')

    @api.model
    def default_get(self, fields_list):
        res = super(WizMrpWorkorderAlternatives, self).default_get(fields_list)
        workorder_ids = []
        if not res.get('workorder_ids') and self._context.get('active_model') == 'mrp.workorder':
            workorder_ids = self.env['mrp.workorder'].browse(self._context['active_ids'])
            if workorder_ids:
                res['workorder_ids'] = [(6, False, workorder_ids.ids)]
        if not res.get('workorder_ids'):
            raise UserError(_('Not found any workorders!'))
        else:
            res['alternatives_line'] = []
            active_move_line_ids = workorder_ids.mapped('active_move_line_ids')
            product_ids = self.env['product.product']
            for line in active_move_line_ids:
                if line.product_id.alternative_component_ids:
                    product_ids |= line.product_id
                    product_ids |= line.product_id.alternative_component_ids
            if product_ids:
                product_ids = product_ids.ids
                for line in active_move_line_ids.filtered(lambda r: r.product_id.id in product_ids):
                    res['alternatives_line'] += [(0, False, {
                        'stock_move_line_id': line.id,
                        'workorder_id': line.workorder_id.id,
                        'product_id': line.product_id.id,
                        'product_uom_id': line.product_uom_id.id,
                        'skip_alternative': line.skip_alternative,
                    })]
        return res

    @api.multi
    def action_alternatives(self):
        for record in self:
            for line in record.alternatives_line:
                line.stock_move_line_id.write({
                    'skip_alternative': line.skip_alternative,
                })


class WizMrpAlternativesLine(models.TransientModel):
    _name = "wiz.mrp.alternatives.line"
    _description = "Wizard Lines for MRP alternatives"

    wiz_alternatives = fields.Many2one('wiz.mrp.workorder.alternatives',
                                       string='Wizard for alternatives',
                                       required=True,
                                       index=True,
                                       ondelete='cascade')
    stock_move_line_id = fields.Many2one('stock.move.line', 'Stock move line')
    workorder_id = fields.Many2one('mrp.workorder', 'Work order')
    product_id = fields.Many2one('product.product', 'Product', related='stock_move_line_id.product_id')
    product_uom_id = fields.Many2one('product.uom', 'Product uom', related='stock_move_line_id.product_uom_id')
    skip_alternative = fields.Boolean('Skip using material')
