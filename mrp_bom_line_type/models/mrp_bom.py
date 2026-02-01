# -*- coding: utf-8 -*-
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import api, models, fields, _
from odoo.tools import float_round

from collections import defaultdict

import logging

_logger = logging.getLogger(__name__)


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    line_type = fields.Selection([
        ('normal', 'Normal'),
        ('phantom', 'Kit'),
    ], string='Line Type Override',
        help="Override the child BOM type:\n"
             "- Normal: Use child BOM's own type\n"
             "- Kit: Force treat as phantom/kit regardless of child BOM type",
        default='normal')


def explode_with_line_type(self, product, quantity, picking_type=False, never_attribute_values=False):
    """
    Explodes the BoM and creates two lists with all the information you need: bom_done and line_done
    Quantity describes the number of times you need the BoM: so the quantity divided by the number created by the BoM
    and converted into its UoM
    
    PATCHED: Added support for line_type field on BOM lines.
    When line_type='phantom', the child BOM is treated as a kit regardless of its actual type.
    """
    product_ids = set()
    product_boms = {}
    # Track which products need phantom-only search vs any-bom search
    force_phantom_products = set()

    def update_product_boms():
        products = self.env['product.product'].browse(product_ids)
        # First, search for phantom BOMs (standard behavior)
        product_boms.update(self._bom_find(
            products, 
            picking_type=picking_type or self.picking_type_id,
            company_id=self.company_id.id, 
            bom_type='phantom'
        ))
        # For products that need force phantom, also search for any BOM type
        if force_phantom_products:
            force_products = self.env['product.product'].browse(force_phantom_products)
            any_boms = self._bom_find(
                force_products,
                picking_type=picking_type or self.picking_type_id,
                company_id=self.company_id.id,
                bom_type=False  # Any type
            )
            # Only update if we don't already have a phantom BOM
            for prod, bom in any_boms.items():
                if not product_boms.get(prod):
                    product_boms[prod] = bom
        # Set missing keys to default value
        for prod in products:
            product_boms.setdefault(prod, self.env['mrp.bom'])

    boms_done = [(self, {'qty': quantity, 'product': product, 'original_qty': quantity, 'parent_line': False})]
    lines_done = []

    bom_lines = []
    for bom_line in self.bom_line_ids:
        product_id = bom_line.product_id
        bom_lines.append((bom_line, product, quantity, False))
        product_ids.add(product_id.id)
        # === KEY CHANGE: Track products that need force phantom ===
        line_type = getattr(bom_line, 'line_type', 'normal') or 'normal'
        if line_type == 'phantom':
            force_phantom_products.add(product_id.id)
            
    update_product_boms()
    product_ids.clear()
    force_phantom_products.clear()
    
    while bom_lines:
        current_line, current_product, current_qty, parent_line = bom_lines[0]
        bom_lines = bom_lines[1:]

        if current_line._skip_bom_line(current_product, never_attribute_values):
            continue

        line_quantity = current_qty * current_line.product_qty
        
        # Get line_type safely (might not exist if module not fully installed)
        current_line_type = getattr(current_line, 'line_type', 'normal') or 'normal'
        
        # Check if we need to fetch BOMs for this product
        if current_line.product_id not in product_boms:
            product_ids.add(current_line.product_id.id)
            if current_line_type == 'phantom':
                force_phantom_products.add(current_line.product_id.id)
            update_product_boms()
            product_ids.clear()
            force_phantom_products.clear()
            
        bom = product_boms.get(current_line.product_id)
        
        # === KEY CHANGE: Force phantom behavior if line_type is phantom ===
        # Even if no phantom BOM was found, if line_type is phantom and we have any BOM, use it
        if not bom and current_line_type == 'phantom':
            # Search for any BOM type for this specific product
            any_bom_result = self._bom_find(
                current_line.product_id,
                picking_type=picking_type or self.picking_type_id,
                company_id=self.company_id.id,
                bom_type=False
            )
            bom = any_bom_result.get(current_line.product_id)
            if bom:
                product_boms[current_line.product_id] = bom
        
        if bom:
            converted_line_quantity = current_line.product_uom_id._compute_quantity(
                line_quantity / bom.product_qty, bom.product_uom_id, round=False
            )
            bom_lines = [(line, current_line.product_id, converted_line_quantity, current_line) for line in bom.bom_line_ids] + bom_lines
            for bom_line in bom.bom_line_ids:
                if bom_line.product_id not in product_boms:
                    product_ids.add(bom_line.product_id.id)
                    # === Track force phantom for child lines too ===
                    child_line_type = getattr(bom_line, 'line_type', 'normal') or 'normal'
                    if child_line_type == 'phantom':
                        force_phantom_products.add(bom_line.product_id.id)
            boms_done.append((bom, {'qty': converted_line_quantity, 'product': current_product, 'original_qty': quantity, 'parent_line': current_line}))
        else:
            # We round up here because the user expects that if he has to consume a little more, the whole UOM unit
            # should be consumed.
            rounding = current_line.product_uom_id.rounding
            line_quantity = float_round(line_quantity, precision_rounding=rounding, rounding_method='UP')
            lines_done.append((current_line, {'qty': line_quantity, 'product': current_product, 'original_qty': quantity, 'parent_line': parent_line}))

    return boms_done, lines_done
