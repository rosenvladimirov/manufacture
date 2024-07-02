# Copyright (C) 2011 Julius Network Solutions SARL <contact@julius.fr>
# Copyright 2018 Camptocamp SA
# Copyright 2019 Sergio Teruel - Tecnativa <sergio.teruel@tecnativa.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from itertools import groupby

import logging

_logger = logging.getLogger(__name__)


class MrpStockMoveLocationWizard(models.TransientModel):
    _name = "wiz.mrp.stock.move.location"

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
        comodel_name="wiz.mrp.stock.move.location.line",
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
    merge_qty = fields.Boolean(
        string='Merge MO',
        default=True
    )
    work_with_reservation = fields.Boolean(
        string='Work with reservation',
    )
    production_ids = fields.Many2many(
        comodel_name='mrp.production',
        string='Productions',
    )
    exclude_picking_ids = fields.Many2many(
        string="Excluded Pickings",
        comodel_name="stock.picking",
    )
    force_sale_order = fields.Boolean('Force sale order', help='If checked it, the system will create a sale order, '
                                                               'when work with Subcontractor, is needed to make '
                                                               'Commercial invoice')

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
        res = super(MrpStockMoveLocationWizard, self).default_get(fields_list)
        manufacture_route = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
        productions = False
        moves = []
        if self._context.get('active_ids'):
            productions = self.env['mrp.production'].browse(self._context['active_ids'])

        if not productions:
            productions = self.production_ids

        if not productions:
            return res
        # if not self._context.get('move_semi_product'):
        res['production_ids'] = [(6, False, productions.ids)]
        move_raw_ids = productions.mapped('move_raw_ids')
        if res.get('merge_qty', False) or self.merge_qty:
            move_new_ids = self.env['stock.move']
            for operation_product_id, group_moves in groupby(move_raw_ids.sorted(lambda r: "%s-%s" % (r.operation_id.id, r.product_id.id)), lambda r: "%s-%s" % (r.operation_id.id, r.product_id.id)):
                copy_group_moves = list(group_moves)
                # convert from uom factor FIX in FUTURE !!!!!
                sum_moves = sum(x.product_uom_qty for x in copy_group_moves)
                # copy_group_moves[0]._convert_to_write(copy_group_moves[0]._cache)
                move_line = copy_group_moves[0]
                production = move_line.raw_material_production_id
                new_move = self.env['stock.move'].new({
                    'sequence': move_line.sequence,
                    'name': production.name,
                    'date': production.date_planned_start,
                    # 'date_expected': production.date_planned_start,
                    'product_id': move_line.product_id.id,
                    'product_uom_qty': move_line.product_uom_qty,
                    'product_uom': move_line.product_uom.id,
                    'location_id': move_line.location_id.id,
                    'location_dest_id': res.get('destination_location_id') and res['destination_location_id'] or move_line.location_dest_id.id,
                    'company_id': production.company_id.id,
                    'operation_id': move_line.operation_id.id,
                    'price_unit': move_line.price_unit,
                    'origin': production.name,
                    'warehouse_id': move_line.location_id.get_warehouse().id,
                    'unit_factor': move_line.unit_factor,
                })
                new_move.product_uom_qty = sum_moves
                move_new_ids |= new_move
            move_raw_ids = move_new_ids
        for move in move_raw_ids:
            vals = self._copy_move_line(move, productions=productions)
            moves.append((0, False, vals))
            # _logger.info("LINE %s(%s)" % (move.procure_method, manufacture_route.id in move.product_id.mapped('route_ids').ids))
            # if not self._context.get('move_semi_product') \
            #         and manufacture_route.id not in move.product_id.mapped('route_ids').ids:
            #     vals = self._copy_move_line(move, productions=productions)
            #     moves.append((0, False, vals))
            # if self._context.get('move_semi_product') \
            #         and manufacture_route.id in move.product_id.mapped('route_ids').ids:
            #     vals = self._copy_move_line(move, productions=False)
            #     moves.append((0, False, vals))

        if moves:
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.user.company_id.id)], limit=1)
            if warehouse:
                res['origin_location_id'] = warehouse.lot_stock_id.id
            if not res.get('destination_location_id'):
                res['destination_location_id'] = productions[0].location_dest_id.id
            if self._context.get('move_semi_product'):
                origin_location_id_save = res['origin_location_id']
                res['origin_location_id'] = res['destination_location_id']
                res['destination_location_id'] = origin_location_id_save
            res['stock_move_location_line_ids'] = moves
        # _logger.info("RES %s" % res)
        return res

    def _copy_move_line(self, move_line, productions=False):
        production = move_line.raw_material_production_id
        source_location = move_line.location_id
        dest_location = move_line.location_dest_id
        quant = self.env['stock.quant']

        if production.routing_id:
            routing = production.routing_id
        else:
            routing = production.bom_id.routing_id

        if not source_location and routing and routing.location_id:
            source_location = routing.location_id
        elif not dest_location:
            dest_location = production.location_src_id
        if self._context.get('move_semi_product'):
            source_location_save = source_location
            source_location = dest_location
            dest_location = source_location_save
        available_quantity = quant._get_available_quantity(move_line.product_id, move_line.location_dest_id, strict=True)
        total_quantity = 0.0
        warehouse_ids = self.env['stock.warehouse'].search([('company_id', '=', self.env.user.company_id.id)])
        for warehouse in warehouse_ids:
            total_quantity += quant._get_available_quantity(move_line.product_id, warehouse.lot_stock_id)
        return {
            'sequence': move_line.sequence,
            'name': production.name,
            'date': production.date_planned_start,
            'date_expected': production.date_planned_start,
            'product_id': move_line.product_id.id,
            'product_uom_qty': move_line.product_uom_qty,
            'real_product_uom_qty': move_line.product_uom_qty,
            'product_uom': move_line.product_uom.id,
            'location_id': source_location.id,
            'location_dest_id': dest_location.id,
            'company_id': production.company_id.id,
            'operation_id': move_line.operation_id.id,
            'price_unit': move_line.price_unit,
            'origin': production.name,
            'warehouse_id': source_location.get_warehouse().id,
            'unit_factor': move_line.unit_factor,
            'production_ids': productions and [(6, False, productions.ids)] or False,
            'total_quantity': available_quantity,
            'all_wh_total_quantity': total_quantity,
        }

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
        if self.origin_location_id:
            warehouse_id = self.origin_location_id.get_warehouse().id
            picking_type_id = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'), ('warehouse_id', '=', warehouse_id)
            ], limit=1).id
            if picking_type_id:
                self.picking_type_id = picking_type_id
        for line in self.stock_move_location_line_ids:
            line.location_id = self.origin_location_id
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
            qty_todo, qty_done, available_qty = line._get_available_quantity()
            line.max_quantity = qty_todo
            line.total_quantity = available_qty
        return res

    @api.onchange('owner_id')
    def _onchange_owner_id(self):
        for line in self.stock_move_location_line_ids:
            line.owner_id = self.owner_id

    @api.onchange('exclude_picking_ids')
    def _onchange_exclude_picking_ids(self):
        if len(self.exclude_picking_ids.ids) > 0:
            move_ids = self.exclude_picking_ids.mapped('move_lines')
            for group_id, lines in groupby(move_ids.sorted(lambda r: r.product_id.id), lambda r: r.product_id):
                exclude_lines = list(lines)
                stock_move_location_line_ids = self.stock_move_location_line_ids.\
                    filtered(lambda r: r.product_id == group_id)
                quantity_done = product_oum_qty = 0.0
                for line in exclude_lines:
                    quantity_done += line.quantity_done
                    product_oum_qty += line.product_uom_qty
                stock_move_location_line_ids.update({
                    'exclude_product_uom_qty': quantity_done > 0 and quantity_done or product_oum_qty,
                })

    def _get_locations_domain(self):
        return [('usage', '=', 'internal')]

    def _create_sale_order(self):
        partner_id = self.destination_location_id.out_partner_id
        addr = partner_id.address_get(['delivery', 'invoice'])
        values = {
            'partner_id': self.destination_location_id.out_partner_id.id,
            'pricelist_id': partner_id.property_product_pricelist and partner_id.property_product_pricelist.id or False,
            'payment_term_id': partner_id.property_payment_term_id and partner_id.property_payment_term_id.id or False,
            'partner_invoice_id': addr['invoice'],
            'partner_shipping_id': addr['delivery'],
            'user_id': partner_id.user_id.id or self.env.uid
        }
        if self.env['ir.config_parameter'].sudo().get_param('sale.use_sale_note') and self.env.user.company_id.sale_note:
            values['note'] = self.with_context(lang=partner_id.lang).env.user.company_id.sale_note

        if partner_id.team_id:
            values['team_id'] = partner_id.team_id.id
        return values

    @api.multi
    def _create_sale_order_lines(self, sale_order):
        self.ensure_one()
        groups = self.group_lines()
        sale_order_lines = self.env["sale.order.line"]
        for lines in groups.values():
            sale_order_line = self._create_sale_order_line(sale_order, lines)
            sale_order_lines |= sale_order_line
        return sale_order_lines

    @api.multi
    def _create_sale_order_line(self, sale_order, lines):
        self.ensure_one()
        sale_order_line = self.env["sale.order.line"].create(
            self._get_sale_order_line_values(sale_order, lines),
        )
        return sale_order_line

    @api.model
    def get_currency_amount(self, order, amount):
        if order.currency_id != order.company_id.currency_id:
            amount = order.company_id.currency_id.with_context(date=order.create_date). \
                compute(amount, order.pricelist_id.currency_id, round=False)
        return amount

    @api.model
    def get_unit_price(self, product_id, production_id):
        domain = [('product_id', '=', product_id.id)]
        if production_id:
            analytic_account_id = production_id.analytic_account_id
            domain.append(('account_analytic_id', '=', analytic_account_id.id))
        purchase_id = self.env['purchase.order.line'].search(domain, order='date_planned DESC', limit=1)

        if purchase_id:
            price_unit = purchase_id.price_unit
            order = purchase_id.order_id
            if purchase_id.taxes_id:
                price_unit = purchase_id.taxes_id.with_context(round=False).compute_all(
                    price_unit, currency=purchase_id.order_id.currency_id, quantity=1.0, product=purchase_id.product_id,
                    partner=purchase_id.order_id.partner_id
                )['total_excluded']
            if purchase_id.product_uom.id != purchase_id.product_id.uom_id.id:
                price_unit *= purchase_id.product_uom.factor / purchase_id.product_id.uom_id.factor
            if order.currency_id != order.company_id.currency_id:
                price_unit = order.currency_id.with_context(date=order.date_approve).\
                    compute(price_unit, order.company_id.currency_id, round=False)
        else:
            price_unit = product_id.standard_price
        return price_unit

    def _get_sale_order_line_values(self, sale_order, lines):
        # locations are same for the products
        # location_from_id = lines[0].origin_location_id.id
        # location_to_id = lines[0].destination_location_id.id
        product = lines[0].product_id
        product_uom_id = lines[0].product_uom.id
        production_id = lines[0].raw_material_production_id
        qty = sum([x.product_uom_qty - x.exclude_product_uom_qty for x in lines])
        product = product.with_context(
            lang=sale_order.partner_id.lang,
            partner=sale_order.partner_id.id,
            quantity=qty,
            date=sale_order.date_order,
            pricelist=sale_order.pricelist_id.id,
            uom=product_uom_id
        )
        name = product.name_get()[0][1]
        if product.description_sale:
            name += '\n' + product.description_sale

        fpos = sale_order.fiscal_position_id or sale_order.partner_id.property_account_position_id
        # If company_id is set, always filter taxes by the company
        taxes = product.taxes_id.filtered(lambda r: not sale_order.company_id or r.company_id == sale_order.company_id)
        tax_id = fpos.map_tax(taxes, product, sale_order.partner_shipping_id) if fpos else taxes
        price_unit = self.get_unit_price(product, production_id)
        price_unit = self.get_currency_amount(sale_order, price_unit)
        analytic_account_id = production_id.analytic_account_id
        if analytic_account_id != sale_order.analytic_account_id:
            sale_order.analytic_account_id = analytic_account_id
        group_id = sale_order.procurement_group_id
        if not group_id:
            group_id = self.env['procurement.group'].create({
                'name': sale_order.name,
                'move_type': sale_order.picking_policy,
                'sale_id': sale_order.id,
                'partner_id': sale_order.partner_shipping_id.id,
                'production_ids': [(6, False, self.production_ids.ids)],
                'location_dest_id': self.destination_location_id.id,
            })
            sale_order.procurement_group_id = group_id
        return {
            "name": name,
            "product_id": product.id,
            "product_uom": product_uom_id,
            "product_uom_qty": qty,
            "order_id": sale_order.id,
            "price_unit": price_unit,
            "tax_id": [(6, False, tax_id.ids)],
        }

    def _create_picking(self):
        name = {}
        sale = []
        origin = False
        for production in self.production_ids.sorted(lambda r: r.sale_id.id):
            if not name.get(production.sale_id):
                name[production.sale_id] = set([])
            name[production.sale_id].update([production.name])
        if name:
            origin = ':'.join(k and k.name or '' for k in name.keys())
        else:
            origin = ":".join([x.name for x in self.production_ids])
        return self.env['stock.picking'].create({
            'picking_type_id': self.picking_type_id.id,
            'location_id': self.origin_location_id.id,
            'location_dest_id': self.destination_location_id.id,
            'owner_id': self.owner_id.id,
            'origin': origin,
            'production_ids': [(6, False, self.production_ids.ids)],
        })

    @api.multi
    def group_lines(self):
        lines_grouped = {}
        for line in self.stock_move_location_line_ids:
            lines_grouped.setdefault(
                line.product_id.id,
                self.env["wiz.mrp.stock.move.location.line"].browse(),
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
        production_ids = self.production_ids
        qty = sum([x.product_uom_qty - x.exclude_product_uom_qty for x in lines])
        return {
            "name": product.display_name,
            "location_id": location_from_id,
            "location_dest_id": location_to_id,
            # 'owner_id': self.owner_id and self.owner_id.id or False,
            "product_id": product.id,
            "product_uom": product_uom_id,
            "product_uom_qty": qty,
            "picking_id": picking.id,
            # "location_move": True,
            'procure_method': 'make_to_stock',
            "production_ids": production_ids and [(6, False, production_ids.ids)] or False,
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
                    line.product_uom_qty - lines.exclude_product_uom_qty,
                    line.max_quantity,
                    line.origin_location_id,
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
        if self.force_sale_order:
            if self.destination_location_id.out_partner_id:
                sale_order_values = self._create_sale_order()
                sale_order = self.env['sale.order'].create(sale_order_values)
                self._create_sale_order_lines(sale_order)
                # for line in sale_order.order_line:
                #     if sale_order.pricelist_id and sale_order.partner_id:
                #         price_unit = self.env['account.tax']._fix_tax_included_price_company(
                #             line._get_display_price(line.product_id),
                #             line.product_id.taxes_id,
                #             line.tax_id,
                #             sale_order.company_id)
                #     else:
                #         price_unit = line._get_display_price(line.product_id)
                #     line.price_unit = price_unit
                return self._get_sale_order_action(sale_order.id)
        else:
            picking = self._create_picking()
            self._create_moves(picking)
            picking.action_confirm()
            picking.with_context(dict(self._context, block_putaway_strategy=True)).action_assign()
            if any([x for x in self.stock_move_location_line_ids if x.package_id]):
                self._action_move_location(picking)
            self.picking_id = picking
            if self.exclude_picking_ids:
                for line in self.exclude_picking_ids:
                    line.write({
                        'production_ids': [(6, False, list(set(line.production_ids.ids + self.production_ids.ids)))],
                    })

            return self._get_picking_action(picking.id)

    def _get_sale_order_action(self, sale_order_id):
        action = self.env.ref("sale.action_orders").read()[0]
        form_view = self.env.ref("sale.view_order_form").id
        action.update({
            "view_mode": "form",
            "views": [(form_view, "form")],
            "res_id": sale_order_id,
        })
        return action

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
            # Apply the putaway strategy
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
                # cursor returns None instead of False
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
        line_model = self.env["wiz.mrp.stock.move.location.line"]
        self._add_lines(line_model)
        return {
            "type": "ir.actions.do_nothing",
        }

    def clear_lines(self):
        self.stock_move_location_line_ids = False
        return {
            "type": "ir.action.do_nothing",
        }
