# -*- coding: utf-8 -*-
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import api, models, fields, _
from odoo.addons.mrp.models.mrp_bom import MrpBom as mrp_bom_explode
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    ver_major = fields.Integer('Version major')
    ver_minor = fields.Integer('Version manor')

    @api.multi
    @api.depends('ver_major', 'ver_minor', 'code', 'product_tmpl_id.display_name')
    def name_get(self):
        result = []
        for bom in self:
            name = '.'.join([str(bom.ver_major), str(bom.ver_minor)])
            name = '[%s] %s' % (name, '%s%s' % (bom.code and '%s: ' % bom.code or '', bom.product_tmpl_id.display_name))
            result.append((bom.id, name))
        return result


class MrpBom(models.Model):
    _inherit = 'mrp.bom.line'

    loss = fields.Float("Enter The losses by %", help="Please enter the losses by percentage")
    product_qty_real = fields.Float(string="Re-calqulated Qty", compute="_compute_product_qty_real")
    type = fields.Selection([
        ('normal', 'Manufacture this product'),
        ('phantom', 'Kit')], 'BoM Type',
        default='normal')

    @api.multi
    @api.depends('loss', 'product_qty')
    def _compute_product_qty_real(self):
        for rec in self:
            rec.product_qty_real = rec.product_qty*(1+rec.loss/100)

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
        for bom_line in self.bom_line_ids:
            V |= set([bom_line.product_id.product_tmpl_id.id])
            graph[product.product_tmpl_id.id].append(bom_line.product_id.product_tmpl_id.id)
        while bom_lines:
            current_line, current_product, current_qty, parent_line = bom_lines[0]
            bom_lines = bom_lines[1:]

            if current_line._skip_bom_line(current_product):
                continue

            line_quantity = current_qty * current_line.product_qty_real
            line_quantity_total = current_qty * current_line.product_qty
            bom = self._bom_find(product=current_line.product_id, picking_type=picking_type or self.picking_type_id, company_id=self.company_id.id)
            if bom.type == 'phantom' or current_line.type == 'phantom':
                converted_line_quantity = current_line.product_uom_id._compute_quantity(line_quantity / bom.product_qty, bom.product_uom_id)
                bom_lines = [(line, current_line.product_id, converted_line_quantity, current_line) for line in bom.bom_line_ids] + bom_lines
                for bom_line in bom.bom_line_ids:
                    graph[current_line.product_id.product_tmpl_id.id].append(bom_line.product_id.product_tmpl_id.id)
                    if bom_line.product_id.product_tmpl_id.id in V and check_cycle(bom_line.product_id.product_tmpl_id.id, {key: False for  key in V}, {key: False for  key in V}, graph):
                        raise UserError(_('Recursion error!  A product with a Bill of Material should not have itself in its BoM or child BoMs!'))
                    V |= set([bom_line.product_id.product_tmpl_id.id])
                boms_done.append((bom, {'qty': converted_line_quantity, 'product': current_product, 'original_qty': quantity, 'parent_line': current_line}))
            else:
                # We round up here because the user expects that if he has to consume a little more, the whole UOM unit
                # should be consumed.
                rounding = current_line.product_uom_id.rounding
                line_quantity = float_round(line_quantity, precision_rounding=rounding, rounding_method='UP')
                lines_done.append((current_line, {'qty': line_quantity, 'qty_real': line_quantity_total, 'product': current_product, 'original_qty': quantity, 'parent_line': parent_line}))

        return boms_done, lines_done
