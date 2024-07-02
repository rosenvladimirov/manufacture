# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError
from odoo.addons.queue_job.job import job

_logger = logging.getLogger(__name__)


class MrpWorkorderProcess(models.TransientModel):
    _name = 'wiz.mrp.workorder.process'
    _description = 'Auto Process mrp work order'

    mo_id = fields.Many2one('mrp.production', 'Manufacturing Order', required=True)
    production_line_ids = fields.One2many(
        string="MRP work order process Wizard lines",
        comodel_name="wiz.mrp.workorder.process.line",
        inverse_name="production_process_wizard_id",
    )
    product_qty = fields.Float(
        'Quantity To Process',
        digits=dp.get_precision('Product Unit of Measure'), required=True)
    force_mark_as_done = fields.Boolean('Force mark as done')
    force_un_reserve_done = fields.Boolean('Force un-reserve')

    @api.model
    def default_get(self, default_fields):
        res = super(MrpWorkorderProcess, self).default_get(default_fields)
        _logger.info("DEFAULT %s:%s" % (default_fields, res))
        if 'mo_id' in default_fields and not res.get('mo_id') and \
                self._context.get('active_model') == 'mrp.production' and self._context.get('active_id'):
            res['mo_id'] = self._context['active_id']
        if res.get('mo_id'):
            production_id = self.env['mrp.production'].browse(res['mo_id'])
            if production_id.state not in ['planned', 'progress']:
                raise UserError(_('Only in state planed or progress is available this function'))
            workorder_ids = []
            for line in production_id.workorder_ids:
                workorder_ids.append((0, 6, {
                    'workorder_id': line.id,
                    'qty_produced': line.qty_produced,
                    'qty_producing': line.qty_producing,
                    'state': line.state,
                    'product_qty': production_id.product_qty,
                    'product_tracking': production_id.product_id.tracking,
                }))
            res.update({
                'production_line_ids': workorder_ids,
                'product_qty': res.get('product_qty', False) or production_id.product_qty,
            })
        return res

    @api.onchange('product_qty')
    @api.depends('production_line_ids')
    def onchange_product_qty(self):
        for record in self:
            for line in record.production_line_ids:
                line.product_qty = record.product_qty

    @api.multi
    def server_action_process_workorder(self):
        for record in self:
            for line in record.production_line_ids:
                line.with_delay().action_single_process_workorder(record.force_mark_as_done, True)

    @api.multi
    @job(default_channel='root.mrp')
    def action_single_process_workorder(self, force_mark_as_done, server_action=False):
        mo_ids = self.env['mrp.production']
        for line in self.production_line_ids:
            workorder_id = line.workorder_id
            mo_ids |= workorder_id.production_id
            product_qty = line.product_qty - workorder_id.qty_produced

            if product_qty <= 0.0:
                continue

            if workorder_id.working_state != 'blocked':
                workorder_id.qty_producing = product_qty
                workorder_id.with_context(dict(self._context, force_produce=True)).button_empty_bins()
                workorder_id.button_start()
                finish_product_id = workorder_id.product_id
                if workorder_id.product_tracking:
                    lot_obj = self.env['stock.production.lot']
                    next_lot = lot_obj.default_get(['name'])
                    next_lot.update({
                        'product_id': finish_product_id.id,
                        'product_uom_id': finish_product_id.product_tmpl_id.uom_id.id,
                    })
                    final_lot_id = lot_obj.create(next_lot)
                    prefix = finish_product_id.label_prefix_id and finish_product_id.label_prefix_id.code
                    final_lot = prefix and f"{prefix}{final_lot_id.name}" or {final_lot_id.name}
                    # workorder_id.final_lot_id = final_lot_id
                    workorder_id.work_component = False
                    workorder_id.work_production = False
                    workorder_id.on_barcode_scanned(final_lot)
                _logger.info(
                    _('Put for produce %s in work order %s' % (workorder_id.qty_producing, workorder_id.name)))
                if server_action:
                    workorder_id.record_production()
                else:
                    try:
                        workorder_id.record_production()
                    except ValueError:
                        _logger.info(_('Error when validate work order'))
            else:
                raise UserError(_('The work order %s in state %s') %
                                (workorder_id.name, workorder_id.working_state))
        for mo_id in mo_ids:
            for raw_line in mo_id.raw_move_line_ids:
                if raw_line.qty_done != 0.0 and raw_line.product_id.tracking != 'none' and not raw_line.lot_id:
                    raw_line.qty_done = 0.0
            if mo_id.check_to_done \
                    and (not any([x for x in mo_id.move_raw_ids if x.product_uom_qty != x.quantity_done])
                         or force_mark_as_done):
                move_line_ids = mo_id.move_raw_ids.mapped('move_line_ids')
                for line in move_line_ids:
                    qty_available = line.product_id.with_context(dict(self._context, location=mo_id.location_src_id.id)).qty_available
                    if not qty_available < line.qty_done:
                        line.qty_done = qty_available
                if server_action:
                    mo_id.button_mark_done()
                else:
                    try:
                        mo_id.button_mark_done()
                    except ValueError:
                        _logger.info(_('Error when validate production order'))

    @api.multi
    def action_process_workorder(self):
        for record in self:
            for line in record.production_line_ids:
                line.with_delay().action_single_process_workorder(record.force_mark_as_done)


class MrpWorkorderProcessLine(models.TransientModel):
    _name = "wiz.mrp.workorder.process.line"
    _description = 'Auto Process mrp work order lines'

    production_process_wizard_id = fields.Many2one(
        string="MRP work order process Wizard",
        comodel_name="wiz.mrp.workorder.process",
        ondelete="cascade",
        required=True,
    )
    workorder_id = fields.Many2one('mrp.workorder', 'Workorder')
    work_order_name = fields.Char(
        'Name',
        related='workorder_id.display_name')
    qty_produced = fields.Float(
        'Quantity', default=0.0,
        related='workorder_id.qty_produced',
        digits=dp.get_precision('Product Unit of Measure'),
        help="The number of products already handled by this work order")
    qty_producing = fields.Float(
        'Currently Produced Quantity', default=1.0,
        digits=dp.get_precision('Product Unit of Measure'),
        related='workorder_id.qty_producing',
    )
    state = fields.Selection([
        ('pending', 'Pending'),
        ('ready', 'Ready'),
        ('progress', 'In Progress'),
        ('done', 'Finished'),
        ('cancel', 'Cancelled')], string='Status',
        related='workorder_id.state',
        default='pending')
    product_qty = fields.Float(
        'Quantity To Process',
        digits=dp.get_precision('Product Unit of Measure'), required=True)
    product_tracking = fields.Selection(
        'Product Tracking', related='workorder_id.production_id.product_id.tracking',
        help='Technical: used in views only.')
