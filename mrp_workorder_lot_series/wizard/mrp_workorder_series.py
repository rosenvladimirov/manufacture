# coding: utf-8
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import math
import time

from odoo import models, fields, api, _
from odoo.addons.queue_job.job import job

import logging

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MrpWorkOrderSeries(models.TransientModel):
    _name = 'mrp.workorder.series'
    _description = 'Generate SN/Lot by series in work order'
    # _inherit = ['barcodes.barcode_events_mixin']

    workorder_id = fields.Many2one('mrp.workorder', 'Manufacture Workorder')
    lot_ids = fields.Many2many('stock.production.lot', string='SN/Lots')
    range_start = fields.Char('Range start')
    range_stop = fields.Char('Range stop')
    bulk = fields.Integer('Bulk')
    product_id = fields.Many2one('product.product', 'Manufacture product')
    component_product_id = fields.Many2one('product.product', 'Component product')
    product_package_id = fields.Many2one('product.packaging', 'Product packaging')
    # twin_product_id = fields.Many2one('product.product')
    range_count = fields.Integer('Count lots')
    use_ref = fields.Boolean('Use internal reference')

    @api.model
    def default_get(self, default_fields):
        res = super(MrpWorkOrderSeries, self).default_get(default_fields)
        workorder_id = False

        if res.get('workorder_id', False):
            workorder_id = self.env['mrp.workorder'].browse(res['workorder_id'])
        if not workorder_id:
            workorder_id = self.env['mrp.workorder'].browse(self._context['active_id'])
        if workorder_id:
            if not res.get('use_ref'):
                res['use_ref'] = workorder_id.product_id.use_ref
            res['product_id'] = workorder_id.product_id.id
            parent_product_id = workorder_id.product_id.parent_product_id
            if not parent_product_id and workorder_id.active_move_line_ids.filtered(lambda r: r.work_production):
                res['component_product_id'] = workorder_id.active_move_line_ids.filtered(lambda r: r.work_production)[0].product_id.id
            else:
                res['component_product_id'] = parent_product_id and parent_product_id.id or False
        if res.get('product_id') and not workorder_id:
            parent_product_id = self.env['product.product'].browse(res['product_id']).parent_product_id
            res['component_product_id'] = parent_product_id and parent_product_id.id or False
        return res

    @api.onchange('range_start')
    def _onchange_range_start(self):
        _logger.info("START %s STOP %s (%s)" % (self.range_start, self.range_stop, self.bulk))
        if int(self.range_start) != 0:
            self.range_stop = str(int(self.range_start) + self.bulk).zfill(len(self.range_start))

    @api.onchange('bulk')
    @api.depends('range_stop', 'range_start')
    def _onchange_bulk(self):
        _logger.info("START %s STOP %s (%s)" % (self.range_start, self.range_stop, self.bulk))
        if int(self.range_start) != 0:
            self.range_stop = str(int(self.range_start) + self.bulk)

    @api.onchange('range_stop')
    @api.depends('lot_ids')
    def _onchange_range_stop(self):
        if (self.range_start and self.range_stop) and int(self.range_start) != 0 and int(self.range_stop) != 0:
            self.range_count = len(range(int(self.range_start), int(self.range_stop) + 1))
        # _logger.info("START1 %s STOP1 %s" % (self.range_start, self.range_stop))
        # lot_obj = self.env['stock.production.lot']
        # product_id = self.product_id
        # force_company = self.picking_id.company_id.id
        # if int(self.range_start) != 0 and int(self.range_stop) != 0:
        #     seq_id = self.env['ir.sequence'].search([('code', '=', 'stock.lot.serial'),
        #                                              ('company_id', 'in', [force_company, False])],
        #                                             order='company_id', limit=1)
        #     for item in range(int(self.range_start), int(self.range_stop)+1):
        #         lot_name = seq_id.get_next_char(item)
        #         _logger.info("%s = START %s STOP %s" % (lot_name, self.range_start, self.range_stop))
        #         lot_id = self.env['stock.production.lot'].search([
        #             ('product_id', '=', product_id.id),
        #             ('name', '=', lot_name)
        #         ])
        #         if not lot_id:
        #             lot_id = lot_obj.create({
        #                 'name': lot_name,
        #                 'product_id': product_id.id,
        #                 'product_uom_id': product_id.product_tmpl_id.uom_id.id,
        #             })
        #         self.lot_ids |= lot_id

    @api.multi
    # @job(default_channel="root.auto_fill")
    def action_chunk(self, chunk):
        lot_obj = self.env['stock.production.lot']

        for record in self:
            force_company = self.env.user.company_id.id
            len_lot = len(record.range_start)
            product_id = record.product_id
            base_product_id = record.product_id
            component_product_id = lot_component_lot_id = False
            if record.component_product_id:
                component_product_id = record.component_product_id
            seq_id = self.env['ir.sequence'].search([('code', '=', 'stock.lot.serial'),
                                                     ('company_id', 'in', [force_company, False])],
                                                    order='company_id', limit=1)
            for item in chunk:
                if record.use_ref:
                    lot_id = self.env['stock.production.lot'].search([
                        ('product_id', '=', product_id.id),
                        ('ref', '=', str(item).zfill(len_lot))
                    ])
                    if not lot_id and component_product_id:
                        lot_component_lot_id = self.env['stock.production.lot'].search([
                            ('product_id', '=', component_product_id.id),
                            ('ref', '=', str(item).zfill(len_lot))
                        ])

                    if not lot_id and lot_component_lot_id:
                        next_lot = lot_obj.default_get(['name'])
                        next_lot.update({
                            'ref': str(item).zfill(len_lot),
                            'name': lot_component_lot_id.name,
                            'product_id': base_product_id.id,
                            'product_uom_id': base_product_id.product_tmpl_id.uom_id.id
                        })
                        lot_id = lot_obj.create(next_lot)
                    elif not lot_id and not lot_component_lot_id:
                        next_lot = lot_obj.default_get(['name'])
                        next_lot.update({
                            'ref': str(item).zfill(len_lot),
                            'product_id': base_product_id.id,
                            'product_uom_id': base_product_id.product_tmpl_id.uom_id.id
                        })
                        lot_id = lot_obj.create(next_lot)

                else:
                    lot_name = seq_id.get_next_char(item)
                    _logger.info("%s = START %s STOP %s" % (lot_name, record.range_start, record.range_stop))
                    lot_id = self.env['stock.production.lot'].search([
                        ('product_id', '=', product_id.id),
                        ('name', '=', str(lot_name).zfill(len_lot))
                    ])
                    if not lot_id:
                        lot_id = lot_obj.create({
                            'name': str(lot_name).zfill(len_lot),
                            'product_id': base_product_id.id,
                            'product_uom_id': base_product_id.product_tmpl_id.uom_id.id,
                        })
                self.lot_ids |= lot_id

    @api.multi
    def generate_lots(self):
        chunk_size = 5
        for record in self:
            if (record.range_start and record.range_stop) and int(record.range_start) != 0 and int(record.range_stop) != 0:
                total_range = list(range(int(record.range_start), int(record.range_stop) + 1))
                count_total = len(total_range)
                chunks = [total_range[i * chunk_size:(i + 1) * chunk_size] for i in range(math.ceil(len(total_range) / chunk_size))]
                for chunk in chunks:
                    record.action_chunk(chunk)
                # while len(record.lot_ids) <= count_total:
                #     time.sleep(5)

        return {
            'type': 'ir.actions.do_nothing'
        }


    @api.multi
    def generate_series(self):
        self.ensure_one()
        if self._context.get('active_model') == 'mrp.workorder' and self._context.get('active_ids'):
            workorder = self.env['mrp.workorder'].browse(self._context['active_ids'])
        else:
            workorder = self.workorder_id

        if workorder and workorder.product_tracking:
            if workorder.working_state != 'blocked':
                lot_obj = self.env['stock.production.lot']

                for lot_id in self.lot_ids:
                    workorder.qty_producing = 1.0
                    workorder.button_empty_bins()
                    # if self.twin_product_id:
                    #     twin_lot_id = self.env['stock.production.lot'].search([
                    #         ('product_id', '=', self.twin_product_id.id),
                    #         ('name', '=', lot_id.name)
                    #     ])
                    #     if not twin_lot_id:
                    #         twin_lot_id = lot_obj.create({
                    #             'name': lot_id.name,
                    #             'product_id': self.twin_product_id.id,
                    #             'product_uom_id': self.twin_product_id.product_tmpl_id.uom_id.id,
                    #         })
                    #     for line in workorder.active_move_line_ids.filtered(lambda r: r.product_id == self.product_id):
                    #         line.lot_id = twin_lot_id
                    workorder.button_start()
                    if workorder.product_tracking:
                        workorder.on_barcode_scanned(lot_id.name)
                    _logger.info(
                        _('Put for produce %s in work order %s' % (workorder.qty_producing, workorder.name)))
                    try:
                        workorder.record_production()
                    except ValueError:
                        _logger.info(_('Error when validate work order'))
            else:
                raise UserError(_('The work order %s in state %s') %
                                (workorder.name, workorder.working_state))
        else:
            return {'type': 'ir.actions.act_window_close'}
