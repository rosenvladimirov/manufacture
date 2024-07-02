# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _

import logging

_logger = logging.getLogger(__name__)


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    child_bom_line_ids = fields.One2many('mrp.bom.line', string='Semi-product BoM Lines',
                                         compute="_compute_child_bom_line_ids")
    split_bom_line_ids = fields.One2many('mrp.bom.line', string='To split BoM Lines',
                                         compute="_compute_split_bom_line_ids")
    product_brand_id = fields.Many2one('product.brand', string='Brand', related='product_tmpl_id.product_brand_id',
                                       ondelete='restrict',
                                       store=True,
                                       help='Select a brand for this BOM')
    partner_id = fields.Many2one('res.partner', string='Ownet by Partner', ondelete='restrict',
                                 help='Choice it if The BOM will make like subcontractor for this partner')

    @api.multi
    def _compute_child_bom_line_ids(self):
        for record in self:
            record.child_bom_line_ids = self.env['mrp.bom.line'].search(
                [('child_bom_line_id', 'in', record.bom_line_ids.ids)])

    @api.multi
    def _compute_split_bom_line_ids(self):
        for record in self:
            record.split_bom_line_ids = record.bom_line_ids.filtered(lambda r: r.child_product_tmpl_id)

    @api.multi
    def sort_by_operation(self):
        for record in self:
            # _logger.info("SORT BEFORE %s" % record.bom_line_ids)
            if len(record.bom_line_ids.ids) > 0:
                lines = record.bom_line_ids.sorted(lambda r: r.operation_id and r.operation_id.sequence or 999999999)
                for line in lines:
                    if line.operation_id:
                        line.sequence = line.operation_id.sequence
                    else:
                        line.sequence = 999999999
                # _logger.info("SORT AFTER %s" % lines)

    @api.multi
    def split_to_child_product(self):
        for record in self:
            unlink_bom_line = self.env['mrp.bom.line']
            child_product_tmpl_bom = {}
            child_product_tmpl_ids = record.mapped('bom_line_ids').mapped('child_product_tmpl_id')
            for child_product_tmpl in child_product_tmpl_ids:
                bom_lines = child_product_tmpl.mapped('bom_ids').mapped('bom_line_ids'). \
                    filtered(lambda r: r.child_product_tmpl_id == child_product_tmpl)
                if len(bom_lines.ids) > 0:
                    child_product_tmpl_bom[child_product_tmpl] = (bom_lines[0].bom_id, False)
                else:
                    child_product_tmpl_bom[child_product_tmpl] = (False, False)

            for line in record.bom_line_ids.sorted(lambda r: r.sequence):
                if line.child_product_tmpl_id:
                    child_product_tmpl_id = line.child_product_tmpl_id
                    child_product_id = line.child_product_id
                    if not child_product_tmpl_bom[child_product_tmpl_id][0] or child_product_tmpl_bom[
                        child_product_tmpl_id][0].product_id != child_product_id:
                        bom = self.env['mrp.bom'].create({
                            'code': 'From %s' % record.product_tmpl_id.name,
                            'type': 'normal',
                            'product_tmpl_id': child_product_tmpl_id.id,
                            'product_id': child_product_id and child_product_id.id or False,
                            'product_qty': 1.0,
                            'product_uom_id': child_product_tmpl_id.uom_id.id,
                        })
                        child_product_tmpl_bom[child_product_tmpl_id] = (bom, line.operation_id)
                    if child_product_tmpl_bom[child_product_tmpl_id] \
                            and not child_product_tmpl_bom[child_product_tmpl_id][1]:
                        child_product_tmpl_bom[child_product_tmpl_id] = \
                            (child_product_tmpl_bom[child_product_tmpl_id][0], line.operation_id)
                    unlink_bom_line |= line
                    # bom_line = line.copy()
                    bom_line = line._convert_to_write(line._cache)
                    if bom_line.get('id'):
                        del bom_line['id']
                    bom_line.update({
                        'bom_id': child_product_tmpl_bom[child_product_tmpl_id][0].id,
                        # 'child_bom_id': record.id,
                        'child_bom_line_id': line.id,
                        'child_product_tmpl_id': False,
                        'child_product_id': False,
                        'attribute_value_ids': line.attribute_value_ids and [
                            (6, False, line.attribute_value_ids.ids)] or False
                    })
                    res = self.env['mrp.bom.line'].create(bom_line)

            # _logger.info("UNLINK %s" % unlink_bom_line)
            if unlink_bom_line:
                for line in record.bom_line_ids:
                    if line.id in unlink_bom_line.ids:
                        line.unlink()
            if child_product_tmpl_bom:
                lines = self.env['mrp.bom.line']
                for product_tmpl_id, values in child_product_tmpl_bom.items():
                    for product_id in product_tmpl_id.product_variant_ids:
                        line = record.bom_line_ids.new({
                            'bom_id': record.id,
                            'product_id': product_id.id,
                            'product_qty': 1.0,
                            'product_uom_id': product_id.uom_id.id,
                            'routing_id': record.routing_id.id,
                            'operation_id': values[1] and values[1].id,
                        })
                        line.transfer_variants()
                        record.bom_line_ids += line
                        lines |= line
                record.write({})
                # for line in lines:
                #     line.transfer_variants()

    @api.multi
    def merge_back_child_product(self):
        for record in self:
            unlink_bom_line = self.env['mrp.bom.line']
            for line in record.child_bom_line_ids:
                bom = line.bom_id
                # bom_line = line.copy()
                unlink_bom_line |= line
                bom_line = line._convert_to_write(line._cache)
                if bom_line.get('id'):
                    del bom_line['id']
                bom_line.update({
                    'bom_id': record.id,
                    'child_bom_id': False,
                    'child_product_tmpl_id': bom.product_tmpl_id.id,
                    'child_product_id': bom.product_id and bom.product_id.id or False
                })
                self.env['mrp.bom.line'].create(bom_line)


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    child_bom_line_id = fields.Many2one('mrp.bom.line', 'Semi-product Parent BoM')
    child_product_tmpl_id = fields.Many2one(
        'product.template', 'Semi-Product',
        domain="[('type', 'in', ['product', 'consu'])]")
    child_product_id = fields.Many2one(
        'product.product', 'Semi-Product Variant',
        domain="['&', ('product_tmpl_id', '=', product_tmpl_id), ('type', 'in', ['product', 'consu'])]",
        help="If a product variant is defined the BOM is available only for this product.")
    product_tmpl_id = fields.Many2one('product.template', 'Template', related='product_id.product_tmpl_id')
    mrp_multi_bom_id = fields.Many2one('mrp.bom', string='Bill of Material')

    @api.onchange
    def onchange_product_id(self):
        for record in self:
            if not record.child_product_tmpl_id and record.child_product_id:
                record.child_product_tmpl_id = record.child_product_id.product_tmpl_id

    @api.multi
    def transfer_variants(self):
        for record in self:
            product_value_ids = record.product_id.attribute_value_ids
            bom_value_ids = record.bom_id.product_tmpl_id.attribute_line_ids.mapped('attribute_id').mapped('value_ids')

            # _logger.info("TRANSFER %s:%s" % (product_value_ids, bom_value_ids))
            if any(x in bom_value_ids.ids for x in product_value_ids.ids):
                mixed = product_value_ids & bom_value_ids
                record.attribute_value_ids = [(6, False, mixed.ids)]
