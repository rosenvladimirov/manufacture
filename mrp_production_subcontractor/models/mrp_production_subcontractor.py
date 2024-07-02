# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError, AccessError

import logging

_logger = logging.getLogger(__name__)


class MrpProductionSubcontractor(models.Model):
    _name = 'mrp.production.subcontractor'
    _description = 'Production given to subcontractor'

    name = fields.Char('Subcontract Reference',
                       default=lambda self: self.env['ir.sequence'].next_by_code('mrp.production.subcontractor'),
                       copy=False, required=True)
    date = fields.Date('Subcontract date')
    location_src_id = fields.Many2one('stock.location', 'Raw Materials Location', required=True,
                                      help="Location where the system will look for components.")
    location_dest_id = fields.Many2one('stock.location', 'Finished Products Location', required=True,
                                       help="Location where the system will stock the finished products.")
    partner_id = fields.Many2one('res.partner', string='Subcontractor', required=True)
    date_from = fields.Date('Date from', required=True)
    date_to = fields.Date('Date to', required=True)
    product_tmpl_ids = fields.One2many('product.template', string='Product Template',
                                       compute='_compute_product_tmpl_ids')
    invoice_ids = fields.One2many('account.invoice', string='Invoices', compute='_compute_invoice_ids')
    purchase_ids = fields.One2many('purchase.order', string='Purchase orders', compute='_compute_purchase_ids')
    production_ids = fields.Many2many('mrp.production', string='Planed Production', store=False)
    finished_production_ids = fields.One2many('mrp.production', string='Finished Production',
                                              compute='_compute_finished_production_ids')
    # service_product_ids = fields.Many2many('product.product', string='Service product')
    service_product_lines = fields.One2many('mrp.production.product.subcontractor',
                                    string='Product service subcontractor',
                                    inverse_name='subcontract_id',
                                    copy=False)
    service_lines = fields.One2many('mrp.production.service.subcontractor',
                                    string='Production service subcontractor',
                                    inverse_name='subcontract_id',
                                    copy=False)
    production_lines = fields.One2many('mrp.production.ordered.subcontractor',
                                       string='Ordered production',
                                       inverse_name='subcontract_id',
                                       copy=False)

    @api.onchange('production_lines')
    def onchange_production_lines(self):
        self.action_change_location()

    @api.onchange('partner_id', 'date_from', 'date_to')
    @api.depends('production_ids', 'invoice_ids', 'purchase_ids')
    def onchange_partner_id(self):
        for record in self:
            production_ids = self.env['mrp.production']

            for line in record.production_lines:
                production_ids |= line.production_id

            if not production_ids:
                production_ids = self.env['mrp.production']. \
                    search([
                    ('state', '=', 'done'),
                    ('date_start', '>=', record.date_from),
                    ('date_finished', '<=', record.date_to),
                    ('location_dest_id', '=', record.location_dest_id.id)])
            record.with_context(dict(self._context, block_adding=True)).production_ids = self.env['mrp.production']
            for line in production_ids:
                record.with_context(dict(self._context, block_adding=True)).production_ids |= line

    @api.onchange('production_ids')
    @api.depends('production_lines')
    def onchange_production_ids(self):
        for record in self:
            if not self._context.get('block_adding', False):
                record.production_lines = self.env['mrp.production.ordered.subcontractor']
                for line in record.production_ids:
                    record.production_lines += self.env['mrp.production.ordered.subcontractor'].new({
                        'production_id': line.id,
                        'bom_id': line.bom_id.id,
                        'product_qty': line.product_qty,
                        'location_src_id': line.location_src_id.id,
                        'location_dest_id': line.location_dest_id.id,
                        'date_planned_start': line.date_planned_start,
                        'date_planned_finished': line.date_planned_finished,
                        'state': line.state,
                    })

    @api.multi
    def _compute_invoice_ids(self):
        for record in self:
            invoice_ids = self.env['account.invoice'].search([('type', 'in', ['in_invoice', 'in_refund']),
                                                              ('date_invoice', '>=', record.date_from),
                                                              ('date_invoice', '<=', record.date_to),
                                                              '|', ('partner_id', '=', record.partner_id.id),
                                                              ('partner_id', 'child_of', record.partner_id.id)])
            record.invoice_ids = self.env['account.invoice']
            for line in invoice_ids:
                record.invoice_ids |= line

    @api.multi
    def _compute_purchase_ids(self):
        for record in self:
            purchase_ids = self.env['purchase.order']. \
                search([('date_approve', '>=', record.date_from),
                        ('date_approve', '<=', record.date_to),
                        '|', ('partner_id', '=', record.partner_id.id),
                        ('partner_id', 'child_of', record.partner_id.id)])
            record.purchase_ids = self.env['purchase.order']
            for line in purchase_ids:
                record.purchase_ids |= line

    @api.multi
    def _compute_product_tmpl_ids(self):
        for record in self:
            production_ids = self.env['mrp.production']. \
                search([
                ('state', '=', 'done'),
                ('date_start', '>=', record.date_from),
                ('date_finished', '<=', record.date_to),
                ('location_dest_id', '=', record.location_dest_id.id)])
            record.product_tmpl_ids = self.env['product.template']
            for line in production_ids:
                record.product_tmpl_ids |= line.product_tmpl_id

    @api.multi
    def _compute_finished_production_ids(self):
        for record in self:
            production_ids = self.env['mrp.production']. \
                search([
                ('state', '=', 'done'),
                ('date_start', '>=', record.date_from),
                ('date_finished', '<=', record.date_to),
                ('location_dest_id', '=', record.location_dest_id.id)])
            record.finished_production_ids = self.env['mrp.production']
            for line in production_ids:
                record.finished_production_ids |= line

    @api.multi
    def action_change_location(self):
        production_ids = self.env['mrp.production']
        for record in self:
            for line in record.production_lines:
                if line.production_id.location_src_id != record.location_src_id \
                        or line.production_id.location_dest_id != record.location_dest_id:
                    production_ids |= line.production_id

            if production_ids:
                wiz = self.env['wiz.mrp.split.production']. \
                    with_context(dict(self._context, active_model='mrp.production', active_ids=production_ids.ids)). \
                    create({
                    'state': 'location',
                    'location_src_id': record.location_src_id.id,
                    'location_dest_id': record.location_dest_id.id,
                })
                wiz.server_action_change_location_production()

    @api.multi
    def action_add_services(self):
        for record in self:
            # record.service_lines = self.env['mrp.production.service.subcontractor']
            for line in record.production_lines:
                for service_product in record.service_product_lines:
                    if service_product.product_tmpl_id \
                            and service_product.product_tmpl_id != line.product_id.product_tmpl_id:
                        continue
                    service_line = record.production_lines.\
                        filtered(lambda r: r.product_id == service_product.product_id and r.production_id == line.production_id)
                    if service_line:
                        service_line.product_qty += line.product_qty
                    else:
                        record.service_lines += self.env['mrp.production.service.subcontractor'].new({
                            'partner_id': record.partner_id.id,
                            'product_id': service_product.product_id.id,
                            'production_id': line.production_id.id,
                            'product_qty': line.product_qty,
                            'product_uom': service_product.product_id.uom_id.id,
                        })
            for line in record.service_lines.filtered(lambda r: not r.partner_id):
                line.partner_id = record.partner_id

    @api.multi
    def action_compute_services(self):
        for record in self:
            for line in record.service_lines.filtered(lambda r: not r.procurement_group_id):
                if line.product_id.property_subcontracted_service:
                    warehouse = self.env['stock.warehouse'].search(
                        [('company_id', '=', line.production_id.company_id.id)], limit=1)
                    values = {
                        'date_planned': fields.Date.today(),
                        'company_id': line.production_id.company_id,
                        'route_ids': line.product_id.route_ids,
                        'group_id': line.production_id.procurement_group_id,
                        'warehouse_id': warehouse,
                        'analytic_account_id': line.production_id.analytic_account_id.id,
                        'note2': line.note2,
                        'force_partner_id': record.partner_id != line.partner_id and line.partner_id or False,
                        'subcontractor': True,
                    }
                    self.env['procurement.group'].run(line.product_id,
                                                      line.product_qty,
                                                      line.product_uom,
                                                      line.production_id.location_src_id,
                                                      line.production_id.name,
                                                      line.production_id.name,
                                                      values)
                    line.procurement_group_id = line.production_id.procurement_group_id
                    line.production_id.extra_product_ids |= line.product_id
                    line.production_id._compute_service_amount()


