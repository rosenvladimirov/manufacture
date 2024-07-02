# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp

import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    product_brand_id = fields.Many2one('product.brand', string='Brand', ondelete='restrict',
                                       help='Select a brand for this BOM')
    partner_id = fields.Many2one('res.partner', string='Ownet by Partner', ondelete='restrict',
                                 help='Choice it if The BOM will make like subcontractor for this partner')
    sale_id = fields.Many2one('sale.order', 'Sale Order', ondelete='restrict', index=True)
    sale_line_ids = fields.Many2many('sale.order.line', string='Sale Line')
    merge_pickings_ids = fields.One2many('mrp.production.merge', 'production_id', 'Merged MO')
    location_ids = fields.One2many('stock.location', string='Locations', compute="_compute_location_ids")
    product_tmpl_id = fields.Many2one(store=True)

    @api.multi
    def _compute_location_ids(self):
        for record in self:
            record.location_ids = self.env['stock.location']
            location_ids = self.env['stock.warehouse'].\
                search([('company_id', '=', self.env.user.company_id.id)]).mapped('lot_stock_id')
            for location_id in location_ids:
                record.location_ids |= self.env['stock.location'].search([('id', 'child_of', location_id.id)])

    @api.onchange('bom_id')
    def _onchange_bom_id(self):
        super(MrpProduction, self)._onchange_bom_id()
        self.product_brand_id = self.bom_id.product_brand_id
        self.partner_id = self.bom_id.partner_id

    @api.model
    def _prepare_for_merge(self, vals=False):
        if not vals:
            vals ={}
        return {
            'production_id': self.id,
            'oring_production_id': vals.get('oring_production_id'),
            'product_id': self.product_id.id,
            'product_qty': vals.get('product_qty', False) or self.product_qty,
            'product_uom_id': self.product_uom_id.id,
            'location_dest_id': self.location_dest_id.id,
            'bom_id': self.bom_id.id,
            'routing_id': self.routing_id and self.routing_id.id or False,
            'picking_type_id': self.picking_type_id.id,
            'name': self.name,
            'origin': self.origin,
            'company_id': self.company_id.id,
            'sale_id': vals.get('sale_id', False) or self.sale_id.id,
            'stock_move_id': vals.get('stock_move_id', False),
            'picking_id': vals.get('picking_id', False),
            'partner_id': vals.get('partner_id', False) or self.partner_id.id,
        }


class MrpProductionMerge(models.Model):
    _name = 'mrp.production.merge'
    _description = 'Collections of procurements'

    production_id = fields.Many2one(
        'mrp.production', 'Manufacturing Order',
        index=True, ondelete='cascade', required=True)
    oring_production_id = fields.Many2one('mrp.production', 'Oring production')
    product_id = fields.Many2one('product.product', 'Manufacture product')
    product_qty = fields.Float('Quantity To Produce', digits=dp.get_precision('Product Unit of Measure'),
                               readonly=True, required=True, track_visibility='onchange')
    product_uom_id = fields.Many2one('product.uom', 'Product Unit of Measure', readonly=True, required=True)
    location_dest_id = fields.Many2one('stock.location', 'Finished Products Location',
                                       readonly=True, required=True,
                                       help="Location where the system will stock the finished products.")
    bom_id = fields.Many2one('mrp.bom', 'Bill of Material', readonly=True,
                             help="Bill of Materials allow you to define the list of required "
                                  "raw materials to make a finished product.")
    routing_id = fields.Many2one('mrp.routing', 'Routing', readonly=True,
                                 help="The list of operations (list of work centers) to produce the finished product. "
                                      "The routing is mainly used to compute work center costs during operations and "
                                      "to plan future loads on work centers based on production planning.")
    picking_type_id = fields.Many2one('stock.picking.type', 'Operation Type', required=True)
    name = fields.Char('Name')
    origin = fields.Char('Origin')
    company_id = fields.Many2one('res.company', 'Company',
                                 default=lambda self: self.env['res.company']._company_default_get('mrp.production'),
                                 required=True)
    sale_id = fields.Many2one('sale.order', 'Sale Order', ondelete='restrict', index=True)
    sale_line_id = fields.Many2one('sale.order.line', 'Sale order line', index=True)
    stock_move_id = fields.Many2one('stock.move', 'Stock move')
    picking_id = fields.Many2one('stock.picking', 'Picking', related='stock_move_id.picking_id', store=True)
    partner_id = fields.Many2one('res.partner', string='Ownet by Partner', ondelete='restrict',
                                 help='Choice it if The BOM will make like subcontractor for this partner')
