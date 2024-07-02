# -*- coding: utf-8 -*-
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import api, models, fields, _
from odoo.addons.mrp.models.mrp_bom import MrpBom as mrp_bom
from odoo.addons.mrp.models.mrp_bom import MrpBomLine as mrp_bom_line

from odoo.exceptions import UserError
from odoo.tools import float_round, float_compare

import logging

_logger = logging.getLogger(__name__)


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    bom_line_ids = fields.Many2one('mrp.bom', string='Bom')

    @api.model
    def _bom_find(self, product_tmpl=None, product=None, picking_type=None, company_id=False):
        """ Finds BoM for particular product, picking and company """
        if product:
            if not product_tmpl:
                product_tmpl = product.product_tmpl_id
            domain = ['|', ('product_id', '=', product.id), '&', ('product_id', '=', False),
                      ('product_tmpl_id', '=', product_tmpl.id)]
        elif product_tmpl:
            domain = [('product_tmpl_id', '=', product_tmpl.id)]
        else:
            # neither product nor template, makes no sense to search
            return False
        if picking_type:
            domain += ['|', ('picking_type_id', '=', picking_type.id), ('picking_type_id', '=', False)]
        if company_id or self.env.context.get('company_id'):
            domain = domain + [('company_id', '=', company_id or self.env.context.get('company_id'))]
        # order to prioritize bom with product_id over the one without
        return self.search(domain, order='sequence DESC, product_id', limit=1)

    def explode(self, product, quantity, picking_type=False):
        """
            Explodes the BoM and creates two lists with all the information you need: bom_done and line_done
            Quantity describes the number of times you need the BoM: so the quantity divided by the number created by the BoM
            and converted into its UoM
        """
        from collections import defaultdict

        graph = defaultdict(list)
        V = set()

        def check_cycle(v, visited, recStack, graph):
            visited[v] = True
            recStack[v] = True
            for neighbour in graph[v]:
                if visited[neighbour] == False:
                    if check_cycle(neighbour, visited, recStack, graph) == True:
                        return True
                elif recStack[neighbour] == True:
                    return True
            recStack[v] = False
            return False

        manufacture_route = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
        boms_done = [(self, {'qty': quantity, 'product': product, 'original_qty': quantity, 'parent_line': False})]
        lines_done = []
        V |= set([product.product_tmpl_id.id])

        bom_lines = [(bom_line, product, quantity, False) for bom_line in self.bom_line_ids]
        master_product = product
        # master_attributes = product.attribute_value_ids
        for bom_line in self.bom_line_ids:
            V |= set([bom_line.product_id.product_tmpl_id.id])
            graph[product.product_tmpl_id.id].append(bom_line.product_id.product_tmpl_id.id)
        while bom_lines:
            current_line, current_product, current_qty, parent_line = bom_lines[0]
            bom_lines = bom_lines[1:]
            variant_product = \
                (current_line.use_master and current_line.type == 'phantom') and master_product or current_product
            if current_line._skip_bom_line(variant_product):
                if current_line.use_master:
                    raise UserError(_(
                        'No match on parent master and child variant!  No match attributes %s!') % (
                                        tuple([x.name for x in variant_product.attribute_value_ids]),))
                continue
            line_quantity = current_qty * current_line.product_qty_real
            line_quantity_real = current_qty * current_line.product_qty
            bom_product = current_line.product_id
            if current_line.use_master and current_line.type != 'phantom' and current_line.product_id.is_product_variant:
                for child_product in current_line.product_id.product_tmpl_id.product_variant_ids:
                    if not master_product.attribute_value_ids - child_product.attribute_value_ids:
                        master_product = bom_product = child_product
                        current_line.product_id = child_product
                        break

            _logger.info("BOM LINE %s=>%s" % (variant_product.display_name, bom_product.display_name))
            bom_picking_type = self.picking_type_id
            if current_line.block_fallow or self._context.get('block_fallow', False):
                bom_picking_type = False
                picking_type = False

            if manufacture_route in bom_product.route_ids and len(bom_product.bom_ids.ids) > 0:
                # if len(bom_product.bom_ids.ids) == 0:
                #     raise UserError(_('The manufacturing product %s is not have The any BOM\'s') % bom_product.display_name)
                force_phantom = self._context.get('force_phantom', False)
            else:
                force_phantom = False

            bom = self._bom_find(product=bom_product, picking_type=picking_type or bom_picking_type,
                                 company_id=self.company_id.id)
            if bom.type == 'phantom' or current_line.type == 'phantom' or force_phantom:
                product_qty = bom.product_qty == 0.0 and 1.0 or bom.product_qty
                converted_line_quantity = current_line.product_uom_id._compute_quantity(line_quantity / product_qty,
                                                                                        bom.product_uom_id)
                bom_lines = [(line, bom_product, converted_line_quantity, current_line) for line in
                             bom.bom_line_ids] + bom_lines
                for bom_line in bom.bom_line_ids:
                    graph[bom_product.product_tmpl_id.id].append(bom_line.product_id.product_tmpl_id.id)
                    if bom_line.product_id.product_tmpl_id.id in V and check_cycle(
                            bom_line.product_id.product_tmpl_id.id, {key: False for key in V},
                            {key: False for key in V}, graph):
                        raise UserError(_(
                            'Recursion error!  A product with a Bill of Material should not have itself in its BoM or child BoMs!'))
                    V |= set([bom_line.product_id.product_tmpl_id.id])
                boms_done.append((bom,
                                  {'qty': converted_line_quantity, 'product': bom_product, 'original_qty': quantity,
                                   'parent_line': current_line}))
            else:
                # We round up here because the user expects that if he has to consume a little more, the whole UOM unit
                # should be consumed.
                rounding = current_line.product_uom_id.rounding
                line_quantity = float_round(line_quantity, precision_rounding=rounding, rounding_method='UP')
                line_quantity_real = float_round(line_quantity_real, precision_rounding=rounding, rounding_method='UP')
                lines_done.append((current_line,
                                   {'qty': line_quantity, 'qty_real': line_quantity_real, 'product': bom_product,
                                    'original_qty': quantity, 'parent_line': parent_line}))

        return boms_done, lines_done