class MrpProductionServicesSubcontractor(models.Model):
    _name = 'mrp.production.service.subcontractor'
    _description = 'Service from subcontractor'
    _parent_name = "parent_id"
    _parent_store = True
    # _parent_order = 'product_id'
    _order = 'parent_left'

    subcontract_id = fields.Many2one('mrp.production.subcontractor',
                                     'Production subcontractor',
                                     required=True,
                                     index=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', 'Partner')
    parent_id = fields.Many2one('mrp.production.service.subcontractor', 'Parent Service',
                                index=True, ondelete='cascade')
    child_id = fields.One2many('mrp.production.service.subcontractor', 'parent_id', 'Child Services')
    parent_left = fields.Integer('Left Parent', index=1)
    parent_right = fields.Integer('Right Parent', index=1)

    product_id = fields.Many2one('product.product',
                                 string='Product',
                                 domain=[('purchase_ok', '=', True)],
                                 required=True)
    product_uom = fields.Many2one('product.uom',
                                  string='Product Unit of Measure',
                                  required=True)
    production_id = fields.Many2one('mrp.production',
                                    string='Production',)
    final_product_id = fields.Many2one('product.product', 'Final product', related='production_id.product_id')
    qty_produced = fields.Float(string='Produced quantity', related='production_id.qty_produced')
    product_qty = fields.Float(string='Quantity',
                               digits=dp.get_precision('Product Unit of Measure'),
                               required=True)
    procurement_group_id = fields.Many2one('procurement.group', 'Procurement Group', copy=False)
    comment_template2_id = fields.Many2one('base.comment.template',
                                           string='Comment Template')
    note2 = fields.Html('Comment')

    @api.onchange('comment_template2_id')
    def _set_note1(self):
        comment = self.comment_template2_id
        if comment:
            self.note2 = comment.get_value()

    @api.onchange('product_id')
    def onchange_product_id(self):
        result = {}
        if not self.product_id:
            return result
        self.product_uom = self.product_id.uom_po_id or self.product_id.uom_id
        result['domain'] = {'product_uom': [('category_id', '=', self.product_id.uom_id.category_id.id)]}
        return result


class MrpProductionOrderedSubcontractor(models.Model):
    _name = 'mrp.production.ordered.subcontractor'
    _description = 'Ordered production to subcontractor'

    subcontract_id = fields.Many2one('mrp.production.subcontractor',
                                     'Production subcontractor',
                                     required=True,
                                     index=True, ondelete='cascade')
    bom_id = fields.Many2one('mrp.bom', 'Bom')
    production_id = fields.Many2one('mrp.production', 'Production')
    product_id = fields.Many2one('product.product', 'Product', related='production_id.product_id')
    product_qty = fields.Float(string='Quantity',
                               digits=dp.get_precision('Product Unit of Measure'),
                               related='production_id.product_qty', store=True)
    location_src_id = fields.Many2one('stock.location', 'Source material location',
                                      related='production_id.location_src_id', store=True)
    location_dest_id = fields.Many2one('stock.location', 'Destination production location',
                                       related='production_id.location_dest_id', store=True)
    date_planned_start = fields.Datetime('Deadline Start', related='production_id.date_planned_start', store=True)
    date_planned_finished = fields.Datetime('Deadline End', related='production_id.date_planned_finished', store=True)
    state = fields.Selection([
        ('confirmed', 'Confirmed'),
        ('planned', 'Planned'),
        ('progress', 'In Progress'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')], string='State',
        related='production_id.state')


class MrpProductionProductSubcontractor(models.Model):
    _name = 'mrp.production.product.subcontractor'
    _description = 'Service product subcontractor'

    product_id = fields.Many2one('product.product', 'Product Service')
    product_tmpl_id = fields.Many2one('product.template', 'Product template')
    subcontract_id = fields.Many2one('mrp.production.subcontractor',
                                     'Production subcontractor',
                                     required=True,
                                     index=True, ondelete='cascade')
    price = fields.Float('Price', default=0.0, digits=dp.get_precision('Product Price'),
                         help="The price to purchase a product")
    currency_id = fields.Many2one(
        'res.currency', 'Currency',
        default=lambda self: self.env.user.company_id.currency_id.id,
        required=True)

    @api.onchange('product_id')
    def onchange_product_id(self):
        if self.product_id:
            seller = self.product_id._select_seller(
                    partner_id=self.subcontract_id.partner_id,
                    date=self.subcontract_id.date_from)
            if seller:
                self.price = seller.price

    @api.onchange('price')
    def onchange_price(self):
        if self.product_id:
            seller = self.product_id._select_seller(
                partner_id=self.subcontract_id.partner_id,
                date=self.subcontract_id.date_from)
            if self.price != 0.0 and not seller:
                partner = self.subcontract_id.partner_id
                currency = self.currency_id
                supplierinfo = {
                    'name': partner.id,
                    'sequence': max(self.product_id.seller_ids.mapped('sequence')) + 1 if self.product_id.seller_ids else 1,
                    'min_qty': 0.0,
                    'price': self.price,
                    'currency_id': currency.id,
                    'delay': 0,
                }
                vals = {
                    'seller_ids': [(0, 0, supplierinfo)],
                }
                try:
                    self.product_id.write(vals)
                except AccessError:  # no write access rights -> just ignore
                    pass
