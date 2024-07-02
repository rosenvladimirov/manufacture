# Copyright 2016-2018 Tecnativa - Pedro M. Baeza
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import odoo.addons.decimal_precision as dp
from odoo import api, models, fields, _

import logging

_logger = logging.getLogger(__name__)


class BomManageVariant(models.TransientModel):
    _name = 'bom.manage.variant'
    _description = "Sale manage variant wizard"

    product_tmpl_id = fields.Many2one(
        comodel_name='product.template',
        string="Component Template", required=True)
    product_attribute_ids = fields.One2many(
        comodel_name='component.bom.configurator.attribute',
        inverse_name='bom_manage_variant_id',
        string='Product Template configurator Attributes')

    show_mrp_attributes = fields.Boolean('Show product attribute', help='Technical field for control on Product '
                                                                        'Template configurator Attributes')
    mrp_product_tmpl_id = fields.Many2one(
        comodel_name='product.template',
        string="Product Template", required=True)
    mrp_product_attribute_ids = fields.One2many(
        comodel_name='template.bom.configurator.attribute',
        inverse_name='bom_manage_variant_id',
        string='Product Template configurator Attributes')

    variant_line_ids = fields.Many2many(
        comodel_name='bom.manage.variant.line',
        string="Variant Lines")
    product_uom_qty = fields.Float(string="Quantity", digits=dp.get_precision('Product UoS'))
    bom_id = fields.Many2one('mrp.bom', 'BOM')
    # bom_line_ids = fields.One2many('mrp.bom.line', 'bom_id', string='BOM lines')
    routing_id = fields.Many2one('mrp.routing', 'Routing')
    operation_id = fields.Many2one('mrp.routing.workcenter', 'Consumed in Operation')

    def _get_product_variant(self, product, static_ids, value_x, value_y):
        """Filter the corresponding product for provided values."""
        self.ensure_one()
        values = self.env['product.attribute.value']
        for value in static_ids.filtered(lambda r: r.value_id):
            values += value.value_id
        for value in static_ids.filtered(lambda r: r.system_all):
            values += product.attribute_line_ids.filtered(lambda r: r.attribute_id == value.attribute_id).mapped(
                'value_ids')

        if value_x:
            values += value_x
        if value_y:
            values += value_y
        # _logger.info("VALUES %s" % values)
        return product.product_variant_ids.filtered(
            lambda x: len(list(set(values.ids).intersection(x.attribute_value_ids.ids))) > 0
        )[:1]
        # return product.product_variant_ids.filtered(
        #     lambda x: not (values - x.attribute_value_ids)
        # )[:1]

    @api.model
    def _get_order_line_values(self, value_x, value_y):
        return {
            'value_x': value_x,
            'value_y': value_y,
        }

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        for record in self:
            template = record.product_tmpl_id

            # _logger.info("VALUES %s" % template.attribute_line_ids)
            if template.attribute_line_ids:
                record.product_attribute_ids = [(6, False, [])]
                values_ids = []

                for val in template.attribute_line_ids:
                    attribute = template.attribute_line_ids.filtered(lambda x: x.attribute_id == val.attribute_id)
                    values_ids.append((0, 0, {
                        'product_tmpl_id': template.id,
                        'attribute_id': val.attribute_id.id,
                        'type_attribute': val.type_attribute,
                        'possible_value_ids': attribute.value_ids.sorted(),
                    }))
                # _logger.info("VALUES COMPONENT %s" % values_ids)
                record.product_attribute_ids = values_ids
            else:
                record.product_attribute_ids = False

    @api.depends('mrp_product_attribute_ids', 'variant_line_ids')
    @api.onchange('product_attribute_ids')
    def _onchange_product_attribute_ids(self):
        for record in self:
            if record.product_tmpl_id and record.mrp_product_tmpl_id:
                for line in record.product_attribute_ids:
                    mrp_product_attribute_ids = record.mrp_product_attribute_ids. \
                        filtered(lambda r: r.attribute_id == line.attribute_id)
                    # _logger.info("mrp_product_attribute_ids COMPARE %s" % len(mrp_product_attribute_ids))
                    if len(mrp_product_attribute_ids) > 0:
                        rebuild = False
                        for mrp_line in mrp_product_attribute_ids:
                            mrp_line.value_id = line.value_id
                            rebuild = True
                            # _logger.info("MRP LINE %s" % mrp_line.value_id)
                        if rebuild:
                            record.variant_line_ids = [(6, 0, [])]
                            lines = record._compute_variant_line_ids()
                            record.variant_line_ids = lines
                # record.show_mrp_attributes = any([x.system_all for x in record.product_attribute_ids])

    @api.depends('variant_line_ids')
    @api.onchange('mrp_product_tmpl_id')
    def _onchange_mrp_product_tmpl_id(self):
        for record in self:
            template = record.mrp_product_tmpl_id

            # _logger.info("VALUES %s" % template.attribute_line_ids)
            if template.attribute_line_ids:
                record.mrp_product_attribute_ids = False
                values_ids = []

                for val in template.attribute_line_ids:
                    attribute = template.attribute_line_ids.filtered(lambda x: x.attribute_id == val.attribute_id)
                    values_ids.append((0, 0, {
                        'product_tmpl_id': template.id,
                        'attribute_id': val.attribute_id.id,
                        'type_attribute': val.type_attribute,
                        'possible_value_ids': attribute.value_ids.sorted(),
                    }))
                # _logger.info("VALUES %s" % values_ids)
                record.mrp_product_attribute_ids = values_ids
            else:
                record.mrp_product_attribute_ids = False
            # record.variant_line_ids = record._compute_variant_line_ids()

    @api.depends('variant_line_ids')
    @api.onchange('mrp_product_attribute_ids')
    def _onchange_mrp_product_attribute_ids(self):
        for record in self:
            # _logger.info("ONCHANGE %s:%s" % (len(record.variant_line_ids), record.mrp_product_tmpl_id))
            if record.mrp_product_tmpl_id:
                record.variant_line_ids = [(6, 0, [])]
                lines = record._compute_variant_line_ids()
                record.variant_line_ids = lines
                # _logger.info("LINES %s(%s)" % (lines, record.variant_line_ids))

    @api.model
    def _compute_variant_line_ids(self):
        template = self.mrp_product_tmpl_id
        mrp_product_attribute_ids = self.mrp_product_attribute_ids
        special_value = self.env.ref('mrp_bom_multi_mgmt.special_for_use_value')
        type_attribute = set(mrp_product_attribute_ids.mapped('type_attribute'))
        num_attrs = len([r for r in type_attribute if r in ['row', 'col']])
        # _logger.info("NUMS %s:%s" % (num_attrs, [x.value_id for x in set(mrp_product_attribute_ids)]))
        if not template or num_attrs not in [1, 2]:
            return

        col = mrp_product_attribute_ids.filtered(lambda r: r.type_attribute == 'col')
        if len(col.ids) > 1:
            col = col[-1]
        if any(x.system_all for x in col):
            # col_values_ids = col.mapped('possible_value_ids')
            col_values_ids = special_value
        elif any(x.value_id for x in col):
            values_ids = col.mapped('value_id')
            col_values_ids = col.mapped('possible_value_ids').filtered(lambda r: r.id in values_ids.ids)
        else:
            col_values_ids = col.mapped('possible_value_ids')
        col = col.mapped('possible_value_ids')

        row = mrp_product_attribute_ids.filtered(lambda r: r.type_attribute == 'row')
        if len(row.ids) > 1:
            row = row[-1]
        if any(x.system_all for x in row):
            # row_values_ids = row.mapped('possible_value_ids')
            row_values_ids = special_value
        elif any(x.value_id for x in row):
            values_ids = row.mapped('value_id')
            row_values_ids = row.mapped('possible_value_ids').filtered(lambda r: r.id in values_ids.ids)
        else:
            row_values_ids = row.mapped('possible_value_ids')
        row = row.mapped('possible_value_ids')

        # _logger.info('ROW:COL %s(%s):%s(%s)' % (row, row_values_ids, col, col_values_ids))
        line_x = col
        line_y = False if num_attrs == 1 else row
        lines = []
        for value_x in line_x:
            for value_y in line_y and line_y or [False]:
                if not value_y:
                    continue
                # _logger.info("SERVE col:row %s in %s:%s in %s" % (value_x, col_values_ids, value_y, row_values_ids))
                product = self._get_product_variant(template, self.mrp_product_attribute_ids, value_x, value_y)
                if not product:
                    continue
                value_x_put = value_x
                value_y_put = value_y

                if col_values_ids != special_value and value_x.id not in col_values_ids.ids:
                    continue
                elif col_values_ids == special_value:
                    value_x_put = special_value

                if row_values_ids != special_value and value_y.id not in row_values_ids.ids:
                    continue
                elif row_values_ids == special_value:
                    value_y_put = special_value

                if value_x_put == special_value == value_y_put:
                    continue
                # _logger.info("USED col:row %s:%s" % (value_x, value_y))
                lines.append((0, 0, self._get_order_line_values(value_x_put, value_y_put)))
        self.show_mrp_attributes = len(lines) == 0
        return lines

    @api.model
    def _get_new_order_line(self, sale_order, product, qty):
        return {
            'product_id': product.id,
            'product_uom': product.uom_id,
            'product_uom_qty': qty,
            'order_id': sale_order.id,
            'name': product.display_name,
        }

    @api.model
    def _get_update_order_line(self, order_line, product, qty):
        return {
            'product_uom_qty': qty,
        }

    @api.model
    def _post_update_transfer(self, total_bom_line_ids):
        pass

    @api.model
    def _get_line_value(self, variant, product_uom_qty, operation_id, attribute_value_ids):
        res = {
            'product_id': variant.id,
            'product_qty': product_uom_qty,
            'product_uom_id': variant.uom_id.id,
            'operation_id': operation_id.id,
        }
        if attribute_value_ids:
            res.update({
                'attribute_value_ids': [(6, False, attribute_value_ids)],
            })
        return res

    @api.multi
    def button_transfer_to_bom(self):
        for record in self:
            values = self.env['product.attribute.value']
            total_bom_line_ids = record.bom_id.bom_line_ids

            # use first by component
            for value in record.product_attribute_ids.filtered(lambda r: not r.system_all):
                values += value.value_id
            for value in record.product_attribute_ids.filtered(lambda r: r.system_all):
                values += value.attribute_id.mapped('value_ids')
            components = record.product_tmpl_id.product_variant_ids. \
                filtered(lambda x: not (values - x.attribute_value_ids))
            _logger.info("START with %s:%s:%s" % (components,
                                                  len(record.product_attribute_ids.mapped('value_id')),
                                                  len(record.product_attribute_ids)))
            # use for single component
            if not components \
                    and len(record.product_attribute_ids.mapped('value_id')) == len(record.product_attribute_ids):
                active_values = record.product_attribute_ids.filtered(lambda r: not r.system_all).mapped('value_id')
                for product in record.product_tmpl_id.product_variant_ids:
                    if not product.attribute_value_ids - active_values:
                        components |= product
                    # _logger.info("PUT NEW COMPONENT %s-%s=%s" % (
                    # product.attribute_value_ids, active_values, product.attribute_value_ids - active_values))
            # count_components = len(components)
            # mrp_product_attribute_ids = record.mrp_product_attribute_ids
            mrp_value_ids = record.mrp_product_tmpl_id.mapped('product_variant_ids').mapped('attribute_value_ids')
            # atr_mrp_product_attribute_ids = mrp_product_attribute_ids.mapped('attribute_id')
            product_uom_qty = record.product_uom_qty
            special_value = self.env.ref('mrp_bom_multi_mgmt.special_for_use_value')
            for variant in components:
                # _logger.info(
                #     "VARIANT %s" % variant)
                variant_line = record.variant_line_ids.filtered(lambda r: r.value_x and r.value_y)
                product_value_ids = variant.attribute_value_ids
                for line in record.variant_line_ids:
                    attribute_x_id = line.value_x.attribute_id
                    value_x_id = line.value_x.id
                    attribute_y_id = line.value_y.attribute_id
                    value_y_id = line.value_y.id
                    if any([x for x in product_value_ids if x.attribute_id == attribute_x_id and x.id != value_x_id]):
                        continue
                    if any([x for x in product_value_ids if x.attribute_id == attribute_y_id and x.id != value_y_id]):
                        continue
                    if line.product_uom_qty != 0.0:
                        mixed = self.env['product.attribute.value']
                        for additional in record.mrp_product_attribute_ids:
                            if additional.attribute_id.id not in (
                                    line.value_x.attribute_id + line.value_y.attribute_id).ids:
                                mixed |= additional.value_id
                        value_x = line.value_x
                        if value_x == special_value:
                            value_x = self.env['product.attribute.value']
                        value_y = line.value_y
                        if value_y == special_value:
                            value_y = self.env['product.attribute.value']
                        bom_line_ids = self.env['mrp.bom.line'].new(self._get_line_value(
                            variant,
                            line.product_uom_qty,
                            record.operation_id,
                            (value_x + value_y + mixed).ids,
                        ))
                        # total_bom_line_ids += bom_line_ids
                        record.bom_id.bom_line_ids += bom_line_ids
                additional = record.mrp_product_attribute_ids.filtered(lambda r: not r.system_all).mapped('value_id')
                # _logger.info("LAST CHECK: COMPONENT -> %s: PRODUCT -> CHECKED ATTRIBUTE %s: ALL ATTRIBUTES %s" %
                #              (product_value_ids, variant_line, additional))
                if not variant_line and not additional:
                    # !!!! try to merge attributes !!!!
                    if any(x in mrp_value_ids.ids for x in product_value_ids.ids):
                        mixed = product_value_ids & mrp_value_ids
                        # _logger.info("USE DIRECT TRANSFER %s" % mixed)
                        if mixed:
                            bom_line_ids = self.env['mrp.bom.line'].new(self._get_line_value(
                                variant,
                                record.product_uom_qty,
                                record.operation_id,
                                mixed.ids))
                            # total_bom_line_ids += bom_line_ids
                            record.bom_id.bom_line_ids += bom_line_ids
                    else:
                        # _logger.info("PARCE %s-%s=%s" % (product_value_ids, mrp_value_ids, product_value_ids-mrp_value_ids))
                        if len(product_value_ids.ids) > 0 \
                                and len(mrp_value_ids.ids) > 0 \
                                and product_value_ids - mrp_value_ids \
                                and product_value_ids != product_value_ids - mrp_value_ids:
                            continue
                        # {
                        #     'product_id': variant.id,
                        #     'product_qty': product_uom_qty,
                        #     'product_uom_id': variant.uom_id.id,
                        #     'operation_id': record.operation_id.id,
                        # }
                        bom_line_ids = self.env['mrp.bom.line'].new(self._get_line_value(
                            variant,
                            product_uom_qty,
                            record.operation_id,
                            False))
                        # total_bom_line_ids += bom_line_ids
                        record.bom_id.bom_line_ids += bom_line_ids
                if not variant_line and additional:
                    # {
                    #     'product_id': variant.id,
                    #     'product_qty': product_uom_qty,
                    #     'product_uom_id': variant.uom_id.id,
                    #     'operation_id': record.operation_id.id,
                    #     'attribute_value_ids': [(6, False, additional.ids)],
                    # }
                    bom_line_ids = self.env['mrp.bom.line'].new(self._get_line_value(
                            variant,
                            product_uom_qty,
                            record.operation_id,
                            additional.ids))
                    # total_bom_line_ids += bom_line_ids
                    record.bom_id.bom_line_ids += bom_line_ids
            # _logger.info('COMPONENT %s:%s:%s' % (component, atributes, exluse))
            record._post_update_transfer(record.bom_id.bom_line_ids - total_bom_line_ids)
        return {'type': 'ir.actions.act_window_close'}


class SaleManageVariantLine(models.TransientModel):
    _name = 'bom.manage.variant.line'

    value_x = fields.Many2one(comodel_name='product.attribute.value')
    value_y = fields.Many2one(comodel_name='product.attribute.value')
    product_uom_qty = fields.Float(
        string="Quantity", digits=dp.get_precision('Product UoS'))