mrp_bom.explode = MrpBom.explode
mrp_bom._bom_find = MrpBom._bom_find


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    def _message_get(self, bom_lines, values):
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        msg = ""
        for inx, line in enumerate(bom_lines):
            if 'product_qty' in values \
                    and float_compare(line.product_qty, values['product_qty'], precision_digits=precision) != 0:
                msg += "<b>The bom line quantity has been updated.</b><ul>"
                msg += "<li> %s: " % (line.product_id.display_name,)
                msg += _("Quantity") + ": %s -> %s </li>" % (line.product_qty, float(values['product_qty']),)
                msg += "</ul>"
                msg += inx + 1 < len(bom_lines) > 1 and "<br/>" or ""
            if 'product_id' in values and line.product_id.id != values['product_id']:
                msg += "<b>The bom line product has been updated.</b><ul>"
                product_id = self.env['product.product'].browse(values['product_id'])
                msg += "<li>"
                msg += _("Product") + ": %s -> %s </li>" % (line.product_id.display_name, product_id.display_name,)
                msg += "</ul>"
                msg += inx + 1 < len(bom_lines) and "<br/>" or ""
            if 'attribute_value_ids' in values and len(values['attribute_value_ids']) > 0:
                msg += "<b>The bom line attribute variant has been updated.</b><ul>"
                attribute_value_ids = self.env['product.attribute.value'].browse(values['attribute_value_ids'][0][2])
                attribute_value_ids = attribute_value_ids.mapped('display_name')
                attribute_value_ids = attribute_value_ids and ';'.join(attribute_value_ids) or ''
                old_attribute_value_ids = line.attribute_value_ids.mapped('display_name')
                old_attribute_value_ids = old_attribute_value_ids and ';'.join(old_attribute_value_ids) or ''
                msg += "<li> %s: " % (line.product_id.display_name,)
                msg += _("Attributes") + ": %s -> %s </li>" % (old_attribute_value_ids, attribute_value_ids,)
                msg += "</ul>"
                msg += inx + 1 < len(bom_lines) and "<br/>" or ""
        return msg

    def _update_line(self, values):
        boms = self.mapped('bom_id')
        for bom in boms:
            bom_lines = self.filtered(lambda x: x.bom_id == bom)
            msg = self._message_get(bom_lines, values)
            if msg:
                bom.message_post(body=msg)

    @api.multi
    def write(self, values):
        for record in self:
            if values.get('product_qty', False) or values.get('product_id', False):
                record.filtered(
                    lambda r: r.product_id)._update_line(values)
        return super(MrpBomLine, self).write(values)

    @api.multi
    @api.depends('loss', 'product_qty')
    def _compute_product_qty_real(self):
        for rec in self:
            rec.product_qty_real = rec.product_qty * (1 + rec.loss / 100)

    loss = fields.Float("Enter The losses by %", help="Please enter the losses by percentage")
    product_qty_real = fields.Float(string="Re-calqulated Qty", compute=_compute_product_qty_real)
    type = fields.Selection([
        ('normal', 'Manufacture this product'),
        ('phantom', 'Kit')], 'BoM Type',
        default='normal')
    use_master = fields.Boolean("Use master")
    block_fallow = fields.Boolean("Block follow operation type")

    @api.one
    @api.depends('product_id', 'bom_id')
    def _compute_child_bom_id(self):
        if not self.product_id:
            self.child_bom_id = False
        else:
            bom_picking_type = self.bom_id.picking_type_id
            if self.block_fallow or self._context.get('block_fallow', False):
                bom_picking_type = False
            self.child_bom_id = self.env['mrp.bom']._bom_find(
                product_tmpl=self.product_id.product_tmpl_id,
                product=self.product_id,
                picking_type=bom_picking_type)


mrp_bom_line._compute_child_bom_id = MrpBomLine._compute_child_bom_id
