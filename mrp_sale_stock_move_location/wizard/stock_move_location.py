# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from itertools import groupby

import logging

_logger = logging.getLogger(__name__)


class SaleStockMoveLocationWizard(models.TransientModel):
    _name = "wiz.sale.stock.move.location"
    _description = "Wizard for create special picking from sale orders"

    def _get_locations_domain(self):
        return [('usage', '=', 'internal')]

    @api.multi
    def _get_default_picking_type_id(self):
        company_id = self.env.context.get('company_id') or \
                     self.env.user.company_id.id
        return self.env['stock.picking.type'].search(
            [('code', '=', 'internal'),
             ('warehouse_id.company_id', '=', company_id)], limit=1).id

    origin_location_disable = fields.Boolean(
        compute="_compute_readonly_locations",
        help="technical field to disable the edition of origin location."
    )
    origin_location_id = fields.Many2one(
        string='Origin Location',
        comodel_name='stock.location',
        required=True,
        domain=lambda self: self._get_locations_domain(),
    )
    destination_location_disable = fields.Boolean(
        compute="_compute_readonly_locations",
        help="technical field to disable the edition of destination location."
    )
    destination_location_id = fields.Many2one(
        string='Destination Location',
        comodel_name='stock.location',
        required=True,
        domain=lambda self: self._get_locations_domain(),
    )
    filter_location_id = fields.Many2one(
        string='Filter Location',
        comodel_name='stock.location',
        required=True,
        domain=lambda self: self._get_locations_domain(),
    )
    destination_owner_disable = fields.Boolean(
        compute="_compute_readonly_locations",
        help="technical field to disable the edition of destination owner."
    )
    owner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Owner',
        help="Owner of the quants"
    )
    picking_type_id = fields.Many2one(
        comodel_name='stock.picking.type',
        default=_get_default_picking_type_id,
    )
    stock_move_location_line_ids = fields.One2many(
        string="Move Location lines",
        comodel_name="wiz.sale.stock.move.location.line",
        inverse_name="move_location_wizard_id",
    )
    filtered_move_location_line_ids = fields.Many2many(
        comodel_name='wiz.sale.stock.move.location.line',
        relation='wiz_filtered_sale_stock_move',
        string="Move Location lines",
        # compute='_compute_filtered_move_location_line_ids'
    )
    bom_line_ids = fields.One2many(
        string="Bom lines",
        comodel_name="wiz.sale.line",
        inverse_name="move_location_wizard_id",
    )
    sale_order_line_ids = fields.One2many(
        comodel_name='wiz.sale.order.line',
        string='Sale order lines',
        inverse_name="move_location_wizard_id",
    )
    picking_id = fields.Many2one(
        string="Connected Picking",
        comodel_name="stock.picking",
    )
    edit_locations = fields.Boolean(
        string='Edit Locations',
        default=True
    )
    work_with_reservation = fields.Boolean(
        string='Work with reservation',
    )
    product_ids = fields.Many2many(
        comodel_name='product.product',
        string='Products',
    )
    product_tmpl_ids = fields.Many2many(
        comodel_name='product.template',
        string='Products',
    )
    bom_ids = fields.Many2many(
        comodel_name='mrp.bom',
        string='Used boms'
    )
    production_ids = fields.Many2many(
        comodel_name='mrp.production',
        string='Productions',
    )
    product_type_ids = fields.Many2many(
        comodel_name='project.product.types',
        string='Product Type'
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
    )
    create_order_point = fields.Boolean('Direct order point', default=True)

    # create_order_point_semi = fields.Boolean('Direct order point semi-product', default=True)

    @api.depends('edit_locations')
    def _compute_readonly_locations(self):
        for rec in self:
            rec.origin_location_disable = self.env.context.get(
                'origin_location_disable', False)
            if not rec.edit_locations:
                rec.origin_location_disable = True
                rec.destination_location_disable = True
                rec.destination_owner_disable = True

    def sale_order_values(self, line):
        return {}

    @api.model
    def default_get(self, fields_list):
        res = super(SaleStockMoveLocationWizard, self).default_get(fields_list)
        analytic_account_id = self.env['account.analytic.account']
        manufacture_route = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
        moves = []
        main_warehouse_location_id = False
        products = False
        company_id = self.env.user.company_id
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company_id.id)], limit=1)
        mrp_warehouse = self.env['stock.warehouse'].search([('company_id', '=', company_id.id),
                                                            ('manufacture_to_resupply', '=', True)], limit=1)
        location_dest_id = mrp_warehouse.lot_stock_id
        sale_order_line_ids = self.env['sale.order.line']
        filter_location_id = False

        if self._context.get('active_ids') and self._context.get('active_model') == 'sale.order':
            main_warehouse_location_id = warehouse.lot_stock_id
            sale_order_ids = self.env['sale.order'].browse(self._context['active_ids'])
            for order in sale_order_ids:
                if order.analytic_account_id and order.analytic_account_id.dest_address_id:
                    location_dest_id = order.analytic_account_id.dest_address_id
                    filter_location_id = analytic_account_id.dest_address_id
                for line in order.order_line:
                    sale_order_line_ids |= line
            products = sale_order_line_ids.mapped('product_id')

        if products and not res.get('product_ids'):
            res['product_ids'] = [(6, False, products.ids)]
            res['product_tmpl_ids'] = [(6, False, products.mapped('product_tmpl_id').ids)]

        res['company_id'] = company_id.id
        if warehouse:
            res['origin_location_id'] = warehouse.lot_stock_id.id
        if mrp_warehouse:
            res['destination_location_id'] = location_dest_id.id
        if filter_location_id:
            res['filter_location_id'] = filter_location_id.id
        else:
            res['filter_location_id'] = location_dest_id.id
        sale_order_lines = []
        new_bom_ids = self.env['mrp.bom']
        production_ids = self.env['mrp.production']

        for line in sale_order_line_ids:
            product = line.product_id
            analytic_account_id |= line.order_id.analytic_account_id

            # _logger.info('PRODUCT %s' % product.display_name)
            if manufacture_route.id not in product.mapped('route_ids').ids:
                continue
            production = self.env['mrp.production'].search([('procurement_group_id.sale_id', '=', line.order_id.id),
                                                            ('product_id', '=', line.product_id.id)], limit=1)
            if production and production.bom_id:
                bom = production.bom_id
                production_ids |= production
            else:
                bom = self.env['mrp.bom']._bom_find(product=product, company_id=company_id.id)
                if not bom:
                    bom = self.env['mrp.bom']._bom_find(product_tmpl=product.product_tmpl_id, company_id=company_id.id)
                if not bom:
                    continue
            new_bom_ids |= bom
            sale_order_values = self.sale_order_values(line)
            sale_order_values.update({
                'bom_id': bom.id,
                'sale_order_line_id': line.id,
                'product_uom_qty': line.product_uom_qty,
                'product_id': line.product_id.id,
            })
            sale_order_lines.append((0, False, sale_order_values))
            # _logger.info("BOM %s" % bom.product_tmpl_id.display_name)
            factor = product.uom_id._compute_quantity(1.0, bom.product_uom_id) / bom.product_qty
            boms, exploded_lines = bom.with_context(dict(self._context, force_phantom=True)). \
                explode(product, factor, picking_type=bom.picking_type_id)
            # bom_raw_ids = bom.mapped('bom_line_ids')
            if bom.routing_id:
                location_id = bom.routing_id.location_id or warehouse.lot_stock_id
            else:
                location_id = warehouse.lot_stock_id
            if not filter_location_id:
                filter_location_id = location_id
            for bom_line, line_data in exploded_lines:
                if manufacture_route.id not in bom_line.product_id.mapped('route_ids').ids:
                    vals = self._copy_move_line(bom_line,
                                                line_data['qty'],
                                                line,
                                                location_id,
                                                location_dest_id,
                                                filter_location_id,
                                                company_id)
                    moves.append((0, False, vals))
        if moves:
            res['bom_line_ids'] = moves

        if sale_order_lines:
            res['sale_order_line_ids'] = sale_order_lines

        if new_bom_ids:
            res['bom_ids'] = [(6, False, new_bom_ids.ids)]

        if production_ids:
            res['production_ids'] = [(6, False, production_ids.ids)]
        # _logger.info("RES %s" % res)
        return res

    def _copy_move_line(self, move_line, qty, line, source_location, destination_location, filter_location_id,
                        company_id):
        mrp_product_id = line.product_id
        return {
            'sequence': move_line.sequence,
            'name': mrp_product_id.display_name,
            'mrp_product_id': mrp_product_id.id,
            'product_id': move_line.product_id.id,
            'product_uom_qty': qty,
            # 'all_wh_total_quantity': available_quantity,
            # 'exclude_product_uom_qty': available_quantity,
            'product_uom': move_line.product_uom_id.id,
            'location_id': source_location.id,
            'location_dest_id': destination_location.id,
            'filter_location_id': filter_location_id.id,
            'company_id': company_id.id,
            # 'price_unit': move_line['price_unit'],
            'warehouse_id': source_location.get_warehouse().id,
            'bom_line_id': move_line.id,
            'bom_id': move_line.bom_id.id,
            'sale_order_line_id': line.id
        }

    # @api.multi
    # def _compute_filtered_move_location_line_ids(self):
    #     for record in self:
    #         record.filtered_move_location_line_ids = self.env['wiz.sale.stock.move.location.line']
    #         for line in record.stock_move_location_line_ids:
    #             record.filtered_move_location_line_ids |= line

    @api.onchange('product_type_ids')
    @api.depends('stock_move_location_line_ids', 'filtered_move_location_line_ids')
    def onchange_product_type_ids(self):
        self.ensure_one()
        # _logger.info("product_type_ids %s:%s" % (self.product_type_ids.ids, self.stock_move_location_line_ids))
        if len(self.product_type_ids.ids) > 0:
            self.filtered_move_location_line_ids = self.env['wiz.sale.stock.move.location.line']
            for line in self.stock_move_location_line_ids:
                if line.product_type_id.id in self.product_type_ids.ids:
                    self.filtered_move_location_line_ids |= line
                # _logger.info("LINE %s" % line)
        # else:
        #     self.filtered_move_location_line_ids = self.env['wiz.sale.stock.move.location.line']
        #     for line in self.stock_move_location_line_ids:
        #         self.filtered_move_location_line_ids |= line

    @api.onchange('sale_order_line_ids')
    @api.depends('stock_move_location_line_ids')
    def onchange_sale_order_line_ids(self):
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.user.company_id.id)], limit=1)
        for record in self:
            # record.stock_move_location_line_ids = self.env['wiz.sale.stock.move.location.line']
            # main_warehouse_location_id = len(record.sale_order_line_ids.ids) > 0 and warehouse.lot_stock_id or False
            # if main_warehouse_location_id != record.filter_location_id:
            #     main_warehouse_location_id = record.filter_location_id
            record.stock_move_location_line_ids = False
            record.filtered_move_location_line_ids = self.env['wiz.sale.stock.move.location.line']
            for line in record.sale_order_line_ids:
                analytic_account_id = line.sale_order_line_id.order_id.analytic_account_id
                bom_line_ids = record.bom_line_ids. \
                    filtered(lambda r: r.mrp_product_id == line.product_id
                                       and r.sale_order_line_id == line.sale_order_line_id)
                record.stock_move_location_line_ids |= record. \
                    with_context(dict(self._context, main_warehouse_location_id=record.filter_location_id.id)). \
                    _group_product(bom_line_ids,
                                   qty_producing=line.product_uom_qty,
                                   analytic_account_id=analytic_account_id,
                                   sale_order_line_id=line.sale_order_line_id)

            if record.stock_move_location_line_ids:
                stock_move_location_line_ids = record.stock_move_location_line_ids
                # record.stock_move_location_line_ids = self.env['wiz.sale.stock.move.location.line']
                record.stock_move_location_line_ids = record. \
                    with_context(dict(self._context, main_warehouse_location_id=record.filter_location_id.id)). \
                    _group_product(stock_move_location_line_ids)
                for line in record.stock_move_location_line_ids:
                    record.filtered_move_location_line_ids |= line

    def get_group_values(self, lines, sale_order_line_id=False):
        # _logger.info("PURCHASE %s" % sale_order_line_id)
        res = {}
        if sale_order_line_id:
            res.update({
                'sale_order_line_id': sale_order_line_id.id,
                # 'sale_order_ids': [(6, False, sale_order_line_id.ids)]
            })
        if len(lines) > 0 and lines[0]._name == 'wiz.sale.stock.move.location.line':
            sale_order_ids = self.env['sale.order.line']
            for line in lines:
                sale_order_ids |= line.sale_order_line_id
            if sale_order_ids:
                res.update({
                    'sale_order_ids': [(6, False, sale_order_ids.ids)]
                })
        return res

    def _group_product(self, grouping, qty_producing=1.0, analytic_account_id=False, sale_order_line_id=False):
        stock_move_location_line_ids = self.env['wiz.sale.stock.move.location.line']
        main_warehouse_location_id = self._context.get('main_warehouse_location_id', False)
        filter_location_id = False
        if main_warehouse_location_id:
            main_warehouse_location_id = self.env['stock.location'].browse(main_warehouse_location_id)
        for group, lines in groupby(grouping.sorted(lambda r: r.product_id.id), lambda r: r.product_id):
            new_lines = list(lines)
            new_line = new_lines[0]
            if not analytic_account_id:
                analytic_account_id = new_line.analytic_account_id
            domain = [('product_id', '=', new_line.product_id.id)]
            if analytic_account_id:
                domain.append(('account_analytic_id', 'in', analytic_account_id.ids))
            purchase_ids = self.env['purchase.order.line'].search(domain, order='date_planned DESC')
            if analytic_account_id:
                if len(analytic_account_id.ids) > 1:
                    filter_location_id = analytic_account_id[0].dest_address_id
                else:
                    filter_location_id = analytic_account_id.dest_address_id
            if not filter_location_id:
                filter_location_id = main_warehouse_location_id and main_warehouse_location_id or self.origin_location_id
            _logger.info("FILTER LOCATION %s %s" % (filter_location_id, analytic_account_id))
            if main_warehouse_location_id:
                available_quantity = self.env['stock.quant']. \
                    _get_available_quantity(new_line.product_id,
                                            filter_location_id,
                                            strict=True)
                all_wh_total_quantity = self.env['stock.quant']. \
                    _get_available_quantity(new_line.product_id, filter_location_id)
                transfers_quantity = 0.0
                for line in purchase_ids:
                    picking_qty = 0.0
                    for picking_id in purchase_ids:
                        picking_qty = sum([x.quantity_done for x in picking_id.move_ids.
                                          filtered(lambda r: r.product_id == new_line.product_id)])
                        # _logger.info("PURCHASE %s (%s)" % (picking_id, picking_qty))
                    purchase_product_qty = line.product_uom._compute_quantity(line.product_qty, new_line.product_uom)
                    purchase_product_qty = picking_qty < purchase_product_qty and picking_qty or purchase_product_qty
                    transfers_quantity += purchase_product_qty - line.product_uom. \
                        _compute_quantity(line.qty_received, new_line.product_uom)
            else:
                transfers_quantity = 0.0  # For check
                available_quantity = self.env['stock.quant']._get_available_quantity(new_line.product_id,
                                                                                     self.filter_location_id,
                                                                                     strict=True)
                all_wh_total_quantity = self.env['stock.quant']. \
                    _get_available_quantity(new_line.product_id, self.origin_location_id)

            # _logger.info("LINE %s:%sx%s" % (
            #     new_line.product_id.display_name, [x.product_uom_qty for x in new_lines], qty_producing))
            product_type_id = new_line.product_id.product_tmpl_id.categ_id.get_product_type_id()
            if not sale_order_line_id and new_line.sale_order_line_id:
                sale_order_line_id = new_line.sale_order_line_id
                # _logger.info("PURCHASE GROUPING %s:%s" % (sale_order_line_id, new_line.sale_order_line_id))
            product_uom_qty = sum([x.product_uom_qty * qty_producing for x in new_lines])
            values = self.get_group_values(new_lines, sale_order_line_id=sale_order_line_id, )
            values.update({
                'product_id': group.id,
                'product_uom_qty': product_uom_qty,
                'product_uom': new_line.product_uom.id,
                'all_wh_total_quantity': all_wh_total_quantity,
                'exclude_product_uom_qty': available_quantity,
                'transfers_quantity': transfers_quantity,
                'max_quantity': product_uom_qty,
                'sequence': new_line.sequence,
                'name': new_line.name,
                'location_id': main_warehouse_location_id and main_warehouse_location_id.id or self.origin_location_id.id,
                'location_dest_id': self.destination_location_id.id,
                'filter_location_id': filter_location_id.id,
                'company_id': self.company_id.id,
                'price_unit': new_line.price_unit,
                'origin': "Force transfer %s" % group.name,
                'warehouse_id': self.origin_location_id.get_warehouse().id,
                'analytic_account_id': analytic_account_id.id,
                'purchase_ids': [(6, False, purchase_ids.ids)],
                'product_type_id': product_type_id.id,
                'move_location_wizard_id': self.id,
            })
            _logger.info("VALUES %s" % values)
            # _logger.info("GROUP %s\n%s=%s\n%s" % ([x.product_uom_qty for x in new_lines], sale_order_line_id.product_uom_qty, qty_producing, values))
            stock_move_location_line_ids |= self.env['wiz.sale.stock.move.location.line'].create(values)
        # _logger.info("NEW LINE %s:%s" % (stock_move_location_line_ids.mapped('purchase_ids'), stock_move_location_line_ids.mapped('sale_order_ids')))
        return stock_move_location_line_ids

    @api.onchange('origin_location_id')
    def _onchange_origin_location_id(self):
        if self.origin_location_id.partner_id and self.destination_location_id.partner_id:
            raise UserError(_('Product re-location is not allowed.\n'
                              'You should not initiate direct transfers between locations with different owners.\n'
                              'Please, first return the products to the main warehouse and then create a second '
                              'operation from the main warehouse to the final destination!'))
        # if self.origin_location_id.partner_id:
        #     self.owner_id = self.origin_location_id.partner_id
        #     res = {'domain': {'owner_id': [('id', '=', self.origin_location_id.partner_id.id)]}}
        # else:
        #     res = {'domain': {'owner_id': []}}
        # for line in self.stock_move_location_line_ids:
        #     line.location_id = self.origin_location_id
        #     qty_todo, qty_done, exclude_product_uom_qty = line._get_available_quantity()
        #     line.max_quantity = qty_todo
        # _logger.info("RES origin_location_id %s" % res)
        # return res

    @api.onchange('destination_location_id')
    def _onchange_destination_location_id(self):
        if self.origin_location_id.partner_id and self.destination_location_id.partner_id:
            raise UserError(_('Product re-location is not allowed.\n'
                              'You should not initiate direct transfers between locations with different owners.\n'
                              'Please, first return the products to the main warehouse and then create a second '
                              'operation from the main warehouse to the final destination!'))
        # if self.destination_location_id.partner_id:
        #     self.owner_id = self.destination_location_id.partner_id
        #     res = {'domain': {'owner_id': [('id', '=', self.destination_location_id.partner_id.id)]}}
        # else:
        #     res = {'domain': {'owner_id': []}}
        # for line in self.stock_move_location_line_ids:
        #     line.location_dest_id = self.destination_location_id
        #     qty_todo, qty_done, exclude_product_uom_qty = line._get_available_quantity()
        #     line.max_quantity = qty_todo
        #     line.exclude_product_uom_qty = exclude_product_uom_qty
        # _logger.info("RES destination_location_id %s" % res)
        # return res

    @api.onchange('filter_location_id')
    def _onchange_filter_location_id(self):
        if self.filter_location_id:
            self.onchange_sale_order_line_ids()

    @api.onchange('owner_id')
    def _onchange_owner_id(self):
        for line in self.stock_move_location_line_ids:
            line.owner_id = self.owner_id

    def _create_picking(self):
        origin = ":".join([x.name for x in self.product_ids])
        return self.env['stock.picking'].create({
            'picking_type_id': self.picking_type_id.id,
            'location_id': self.origin_location_id.id,
            'location_dest_id': self.destination_location_id.id,
            'owner_id': self.owner_id.id,
            'origin': origin,
        })

    @api.multi
    def group_lines(self):
        lines_grouped = {}
        stock_move_location_line_ids = self.filtered_move_location_line_ids
        # if self.product_type_ids:
        #     stock_move_location_line_ids = self.env['wiz.sale.stock.move.location.line']
        #     for line in self.filtered_move_location_line_ids:
        #         stock_move_location_line_ids |= line
        for line in stock_move_location_line_ids:
            lines_grouped.setdefault(
                line.product_id.id,
                self.env["wiz.sale.stock.move.location.line"].browse(),
            )
            lines_grouped[line.product_id.id] |= line
            # _logger.info("RES %s" % lines_grouped)
        return lines_grouped

    @api.multi
    def _create_moves(self, picking):
        self.ensure_one()
        groups = self.group_lines()
        moves = self.env["stock.move"]
        for lines in groups.values():
            move = self._create_move(picking, lines)
            moves |= move
        return moves

    def _get_move_values(self, picking, lines):
        # locations are same for the products
        location_from_id = self.origin_location_id.id
        location_to_id = self.destination_location_id.id
        product = lines[0].product_id
        product_uom_id = lines[0].product_uom.id
        qty = sum([x.real_product_uom_qty for x in lines])
        return {
            "name": product.display_name,
            "location_id": location_from_id,
            "location_dest_id": location_to_id,
            "product_id": product.id,
            "product_uom": product_uom_id,
            "product_uom_qty": qty,
            "picking_id": picking.id,
            # 'procure_method': 'make_to_order',
            'procure_method': 'make_to_stock',
        }

    @api.multi
    def _create_move(self, picking, lines):
        self.ensure_one()
        move = self.env["stock.move"].create(
            self._get_move_values(picking, lines),
        )
        if self.work_with_reservation:
            for line in lines:
                line.create_move_lines(picking, move)
                move._update_reserved_quantity(
                    line.product_uom_qty, line.max_quantity, line.origin_location_id,
                    lot_id=line.lot_id, package_id=line.package_id,
                    owner_id=line.owner_id and line.owner_id or line.owner_id, strict=True
                )
        return move

    @api.multi
    def _action_move_location(self, picking):
        self.ensure_one()
        picking._put_in_pack()

    def get_move_location_values(self, lines):
        if self.create_order_point:
            pass
        return {}

    @api.multi
    def action_move_location(self):
        self.ensure_one()
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.company_id.id)], limit=1)
        if len(self.production_ids.ids) == 0:
            if self.create_order_point:
                account_analytic_id = self.env['account.analytic.account']
                for sale_line in self.sale_order_line_ids:
                    account_analytic_id |= sale_line.sale_order_line_id.order_id.analytic_account_id
                if len(account_analytic_id.ids) > 1:
                    account_analytic_id = account_analytic_id[0]
                name = ', '.join(set([x.sale_order_line_id.order_id.name for x in self.sale_order_line_ids]))
                procurement_group_id = self.env['procurement.group'].create({
                    'name': name,
                    'move_type': 'direct',
                })
                inx = 0
                groups = self.group_lines()
                for product_id, lines in groups.items():
                    product = lines[0].product_id
                    qty = sum([x.real_product_uom_qty for x in lines if x.real_product_uom_qty > 0])
                    if qty > 0:
                        inx += 1
                        values = self.get_move_location_values(lines)
                        values.update({
                            'date_planned': fields.Date.today(),
                            'company_id': self.company_id,
                            'route_ids': product.route_ids,
                            'group_id': procurement_group_id,
                            'warehouse_id': warehouse,
                            'account_analytic_id': account_analytic_id.id,
                        })
                        self.env['procurement.group'].run(product,
                                                          qty,
                                                          product.product_tmpl_id.uom_id,
                                                          warehouse.lot_stock_id,
                                                          inx == 1 and name or '',
                                                          inx == 1 and name or '',
                                                          values)
        else:
            picking = self._create_picking()
            self._create_moves(picking)
            picking.action_confirm()
            if self.work_with_reservation:
                picking.with_context(dict(self._context, block_putaway_strategy=True)).action_assign()
            if any([x for x in self.filtered_move_location_line_ids if x.package_id]):
                self._action_move_location(picking)
            self.picking_id = picking

            if self.create_order_point:
                # products_qty = {}
                move_lines = self.picking_id.mapped('move_lines')
                product_ids = move_lines.mapped('product_id')
                # _logger.info("action_move_location %s:%s" % (sale_order_id, product_ids))
                order_template = self.env['stock.warehouse.orderpoint.template']. \
                    create_sale_order_auto_orderpoints(product_ids, sale_order_id=False,
                                                       stock_picking_id=self.picking_id)
                order_template.auto_generate = False
            return self._get_picking_action(picking.id)

    def _get_picking_action(self, pickinig_id):
        action = self.env.ref("stock.action_picking_tree_all").read()[0]
        form_view = self.env.ref("stock.view_picking_form").id
        action.update({
            "view_mode": "form",
            "views": [(form_view, "form")],
            "res_id": pickinig_id,
        })
        return action

    def _get_group_quants(self, product_id=False, package_id=False):
        location_id = self.origin_location_id.id
        company = self.env['res.company']._company_default_get(
            'stock.inventory',
        )
        # Using sql as search_group doesn't support aggregation functions
        # leading to overhead in queries to DB
        if product_id and not package_id:
            where = "WHERE product_id = %s AND location_id = %s AND company_id = %s"
            args = (product_id, location_id, company.id)
        elif product_id and package_id:
            where = "WHERE product_id = %s AND location_id = %s AND package_id = %s AND company_id = %s"
            args = (product_id, location_id, package_id, company.id)
        else:
            where = "WHERE location_id = %s AND company_id = %s"
            args = (location_id, company.id)
        group = " GROUP BY product_id, package_id, lot_id"
        query = """SELECT product_id, package_id, lot_id, SUM(quantity)
            FROM stock_quant """ + where + group + """ ORDER BY product_id, package_id DESC"""
        # _logger.info("SQL %s" % query % args)
        self.env.cr.execute(query, args)
        return self.env.cr.dictfetchall()

    def _get_stock_move_location_lines_values(self):
        product_obj = self.env['product.product']
        product_data = []
        for group in self._get_group_quants():
            product = product_obj.browse(group.get("product_id")).exists()
            # Apply the put away strategy
            location_dest_id = \
                self.destination_location_id.get_putaway_strategy(
                    product).id or self.destination_location_id.id
            product_data.append({
                'product_id': product.id,
                'product_uom_qty': group.get("sum"),
                'max_quantity': group.get("sum"),
                'origin_location_id': self.origin_location_id.id,
                'destination_location_id': location_dest_id,
                'package_id': group.get("package_id") or False,
                'lot_id': group.get("lot_id") or False,
                'product_uom_id': product.uom_id.id,
                'move_location_wizard_id': self.id,
                'custom': False,
            })
        return product_data

    @api.multi
    def _add_lines(self, line_model):
        self.ensure_one()
        for line_val in self._get_stock_move_location_lines_values():
            if line_val.get('max_quantity') <= 0:
                continue
            line = line_model.create(line_val)
            line.onchange_product_id()

    @api.multi
    def add_lines(self):
        self.ensure_one()
        line_model = self.env["wiz.sale.stock.move.location.line"]
        self._add_lines(line_model)
        return {"type": "ir.actions.do_nothing"}

    def clear_lines(self):
        self.stock_move_location_line_ids = False
        return {
            "type": "ir.action.do_nothing",
        }
