# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class MrpSemiProductComponent(models.TransientModel):
    _name = "mrp.semi.product.component"
    _description = "Semi product on bom lines"

    product_tmpl_id = fields.Many2one('product.template', 'Product template')
    product_id = fields.Many2one('product.product', 'Product')
    operation_ids = fields.Many2many('mrp.routing.workcenter', string='Operations')
    bom_id = fields.Many2one('mrp.bom', 'Bom')
    auto_split = fields.Boolean('Auto split after')
    help_split = fields.Boolean('Help for semi-products', help='The wizard is help you to make semi-products')
    variant_line_ids = fields.Many2many(comodel_name='mrp.semi.product.component.line', string="Operation Lines")

    @api.model
    def default_get(self, fields_list):
        res = super(MrpSemiProductComponent, self).default_get(fields_list)
        _logger.info("default_get %s" % res)
        if res.get('bom_id'):
            bom = self.env['mrp.bom'].browse([res['bom_id']])
            product_tmpl_id = bom.product_tmpl_id
            operation_ids = bom.routing_id.mapped('operation_ids')
            variant_ids = product_tmpl_id.mapped('attribute_line_ids').mapped('attribute_id')
            operations = []
            for operation in operation_ids.sorted(lambda r: r.sequence):
                for attribute in variant_ids.sorted(lambda r: r.sequence):
                    operations.append((0, False, {'value_x': operation.id, 'value_y': attribute.id, 'used': 0}))
            res.update({
                'variant_line_ids': operations,
            })
            _logger.info("RES %s" % res)
        return res

    def _populate_semi_products(self, boms, operation_ids):
        for record in self:
            if len(operation_ids.ids) > 0:
                for bom in boms:
                    for line in bom.bom_line_ids:
                        if line.operation_id.id in operation_ids.ids:
                            if record.product_tmpl_id:
                                line.child_product_tmpl_id = record.product_tmpl_id
                                if record.product_id:
                                    line.child_product_id = record.product_id
                    if record.auto_split:
                        bom.split_to_child_product()

    @api.multi
    def populate_semi_products(self):
        for record in self:
            boms = record.bom_id
            operation_ids = record.operation_ids
            if not boms and self._context.get('active_ids') and self._context.get('active_model', False) == 'mrp.bom':
                boms = self.env['mrp.bom'].browse(self._context['active_ids'])
            if record.help_split:
                mrp_product_tmpl_id = boms.product_tmpl_id
                operation_ids = record.variant_line_ids.mapped('value_x')
                attribute_line_ids = {}
                for line in record.variant_line_ids.sorted(lambda r: r.value_x.sequence, reverse=True):
                    if line.used > 0:
                        if not attribute_line_ids.get(line.value_x):
                            attribute_line_ids[line.value_x] = {}
                        if not attribute_line_ids[line.value_x].get(line.value_y):
                            attribute_line_ids[line.value_x][line.value_y] = set([])
                        attribute_line_ids[line.value_x][line.value_y].update(mrp_product_tmpl_id.
                                                                              mapped('attribute_line_ids').
                                                                              mapped('value_ids').
                                                                              filtered(lambda r: r.attribute_id == line.value_y).ids)
                for idx, operation in attribute_line_ids.items():
                    key = operation_ids.ids.index(idx.id)
                    default = {
                        'name': '%s-%s (%s)' % (operation_ids[key].name, mrp_product_tmpl_id.name, boms.code),
                        'allow_merge': True,
                        'attribute_line_ids': [(0, False, {'attribute_id': key.id, 'value_ids': [(6, False, list(value))]})
                                               for key, value in operation.items()],
                    }
                    _logger.info("DEFAULT %s" % default)
                    record.product_tmpl_id = mrp_product_tmpl_id.copy(default)
                    record._populate_semi_products(boms, operation_ids[:key+1])
                    boms = self.env['mrp.bom'].with_context(force_company=boms.company_id.id).\
                        _bom_find(product_tmpl=record.product_tmpl_id,
                                  picking_type=boms.picking_type_id,
                                  company_id=boms.company_id.id)
                    _logger.info("LINE %s:%s" % (operation_ids[:key+1], boms))
            else:
                record._populate_semi_products(boms, operation_ids)
            return {'type': 'ir.actions.act_window_close'}


class MrpSemiProductComponentLine(models.TransientModel):
    _name = 'mrp.semi.product.component.line'

    value_x = fields.Many2one(comodel_name='mrp.routing.workcenter')
    value_y = fields.Many2one(comodel_name='product.attribute')
    used = fields.Integer('Used in operation')
