# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import api, fields, models, exceptions, _
from odoo.tools import float_compare
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    _logger.warning('requests is not available in the sys path')


class MrpImportImperium(models.TransientModel):
    _name = 'mrp.import.imperium'
    _inherit = "barcodes.barcode_events_mixin"

    production_id = fields.Many2one('mrp.production', 'Manufacturing Order')
    workorder_id = fields.Many2one('mrp.workorder', 'Work order')
    pack_size = fields.Integer("Pack Size", help="Production Pack Size")
    process_order_number = fields.Char('Production Number', help='This number be come from imported data')
    batch_number = fields.Char('Lot/SN', help='This LOT/SN be come from imported data. '
                                              'Batch number in odoo database production is Lot/SN.')
    formula_number = fields.Char('Formula', help='The formula_number is come from import batch production')
    produced_qty = fields.Float('Produced quantity', help='The produced quantity come from imported data')

    server_url = fields.Char('URL', default=lambda self: self.env.user.company_id.imperium_server_url)
    date = fields.Date('From date', default=lambda self: fields.Date.today())
    company_id = fields.Many2one('res.company', 'Company',
                                 default=lambda self: self.env['res.company']._company_default_get('mrp.production'))

    import_lines = fields.One2many('mrp.import.imperium.line', 'wiz_id', string='Lines')

    def on_barcode_scanned(self, barcode):
        workorder = self.env['mrp.workorder'].search(['|',
                                                ('product_id.name', '=', barcode),
                                                ('name', 'ilike', barcode),
                                                ], limit=1)
        if workorder:
            self.workorder_id = workorder.id
            return
        message = "A product with a barcode %s sent from a production order is not found in the repair orders."
        return {'warning': {
            'title': _("I can't find the product to repair"),
            'message': message % {
                'barcode': barcode}
        }}

    @api.multi
    def action_import_imperium(self):
        for record in self:
            date = fields.Date.from_string(record.date).strftime('%Y-%m-%d')
            get_batches_list_url = record.server_url + "/imperiumweb1/ImperiumSVC/DataManagerConfigWEB.svc/Batches_GetList?_dc=1626703411238&Status=COMPLETED&DatabaseName=&strXML=%3Croot%3E%3CSelectBy%3Ebatchnumber%3C%2FSelectBy%3E%3CBatchNumber%3E%3C%2FBatchNumber%3E%3CBatchStarting%3E" + date + "T00%3A00%3A00%3C%2FBatchStarting%3E%3CMixerLine%3E%3C%2FMixerLine%3E%3C%2Froot%3E"
            r = requests.get(get_batches_list_url)
            sequence = self.env['ir.sequence'].search(
                [('code', '=', 'mrp.production'), ('company_id', 'in', [record.company_id.id, False])],
                order='company_id', limit=1)
            batch_list = r.json()['List']
            for line in batch_list:
                prefix = sequence.prefix or ''
                suffix = sequence.suffix or ''
                momp = "9999" + record.production_id.name.replace(prefix, '').replace(suffix, '')
                record.process_order_number = line.get('ProcessOrderNumber', False)
                record.batch_number = line.get('BatchNumber', False)

                _logger.info("Batch Number %s momp %s for %s" % (record.batch_number, momp, record.process_order_number))
                if record.process_order_number == momp and record.batch_number:
                    batch_get_header_url = record.server_url + '/imperiumweb1/ImperiumSVC/DataManagerConfigWEB.svc/Batch_GetHeader?_dc=1614773071192&Status=COMPLETED&DatabaseName=&intBatchNumber=' + record.batch_number
                    _logger.info("batch_get_header_url: %s" % batch_get_header_url)
                    batch_header = requests.get(batch_get_header_url).json()['HeadExtra'][0]
                    formula_number = batch_header.get('FormulationNumber', False)
                    batch_target = batch_header.get('BatchTarget', False)
                    record.pack_size = batch_header.get('PackSize', False)
                    record.formula_number = formula_number
                    record.produced_qty = float(batch_target)

                    if formula_number and record.production_id.bom_id.code and \
                            not record.production_id.bom_id.code == formula_number:
                        raise UserError(_('You are trying to import production with the wrong formula: %s') % formula_number)
                    if not float_compare(record.production_id.product_qty, float(batch_target),
                                     precision_rounding=record.production_id.product_id.uom_id.rounding) == 0:
                        raise UserError(_('You are trying to import production, but we find a difference between'
                                          ' the set quantity %s and the production %s result is %s')
                                        % (record.production_id.product_qty, float(batch_target),
                                           float_compare(record.production_id.product_qty, float(batch_target),
                                                         precision_rounding=record.production_id.product_id.uom_id.rounding)))
                    get_batch_detail_url = record.server_url + '/imperiumweb1/ImperiumSVC/DataManagerConfigWEB.svc/Batch_GetDetailsList?_dc=1614773072471&Status=COMPLETED&DatabaseName=&intBatchNumber=' + record.batch_number
                    rms = requests.get(get_batch_detail_url).json()
                    for rm_line in rms:
                        # Махаме бътовете
                        if rm_line['MaterialNumber'] == '9999':
                            rms.remove(rm_line)
                            continue

                        # print("RM: %s, %s %s" %(RM['MaterialNumber'], RM['MaterialRMBN'], RM['MaterialActual'] ))
                        if rm_line['MaterialRMBN'] == 'BN230000000503':
                            rm_line['MaterialRMBN'] = 'BN23000000503'
                        if rm_line['MaterialRMBN'] == 'UE0210518':
                            rm_line['MaterialRMBN'] = 'UE02101518'
                        if rm_line['MaterialNumber'] == 'CN732A0225':
                            rm_line['MaterialNumber'] == 'CN732A0125'  # Сбъркан продуктов код 28.06.2021 Партида 4700
                        # Check available product and sub product i database very stupid logic from datastore imperium
                        product_id = self.env['product.product'].search(
                            [('default_code', '=', rm_line['MaterialNumber'])])
                        sub_product_id = self.env['product.product'].search(
                            [('default_code', '=', rm_line['SubMaterialNumber'])])

                        if not product_id:
                            raise UserError(_('We find the wrong reference number in the production. '
                                              'Please add this number %s s or fix it.' % rm_line['MaterialNumber']))
                        # Check lot for this product in database
                        lot_id = self.env['stock.production.lot'].search([('product_id', '=', product_id.id),
                                                                          "|",
                                                                          ('name', '=', rm_line['MaterialRMBN']),
                                                                          ('ref', '=', rm_line['MaterialRMBN'])])
                        # if do not found lot we is check again in subproduct
                        if not lot_id:
                            lot_id = self.env['stock.production.lot'].search([('product_id', '=', sub_product_id.id),
                                                                              "|",
                                                                              ('name', '=', rm_line['MaterialRMBN']),
                                                                              ('ref', '=', rm_line['MaterialRMBN'])])
                        if not lot_id:
                            raise UserError(_('You are trying to use a LOT/SN (%s) '
                                              'that you did not receive in the warehouse' % rm_line['MaterialRMBN']))
                        record.import_lines += self.env['mrp.import.imperium.line'].new({
                            'product_id': product_id.id,
                            'lot_id': lot_id.id,
                            'material_actual': rm_line['MaterialActual'],
                            'uom_id': self.env.ref('product.product_uom_kgm').id,
                            'wiz_id': record.id,
                        })
                        _logger.info("Line added with %s Count: %s wiz_id %s" % (product_id.name, lot_id.name, record.import_lines))
        return {"type": "ir.actions.do_nothing"}

    @api.multi
    def action_fill_workorder(self):
        for record in self:
            track_active_move_line_ids = []
            quant = self.env['stock.quant']
            source_location = record.production_id.location_src_id

            precision_digits = self.env[
                'decimal.precision'].precision_get('Product Unit of Measure')

            workorder = record.workorder_id
            final_lot_id = self.env['stock.production.lot'].search([('product_id', '=', record.production_id.product_id.id),
                                                              "|",
                                                              ('name', '=', record.batch_number),
                                                              ('ref', '=', record.batch_number)])
            if len(final_lot_id) > 0:
                raise UserError(_("Ready product LOT exists %s") % final_lot_id[0].name)
            else:
                final_lot_id = self.env['stock.production.lot'].create({
                    "name": record.batch_number,
                    "product_id": record.production_id.product_id.id,
                    "ref": record.batch_number,
                    "gs1": "10" + str(record.batch_number),
                    "lot_certificate": False,
                    "lot_labels": False,
                    "lot_external_problems": False,
                    "lot_pack_size": record.pack_size,
                    "tracking": "lot",
                    "range_start": 0,
                    "range_qty": 0
                })
            if workorder:
                workorder.final_lot_id = final_lot_id

                _logger.info("Work order %s -> %s LOT: %s active ids %s" %
                             (workorder, workorder.production_id, final_lot_id, len(workorder.active_move_line_ids)))

                routing = record.production_id.routing_id
                if routing and routing.location_id:
                    source_location = routing.location_id

                move_line_tobe_delete = workorder.move_raw_ids.filtered(lambda r: not r.bom_line_id.block_clear_qty).mapped('move_line_ids')
                if move_line_tobe_delete:
                    _logger.info('Lines to be delete %s' % move_line_tobe_delete)
                    move_line_tobe_delete.unlink()

                for line in record.import_lines:
                    qty = line.material_actual
                    product = line.product_id
                    if product.type not in ['product', 'consu']:
                        continue
                    # we assure that we set on first empty move_line qty
                    lines_product_ids = workorder.active_move_line_ids.filtered(
                        lambda r: r.product_id.id == product.id and not r.lot_id)
                    lines_lot_ids = workorder.active_move_line_ids.filtered(
                        lambda r: r.product_id.id == product.id and r.lot_id.id == line.lot_id.id)
                    move_raw_move = workorder.move_raw_ids.filtered(lambda r: r.product_id.id == product.id)
                    # if move_raw_move:
                    #     move_raw_move.production_id = False # Force remove

                    _logger.info("RAW %s Product %s:%s %s CHECK: no lot:%s lot:%s move %s" % (move_raw_move, product.default_code, lines_product_ids.product_id.default_code, line.lot_id.name, lines_product_ids.ids, lines_lot_ids.ids, lines_lot_ids.mapped('move_id')))

                    # if if we have an match between batch report and bom lines with empty lot_id
                    if len(lines_lot_ids.ids) >= 1:
                        track_active_move_line_ids += lines_lot_ids.ids
                        _logger.info("Existing Move Line fit lot: %s %s %s" % (product.default_code, lines_product_ids.product_id.default_code, line.lot_id.name))
                        for lot in lines_lot_ids:
                            if not move_raw_move:
                                move_raw_move = workorder._pre_record_production(lot)
                                workorder.move_raw_ids += move_raw_move
                            value = {
                                'qty_done': lot.qty_done + qty,
                                'product_uom_id': line.uom_id.id,
                            }
                            if not lot.move_id:
                                value.update({
                                    'move_id': move_raw_move.id
                                })
                            available_quantity = quant._get_available_quantity(
                                product, lot.location_id, lot_id=line.lot_id,
                                package_id=lot.package_id,
                                owner_id=lot.owner_id,
                            )
                            if float_compare(available_quantity, 0.0, precision_digits=precision_digits) <= 0:
                                continue
                            move_raw_move._update_reserved_quantity(
                                qty, available_quantity, lot.location_id,
                                lot_id=line.lot_id, package_id=lot.package_id,
                                owner_id=lot.owner_id,
                                strict=True
                            )
                            lot.write(value)
                            # move_raw_move.quantity_done += qty
                            # if not lot.move_id:
                            #     workorder._update_production_datails(lot)
                            # if lot.move_id and len(lot.move_id._get_move_lines().ids) < 2:
                            #     lot.move_id.quantity_done += qty
                            # else:
                            #     lot.move_id._set_quantity_done(lot.move_id.quantity_done + qty)

                    if len(lines_product_ids.ids) >= 1:
                        track_active_move_line_ids += lines_product_ids.ids
                        _logger.info("Existing Move Line without lot: %s %s %s" % (product.default_code, lines_product_ids.product_id.default_code, line.lot_id.name))
                        for product_line in lines_product_ids:
                            if not move_raw_move:
                                move_raw_move = workorder._pre_record_production(product_line)
                                workorder.move_raw_ids += move_raw_move
                            value = {
                                'lot_id': line.lot_id.id,
                                'qty_done': qty,
                                'product_uom_id': line.uom_id.id,
                            }
                            if not product_line.move_id:
                                value.update({
                                    'move_id': move_raw_move.id
                                })
                            available_quantity = quant._get_available_quantity(
                                product, product_line.location_id, lot_id=line.lot_id,
                                package_id=product_line.package_id,
                                owner_id=product_line.owner_id,
                            )
                            if float_compare(available_quantity, 0.0, precision_digits=precision_digits) <= 0:
                                continue
                            move_raw_move._update_reserved_quantity(
                                qty, available_quantity, product_line.location_id,
                                lot_id=line.lot_id, package_id=product_line.package_id,
                                owner_id=product_line.owner_id,
                                strict=True
                            )
                            product_line.write(value)
                            # move_raw_move.quantity_done += qty
                            # if not product_line.move_id:
                            #     workorder._update_production_datails(product_line)
                            # if product_line.move_id and len(product_line.move_id._get_move_lines().ids) < 2:
                            #     product_line.move_id.quantity_done += qty
                            # else:
                            #     product_line.move_id._set_quantity_done(product_line.move_id.quantity_done + qty)
                            # product_line.move_id.quantity_done += qty
                    if len(lines_product_ids.ids) == 0 and len(lines_lot_ids.ids) == 0:
                        # create move_line no match between BOM and batch report
                        _logger.info("Not Existing Move Line: %s %s %s" % (product.default_code, lines_product_ids.product_id.default_code, line.lot_id.name))
                        stock_move_line = workorder.active_move_line_ids.new({
                            'product_id': product.id,
                            'product_uom_id': line.uom_id.id,
                            'location_id': source_location and source_location.id or record.production_id.location_src_id.id,
                            'location_dest_id': record.production_id.location_dest_id.id,
                            'qty_done': qty or 0.0,
                            'product_uom_qty': line.lot_id and qty or 0.0,
                            'date': fields.datetime.now(),
                            'lot_id': line.lot_id and line.lot_id.id,
                            'split_lot_id': line.lot_id and line.lot_id.id,
                            'workorder_id': workorder.id,
                            'done_wo': False,
                            'move_id': move_raw_move and move_raw_move.id,
                        })
                        workorder.active_move_line_ids += stock_move_line
                        if not move_raw_move:
                            move_raw_move = workorder._pre_record_production(stock_move_line)
                        available_quantity = quant._get_available_quantity(
                            product, source_location, lot_id=line.lot_id,
                            package_id=False,
                            owner_id=False,
                        )
                        if float_compare(available_quantity, 0.0, precision_digits=precision_digits) <= 0:
                            continue
                        move_raw_move._update_reserved_quantity(
                            qty, available_quantity, source_location,
                            lot_id=line.lot_id, package_id=False,
                            owner_id=False,
                            strict=True
                        )
                        # move_raw_move.production_id = False
                        # move_raw_move.quantity_done += qty
                        # workorder.move_raw_ids += move_raw_move
                        # if update_values:
                        #     workorder.move_raw_ids += update_values
                        _logger.info("Pre Record: %s:%s=>%s" % (workorder, move_raw_move, stock_move_line))


class MrpImportImperiumLine(models.TransientModel):
    _name = 'mrp.import.imperium.line'

    wiz_id = fields.Many2one('mrp.import.imperium', 'Wizard')

    product_id = fields.Many2one('product.product', 'Materials')
    lot_id = fields.Many2one('stock.production.lot', 'Lot/SN')
    material_actual = fields.Float('Consumed quantity')
    uom_id = fields.Many2one('product.uom', 'uom')
    # move_line.product_uom_id._compute_quantity(move_line.qty_done,move_line.product_id.uom_id)
