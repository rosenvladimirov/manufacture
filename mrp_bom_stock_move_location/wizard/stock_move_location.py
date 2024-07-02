# Copyright (C) 2011 Julius Network Solutions SARL <contact@julius.fr>
# Copyright 2018 Camptocamp SA
# Copyright 2019 Sergio Teruel - Tecnativa <sergio.teruel@tecnativa.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from itertools import groupby

import logging

_logger = logging.getLogger(__name__)


class BOMStockMoveLocationWizard(models.TransientModel):
    _name = "wiz.bom.stock.move.location"
    _description = "Wizard for create picking from product boms"
    # _inherit = ['multi.step.wizard.mixin']

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
        comodel_name="wiz.bom.stock.move.location.line",
        inverse_name="move_location_wizard_id",
    )
    bom_line_ids = fields.One2many(
        string="Bom lines",
        comodel_name="wiz.bom.line",
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
    product_qty = fields.Float(
        string='For quantity',
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
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
    )

    @api.depends('edit_locations')
    def _compute_readonly_locations(self):
        for rec in self:
            rec.origin_location_disable = self.env.context.get(
                'origin_location_disable', False)
            if not rec.edit_locations:
                rec.origin_location_disable = True
                rec.destination_location_disable = True
                rec.destination_owner_disable = True

    @api.model
    def default_get(self, fields_list):
        res = super(BOMStockMoveLocationWizard, self).default_get(fields_list)
        manufacture_route = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
        moves = []
        products = False
        products_tmpl = False
        company_id = self.env.user.company_id
        res['company_id'] = company_id.id
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company_id.id)], limit=1)
        mrp_warehouse = self.env['stock.warehouse'].search([('company_id', '=', company_id.id),
                                                            ('manufacture_to_resupply', '=', True)], limit=1)
        location_dest_id = mrp_warehouse.lot_stock_id
        _logger.info("INFO %s:%s" % (res, self._context))
        # if res.get('product_ids'):
        #     products = self.env['product.product'].browse(res['product_ids'][0][2])
        if self._context.get('active_ids') and self._context.get('active_model') == 'product.product':
            products = self.env['product.product'].browse(self._context['active_ids'])
        if products and not res.get('product_ids'):
            res['product_ids'] = [(6, False, products.ids)]
            res['product_tmpl_ids'] = [(6, False, products.mapped('product_tmpl_id').ids)]
        # if res.get('product_tmpl_ids'):
        #     products_tmpl = self.env['product.template'].browse(res['product_tmpl_ids'][0][2])
        if self._context.get('active_ids') \
                and self._context.get('active_model') == 'product.template':
            products_tmpl = self.env['product.template'].browse(self._context['active_ids'])
        if products_tmpl:
            res['product_tmpl_ids'] = [(6, False, products_tmpl.ids)]
            products = self.env['product.product']
            for product in products_tmpl:
                products |= product.mapped('product_variant_ids')

        # _logger.info("INFO 1 %s:%s" % (products_tmpl, products))
        move_raw_ids = self.env['stock.move']
        new_bom_ids = self.env['mrp.bom']
        move_new_ids = self.env['stock.move']
        for product in products:
            bom = self.env['mrp.bom']._bom_find(product=product, company_id=company_id.id)
            if not bom:
                bom = self.env['mrp.bom']._bom_find(product_tmpl=product.product_tmpl_id, company_id=company_id.id)
            new_bom_ids |= bom
            # _logger.info("BOM %s" % bom.product_tmpl_id)
            factor = product.uom_id._compute_quantity(1.0, bom.product_uom_id) / bom.product_qty
            boms, exploded_lines = bom.explode(product, factor, picking_type=bom.picking_type_id)
            # bom_raw_ids = bom.mapped('bom_line_ids')
            if bom.routing_id:
                location_id = bom.routing_id.location_id
            else:
                location_id = warehouse.lot_stock_id
            for bom_line, line_data in exploded_lines:
                new_move = self.env['stock.move'].new({
                    'sequence': bom_line.sequence,
                    'name': product.name,
                    'product_id': bom_line.product_id.id,
                    'product_uom_qty': line_data['qty'],
                    'product_uom': bom_line.product_uom_id.id,
                    'location_id': location_id.id,
                    'location_dest_id': location_dest_id.id,
                    'company_id': company_id.id,
                    # 'origin': "Force transfer %s" % product.name,
                    'warehouse_id': warehouse.id,
                    'procure_method': 'make_to_stock',
                    'bom_line_id': bom_line.id,
                })
                # new_move.product_uom_qty = sum_moves
                # _logger.info("LINE %s" % new_move)
                move_new_ids |= new_move
        move_raw_ids |= move_new_ids
        for move in move_raw_ids:
            if move.procure_method != 'make_to_order' \
                    and manufacture_route.id not in move.product_id.mapped('route_ids').ids:
                vals = self._copy_move_line(move, warehouse.lot_stock_id, location_dest_id, company_id)
                moves.append((0, False, vals))

        if moves:
            if warehouse:
                res['origin_location_id'] = warehouse.lot_stock_id.id
            if mrp_warehouse:
                res['destination_location_id'] = location_dest_id.id
            if new_bom_ids:
                res['bom_ids'] = [(6, False, new_bom_ids.ids)]
            res['bom_line_ids'] = moves
        # _logger.info("RES %s" % res)
        return res

    def _copy_move_line(self, move_line, source_location, destination_location, company_id):
        available_quantity = self.env['stock.quant']._get_available_quantity(move_line.product_id, destination_location)
        return {
            'sequence': move_line.sequence,
            'name': move_line.name,
            'product_id': move_line.product_id.id,
            'product_uom_qty': move_line.product_uom_qty,
            'product_uom': move_line.product_uom.id,
            'location_id': source_location.id,
            'location_dest_id': destination_location.id,
            'company_id': company_id.id,
            # 'operation_id': move_line.operation_id.id,
            'price_unit': move_line.price_unit,
            # 'origin': move_line.origin,
            'warehouse_id': source_location.get_warehouse().id,
            'bom_line_id': move_line.bom_line_id.id,
            'exclude_product_uom_qty': available_quantity,
        }

    @api.model
    def _group_product(self):
        stock_move_location_line_ids = self.env['wiz.bom.stock.move.location.line']
        for group, lines in groupby( self.bom_line_ids.sorted(lambda r: r.product_id.id), lambda r: r.product_id):
            new_lines = list(lines)
            new_line = new_lines[0]
            stock_move_location_line_ids |= self.env['wiz.bom.stock.move.location.line'].new({
                'product_id': group.id,
                'product_uom_qty': sum([x.product_uom_qty for x in new_lines]),
                'product_uom': new_line.product_uom.id,
                'sequence': new_line.sequence,
                'name': new_line.name,
                'location_id': new_line.location_id.id,
                'location_dest_id': new_line.location_dest_id.id,
                'company_id': new_line.company_id.id,
                'price_unit': new_line.price_unit,
                'origin': "Force transfer %s" % group.name,
                'warehouse_id': new_line.warehouse_id.id,
                # 'bom_line_id': new_line.bom_line_id.id,
            })
        return stock_move_location_line_ids

    @api.onchange('product_qty')
    def _onchange_product_qty(self):
        if self.product_qty > 0.0:
            self.stock_move_location_line_ids = False
            for product in self.product_ids:
                bom = self.bom_ids. \
                    filtered(lambda r: r.product_id == product and r.product_tmpl_id == product.product_tmpl_id)
                if not bom:
                    bom = self.bom_ids.filtered(lambda r: r.product_tmpl_id == product.product_tmpl_id)
                factor = product.uom_id._compute_quantity(self.product_qty, bom.product_uom_id) / bom.product_qty
                boms, exploded_lines = bom.explode(product, factor, picking_type=bom.picking_type_id)
                # _logger.info("QTY %s:%s:%s" % (product, boms, exploded_lines))
                for bom_line, line_data in exploded_lines:
                    for move_line in self.bom_line_ids.filtered(lambda r: r.bom_line_id == bom_line):
                        move_line.product_uom_qty = line_data['qty']
            self.stock_move_location_line_ids = self._group_product()
        else:
            self.stock_move_location_line_ids = self._group_product()

    @api.onchange('origin_location_id')
    def _onchange_origin_location_id(self):
        if self.origin_location_id.partner_id and self.destination_location_id.partner_id:
            raise UserError(_('Product re-location is not allowed.\n'
                              'You should not initiate direct transfers between locations with different owners.\n'
                              'Please, first return the products to the main warehouse and then create a second '
                              'operation from the main warehouse to the final destination!'))
        if self.origin_location_id.partner_id:
            self.owner_id = self.origin_location_id.partner_id
            res = {'domain': {'owner_id': [('id', '=', self.origin_location_id.partner_id.id)]}}
        else:
            res = {'domain': {'owner_id': []}}
        for line in self.stock_move_location_line_ids:
            line.location_id = self.origin_location_id
            qty_todo, qty_done, exclude_product_uom_qty = line._get_available_quantity()
            line.max_quantity = qty_todo
        return res

    @api.onchange('destination_location_id')
    def _onchange_destination_location_id(self):
        if self.origin_location_id.partner_id and self.destination_location_id.partner_id:
            raise UserError(_('Product re-location is not allowed.\n'
                              'You should not initiate direct transfers between locations with different owners.\n'
                              'Please, first return the products to the main warehouse and then create a second '
                              'operation from the main warehouse to the final destination!'))
        if self.destination_location_id.partner_id:
            self.owner_id = self.destination_location_id.partner_id
            res = {'domain': {'owner_id': [('id', '=', self.destination_location_id.partner_id.id)]}}
        else:
            res = {'domain': {'owner_id': []}}
        for line in self.stock_move_location_line_ids:
            line.location_dest_id = self.destination_location_id
            qty_todo, qty_done, exclude_product_uom_qty = line._get_available_quantity()
            line.max_quantity = qty_todo
            line.exclude_product_uom_qty = exclude_product_uom_qty
        return res

    @api.onchange('owner_id')
    def _onchange_owner_id(self):
        for line in self.stock_move_location_line_ids:
            line.owner_id = self.owner_id

    def _get_locations_domain(self):
        return [('usage', '=', 'internal')]

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
        for line in self.stock_move_location_line_ids:
            lines_grouped.setdefault(
                line.product_id.id,
                self.env["wiz.bom.stock.move.location.line"].browse(),
            )
            lines_grouped[line.product_id.id] |= line
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

    @api.multi
    def action_move_location(self):
        self.ensure_one()
        picking = self._create_picking()
        self._create_moves(picking)
        picking.action_confirm()
        picking.with_context(dict(self._context, block_putaway_strategy=True)).action_assign()
        if any([x for x in self.stock_move_location_line_ids if x.package_id]):
            self._action_move_location(picking)
        self.picking_id = picking
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
        line_model = self.env["wiz.bom.stock.move.location.line"]
        self._add_lines(line_model)
        return {
            "type": "ir.actions.do_nothing",
        }

    def clear_lines(self):
        self.stock_move_location_line_ids = False
        return {
            "type": "ir.action.do_nothing",
        }
