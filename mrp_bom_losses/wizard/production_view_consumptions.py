# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp

import logging
_logger = logging.getLogger(__name__)


class MrpProductionViewConsumptions(models.TransientModel):
    _name = "mrp.production.view.consumptions"
    _description = "View matrix of consumptions by work orders"

    line_ids = fields.Many2many('mrp.production.view.line')
    production_id = fields.Many2one('mrp.production', 'Manufacture order')
    view_by = fields.Selection([('qty', 'Quantity'),
                                ('wo', 'Is finished WO'),
                                ('move', 'Move lines'),
                                ('operation', 'Operation'),
                                ('lot', 'Lots')
                                ], string="View by", default='qty')

    @api.model
    def default_get(self, fields):
        res = super(MrpProductionViewConsumptions, self).default_get(fields)
        productions = self.production_id
        if not productions and self._context.get('active_id'):
            productions = self.env['mrp.production'].browse(self._context['active_id'])
        consumptions = productions.mapped('production_line_ids')

        value = [(0, 0, {
                'name': "{}'s work order on {}".format(wo.display_name, production.name),
                'product_id': wo.product_id.id,
                'workorder_id': wo.workorder_id.id,
                'product_qty': wo.product_qty,
                'product_wo': wo.product_wo,
                'move_line_id': wo.move_line_id.id,
                'operation_id': wo.operation_id.id,
                'lot_id': wo.lot_id and wo.lot_id.id or False,
            })
            if not production.production_line_ids.filtered(lambda x: x.workorder_id == wo) else
            (4, production.production_line_ids.filtered(lambda x: x.workorder_id == wo)[0].id)
            for production in productions
            for wo in consumptions]
        res.update({
            'production_id': productions.id,
            'view_by': 'qty',
            'line_ids': value
        })
        _logger.info("RES %s:%s" % (res, self._context))
        return res


class MrpProductionViewLine(models.TransientModel):
    _name = "mrp.production.view.line"
    _description = "View lines in matrix of consumptions by work orders"

    name = fields.Char('Matrix name')
    # rows
    product_id = fields.Many2one('product.product', 'Product', domain=[('type', 'in', ['product', 'consu', 'service'])])
    # columns
    workorder_id = fields.Many2one('mrp.workorder', 'Work Orders')
    # values
    product_qty = fields.Float('Quantity Of Product', digits=dp.get_precision('Product Unit of Measure'))
    product_wo = fields.Integer('Checked by workorder', track_visibility='onchange')
    move_line_id = fields.Many2one('stock.move.line', 'Packing Operation')
    operation_id = fields.Many2one('mrp.routing.workcenter', 'Operation')
    lot_id = fields.Many2one('stock.production.lot', 'Lot/Serial Number')
