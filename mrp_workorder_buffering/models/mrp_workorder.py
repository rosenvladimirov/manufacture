# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from itertools import groupby

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.addons.queue_job.job import job

from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round
from odoo.addons import decimal_precision as dp

import logging

_logger = logging.getLogger(__name__)


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    use_buffering = fields.Boolean('Buffering', help='Please checked it if wand to buffer the activities')
    buffer_product_ids = fields.One2many('mrp.workorder.buffer', 'workorder_id', 'Buffering workorder')
    buffered_move_line_ids = fields.One2many('stock.move.line', 'buffer_workorder_id',
                                             domain=[('done_wo', '=', False)])
    buffered_qty_producing = fields.Float(
        'Buffered Produced Quantity', default=1.0,
        digits=dp.get_precision('Product Unit of Measure'),
        compute='_get_buffered_qty_producing',
    )
    buffered_final_lot_id = fields.Many2one(
        'stock.production.lot', 'Lot/Serial Number',
        compute='_get_buffered_final_lot_id'
    )
    buffered_qty_remaining = fields.Float(
        'Buffered Remaining Quantity',
        digits=dp.get_precision('Product Unit of Measure'),
        compute='_get_buffered_qty_remaining',
    )

    @api.multi
    def _get_buffered_qty_producing(self):
        for record in self:
            record.buffered_qty_producing = record.buffer_product_ids and record.buffer_product_ids[
                -1].qty_producing or 0.0
            record.buffered_qty_remaining = sum([x.qty_producing
                                                 for x in record.buffer_product_ids.
                                                filtered(lambda r: not r.product_id)])

    @api.multi
    def _get_buffered_qty_remaining(self):
        for record in self:
            record.buffered_qty_remaining = sum([x.qty_producing
                                                 for x in record.buffer_product_ids.
                                                filtered(lambda r: not r.product_id)])

    @api.multi
    def _get_buffered_final_lot_id(self):
        for record in self:
            record.buffered_final_lot_id = record.buffer_product_ids and record.buffer_product_ids[
                -1].final_lot_id or False

    @api.multi
    def toggle_use_buffering(self):
        for record in self:
            record.use_buffering = not record.use_buffering
            if not record.use_buffering:
                record.buffer_product_ids.unlink()
                record.buffered_move_line_ids.unlink()

    @api.onchange('final_lot_id')
    @api.depends('buffered_final_lot_id', 'buffered_qty_producing', 'buffered_qty_remaining')
    def onchange_final_lot_id(self):
        for wo in self:
            if not wo.buffer_product_ids.filtered(lambda r: not r.lot_id and r.final_lot_id == wo.final_lot_id):
                wo.buffer_product_ids += self.env['mrp.workorder.buffer'].new({
                    'final_product_id': wo.product_id.id,
                    'workorder_id': wo.id,
                    'operation_id': wo.operation_id.id,
                    'final_lot_id': wo.final_lot_id and wo.final_lot_id.id or False,
                    'qty_producing': wo.qty_producing,
                })
                wo._get_buffered_qty_remaining()

    def record_production(self):
        for record in self:
            res = False
            if not self._context.get('no_check_buffering', False) \
                    and record.use_buffering and record.buffer_product_ids:
                for final_product_id, lines in \
                        groupby(record.buffer_product_ids.
                                sorted(lambda r: "%s-%s-%s" % (int(r.final_product_id.id), int(r.final_lot_id.id), int(r.lot_id.id))),
                                lambda r: "%s-%s" % (int(r.final_product_id.id), int(r.final_lot_id.id))):
                    to_remove = self.env['stock.move.line']
                    active_to_remove = self.env['stock.move.line']
                    buffering_to_remove = self.env['mrp.workorder.buffer']
                    copy_lines = lines
                    for inx, line in enumerate(copy_lines):
                        if not line.product_id:
                            record.product_id = line.final_product_id
                            record.qty_producing = line.qty_producing
                            record.final_lot_id = line.final_lot_id
                        # _logger.info("COPY_LINE %s=[%s]%s" % (inx, line.final_lot_id.name, line.final_product_id.name))

                        buffering_to_remove += line
                        if not line.product_id:
                            continue

                        # Adding only components
                        to_adding = record.buffered_move_line_ids. \
                            filtered(lambda r: r.product_id == line.product_id and r.lot_id == line.lot_id and r.buffer_workorder_id == record)
                        if not to_adding:
                            continue

                        # Collect to remove components
                        to_remove += to_adding
                        active_to_remove += record.active_move_line_ids.filtered(lambda r: r.product_id == line.product_id and r.lot_id == line.lot_id)

                        # Populate buffered lines
                        for adding in to_adding:
                            to_adding_value = adding._convert_to_write(adding._cache)
                            _logger.info("TO_ADDING_VALUE %s" % to_adding_value)
                            to_adding_value.update({
                                'done_wo': False,
                                'buffer_workorder_id': False
                            })
                            record.active_move_line_ids += self.env['stock.move.line'].new(to_adding_value)

                    res = record.with_context(dict(self._context, no_check_buffering=True)).record_production()
                    if res:
                        to_remove.unlink()
                        active_to_remove.unlink()
                        buffering_to_remove.unlink()

                record.use_buffering = record.qty_remaining > 0
            else:
                res = super(MrpWorkorder, self).record_production()
            return res

    def _generate_lot_ids(self):
        if self._context.get('no_check_buffering'):
            return
        return super(MrpWorkorder, self)._generate_lot_ids()

    def _assign_default_final_lot_id(self):
        if self.use_buffering:
            self.work_component = True
        else:
            super(MrpWorkorder, self)._assign_default_final_lot_id()


class MrpWorkorderBuffer(models.Model):
    _name = "mrp.workorder.buffer"
    _description = "Buffering workorder lines"

    workorder_id = fields.Many2one('mrp.workorder', 'Work Orders', index=True, required=True, ondelete='cascade')
    operation_id = fields.Many2one('mrp.routing.workcenter', 'Operation To Consume')
    product_id = fields.Many2one('product.product', 'Product', domain=[('type', 'in', ['product', 'consu'])])
    final_product_id = fields.Many2one('product.product', 'Final product')
    lot_id = fields.Many2one('stock.production.lot', 'Lot/Serial Number')
    final_lot_id = fields.Many2one('stock.production.lot', 'Lot/Serial Number')
    qty_done = fields.Float('Quantity done')
    lot_name = fields.Char('Lot name')
    qty_producing = fields.Float('Currently Produced Quantity', default=1.0,
                                 digits=dp.get_precision('Product Unit of Measure'), )
