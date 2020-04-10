# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round
from odoo.addons import decimal_precision as dp


class WorkorderAddComponentLot(models.TransientModel):
    _name = "workorder_add.component.lot"
    _description = "Add extra lots in workorder"

    product_id = fields.Many2one('product.product', required=True, )
    lot_id = fields.Many2one('stock.production.lot', 'Lot', track_visibility='onchange')
    lot_name = fields.Char('Lot/Serial Number')
    workorder_id = fields.Many2one('mrp.workorder')
    product_ids = fields.One2many('product.product', compute='_compute_product_ids')

    def _compute_product_ids(self):
        for component in self:
            if component.workorder_id:
                production = self.workorder_id.production_id
                workorder = component.workorder_id
                tracked_moves = workorder.move_raw_ids.filtered(
                    lambda move: move.state not in ('done',
                                                    'cancel') and move.product_id.tracking != 'none' and move.product_id != production.product_id)
                component.product_ids = [(4, x.id) for x in tracked_moves]

    def add_new_lot(self):
        if self.workorder_id:
            workorder = self.workorder_id
            production = self.workorder_id.production_id
            MoveLine = self.env['stock.move.line']
            tracked_moves = workorder.move_raw_ids.filtered(
                lambda move: move.state not in ('done',
                                                'cancel') and move.product_id.tracking != 'none' and move.product_id != production.product_id and move.product_id == self.product_id)
            for move in tracked_moves:
                qty = move.unit_factor * workorder.qty_producing
                if move.product_id.tracking == 'serial':
                    while float_compare(qty, 0.0, precision_rounding=move.product_uom.rounding) > 0:
                        MoveLine.create({
                            'move_id': move.id,
                            'product_uom_qty': 0,
                            'product_uom_id': move.product_uom.id,
                            'qty_done': min(1, qty),
                            'production_id': production.id,
                            'workorder_id': workorder.id,
                            'product_id': move.product_id.id,
                            'lot_id': self.lot_id.id,
                            'lot_name': self.lot_name,
                            'done_wo': False,
                            'location_id': move.location_id.id,
                            'location_dest_id': move.location_dest_id.id,
                        })
                        qty -= 1
                else:
                    MoveLine.create({
                        'move_id': move.id,
                        'product_uom_qty': 0,
                        'product_uom_id': move.product_uom.id,
                        'qty_done': qty,
                        'product_id': move.product_id.id,
                        'lot_id': self.lot_id.id,
                        'lot_name': self.lot_name,
                        'production_id': production.id,
                        'workorder_id': workorder.id,
                        'done_wo': False,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                    })
        return True
