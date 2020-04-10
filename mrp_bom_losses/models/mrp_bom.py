# -*- coding: utf-8 -*-
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import api, models, fields, _
from odoo.addons.mrp.models.mrp_bom import MrpBom as mrp_bom_explode
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round

import logging
_logger = logging.getLogger(__name__)


class MrpBom(models.Model):
    _inherit = 'mrp.bom.line'

    @api.multi
    @api.depends('loss', 'product_qty')
    def _compute_product_qty_real(self):
        for rec in self:
            rec.product_qty_real = rec.product_qty*(1+rec.loss/100)

    loss = fields.Float("Enter The losses by %", help="Please enter the losses by percentage")
    product_qty_real = fields.Float(string="Re-calqulated Qty", compute=_compute_product_qty_real)
    type = fields.Selection([
        ('normal', 'Manufacture this product'),
        ('phantom', 'Kit')], 'BoM Type',
        default='normal')
    use_master = fields.Boolean("Use master")
    block_fallow = fields.Boolean("Block follow operation type")

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


        boms_done = [(self, {'qty': quantity, 'product': product, 'original_qty': quantity, 'parent_line': False})]
        lines_done = []
        V |= set([product.product_tmpl_id.id])

        bom_lines = [(bom_line, product, quantity, False) for bom_line in self.bom_line_ids]
        master_product = product
        #master_attributes = product.attribute_value_ids
        for bom_line in self.bom_line_ids:
            V |= set([bom_line.product_id.product_tmpl_id.id])
            graph[product.product_tmpl_id.id].append(bom_line.product_id.product_tmpl_id.id)
        while bom_lines:
            current_line, current_product, current_qty, parent_line = bom_lines[0]
            bom_lines = bom_lines[1:]

            variant_product = (current_line.use_master and current_line.type == 'phantom') and master_product or current_product
            if current_line._skip_bom_line(variant_product):
                if current_line.use_master:
                    raise UserError(_(
                        'No match on parent master and child variant!  No match attributes %s!') % (tuple([x.name for x in variant_product.attribute_value_ids]), ))
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

            #_logger.info("BOM LINE %s=>%s" % (variant_product.display_name, bom_product.display_name))
            bom_picking_type = (current_line.block_fallow == False) and False or self.picking_type_id
            picking_type = (current_line.block_fallow == False) and False or picking_type
            bom = self._bom_find(product=bom_product, picking_type=picking_type or bom_picking_type, company_id=self.company_id.id)
            if bom.type == 'phantom' or current_line.type == 'phantom':
                converted_line_quantity = current_line.product_uom_id._compute_quantity(line_quantity / bom.product_qty, bom.product_uom_id)
                bom_lines = [(line, bom_product, converted_line_quantity, current_line) for line in bom.bom_line_ids] + bom_lines
                for bom_line in bom.bom_line_ids:
                    graph[bom_product.product_tmpl_id.id].append(bom_line.product_id.product_tmpl_id.id)
                    if bom_line.product_id.product_tmpl_id.id in V and check_cycle(bom_line.product_id.product_tmpl_id.id, {key: False for  key in V}, {key: False for  key in V}, graph):
                        raise UserError(_('Recursion error!  A product with a Bill of Material should not have itself in its BoM or child BoMs!'))
                    V |= set([bom_line.product_id.product_tmpl_id.id])
                boms_done.append((bom, {'qty': converted_line_quantity, 'product': bom_product, 'original_qty': quantity, 'parent_line': current_line}))
            else:
                # We round up here because the user expects that if he has to consume a little more, the whole UOM unit
                # should be consumed.
                rounding = current_line.product_uom_id.rounding
                line_quantity = float_round(line_quantity, precision_rounding=rounding, rounding_method='UP')
                line_quantity_real = float_round(line_quantity_real, precision_rounding=rounding, rounding_method='UP')
                lines_done.append((current_line, {'qty': line_quantity, 'qty_real': line_quantity_real, 'product': bom_product, 'original_qty': quantity, 'parent_line': parent_line}))

        return boms_done, lines_done

mrp_bom_explode.explode = MrpBom.explode
