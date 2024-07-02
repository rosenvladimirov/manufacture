# Copyright (C) 2011 Julius Network Solutions SARL <contact@julius.fr>
# Copyright 2018 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from odoo import _, api, fields, models
from odoo.addons import decimal_precision as dp
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_compare

import logging
_logger = logging.getLogger(__name__)


class MrpStockMoveLocationWizardLine(models.TransientModel):
    _name = "wiz.mrp.stock.move.location.line"

    move_location_wizard_id = fields.Many2one(
        string="Move location Wizard",
        comodel_name="wiz.mrp.stock.move.location",
        ondelete="cascade",
        required=True,
    )
    sequence = fields.Integer(
        string="Sequence",
    )
    name = fields.Char(
        string="Name",
    )
    date = fields.Datetime(
        string=""
    )
    bom_line_id = fields.Many2one(
        string="Bom line",
        comodel_name="mrp.bom.line",
    )
    product_id = fields.Many2one(
        string="Product",
        comodel_name="product.product",
        required=True,
    )
    location_id = fields.Many2one(
        string='Origin Location',
        comodel_name='stock.location',
    )
    location_dest_id = fields.Many2one(
        string='Destination Location',
        comodel_name='stock.location',
    )
    owner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Owner',
        help="Owner of the quants"
    )
    product_uom = fields.Many2one(
        string='Product Unit of Measure',
        comodel_name='product.uom',
    )
    package_id = fields.Many2one(
        comodel_name='stock.quant.package', string='Package',
        groups="stock.group_tracking_lot"
    )
    lot_id = fields.Many2one(
        string='Lot/Serial Number',
        comodel_name='stock.production.lot',
        domain="[('product_id','=',product_id)]"
    )
    exclude_product_uom_qty = fields.Float(
        string="Exclude Quantity to move",
        digits=dp.get_precision('Product Unit of Measure'),
    )
    total_quantity = fields.Float(
        string="Total Avalibity Quantity in destination location",
        digits=dp.get_precision('Product Unit of Measure'),
    )
    all_wh_total_quantity = fields.Float(
        string="Total Avalibity Quantity in all Warehouse",
        digits=dp.get_precision('Product Unit of Measure'),
    )
    product_uom_qty = fields.Float(
        string="Quantity to move",
        digits=dp.get_precision('Product Unit of Measure'),
    )
    real_product_uom_qty = fields.Float(
        string="Real Quantity to move",
        digits=dp.get_precision('Product Unit of Measure'),
        compute="_compute_real_product_uom_qty",
    )
    max_quantity = fields.Float(
        string="Max quantity to move",
        digits=dp.get_precision('Product Unit of Measure'),
    )
    raw_material_production_id = fields.Many2one(
        string="Production",
        comodel_name="mrp.production",
    )
    company_id = fields.Many2one(
        string="Company",
        comodel_name="res.company",
    )
    operation_id = fields.Many2one(
        string="Operation To Consume",
        comodel_name="mrp.routing.workcenter",
    )
    price_unit = fields.Float(
        string="Unit price"
    )
    procure_method = fields.Selection([
        ('make_to_stock', 'Default: Take From Stock'),
        ('make_to_order', 'Advanced: Apply Procurement Rules')],
        string='Supply Method',
    )
    origin = fields.Char(
        string="Ref"
    )
    warehouse_id = fields.Many2one(
        string="Warehouse",
        comodel_name="stock.warehouse",
    )
    group_id = fields.Many2one(
        string="Procurement",
        comodel_name="procurement.group"
    )
    custom = fields.Boolean(
        string="Custom line",
        default=True,
    )
    propagate = fields.Boolean(
        string='Propagate cancel and split',
        default=True,
    )
    unit_factor = fields.Float(
        string="Unit Factor",
    )
    lot_ids = fields.One2many(
        string='Available Lot/Serial Number',
        comodel_name='stock.production.lot',
        compute="_compute_lot_ids",
    )
    production_ids = fields.Many2many(
        comodel_name='mrp.production',
        string='Productions',
    )

    @staticmethod
    def _compare(qty1, qty2, precision_rounding):
        return float_compare(qty1, qty2, precision_rounding=precision_rounding)

    @api.constrains("max_quantity", "product_uom_qty")
    def _constraint_max_product_uom_qty(self):
        for record in self:
            if record.move_location_wizard_id.work_with_reservation:
                rounding = record.product_uom.rounding
                move_qty_gt_max_qty = self._compare(record.product_uom_qty, record.max_quantity, rounding) == 1
                move_qty_lt_0 = self._compare(record.product_uom_qty, 0.0, rounding) == -1
                if (move_qty_gt_max_qty or move_qty_lt_0):
                    raise ValidationError(_("Move quantity can not exceed max quantity or be negative"))

    @api.multi
    def _compute_lot_ids(self):
        for record in self:
            wiz = record.move_location_wizard_id
            search_args = [
                ('location_id', '=', wiz.origin_location_id.id),
                ('product_id', '=', record.product_id.id),
            ]
            quants = self.env['stock.quant'].search(search_args)
            record.lot_ids = [(6, 0, quants.mapped('lot_id').ids)]

    @api.multi
    @api.depends('product_uom_qty', 'exclude_product_uom_qty')
    def _compute_real_product_uom_qty(self):
        for record in self:
            record.real_product_uom_qty = record.product_uom_qty - record.exclude_product_uom_qty

    @api.onchange('product_id', 'lot_id', 'package_id')
    def onchange_product_id(self):
        if self.move_location_wizard_id.work_with_reservation:
            self.product_uom = self.product_id.uom_id
            wiz = self.move_location_wizard_id
            search_args = [
                ('location_id', '=', wiz.origin_location_id.id),
                ('product_id', '=', self.product_id.id),
            ]
            if self.lot_id:
                search_args.append(('lot_id', '=', self.lot_id.id))
            else:
                search_args.append(('lot_id', '=', False))
            if self.package_id:
                search_args.append(('package_id', '=', self.package_id.id))
            res = self.env['stock.quant'].read_group(search_args, ['quantity'], [])
            max_quantity = res[0]['quantity']
            self.max_quantity = max_quantity
            self.location_id = wiz.origin_location_id
            self.destination_location_id = wiz.destination_location_id
            self.owner_id = wiz.owner_id
            # if not self.product_set_id:
            #     self.product_set_id = wiz.product_set_id
            quants = self.env['stock.quant'].search(search_args[:-1])
            lots = quants.mapped('lot_id')
            owners = False
            if self.lot_id:
                owners = quants.filtered(lambda r: r.lot_id.id == self.lot_id.id).mapped('owner_id')
            if owners and self.lot_id:
                if len(owners.ids) > 1:
                    raise UserError("There is more than one lot/SN of consignment ...")
                elif len(owners.ids) == 1:
                    self.owner_id = owners
            # _logger.info("LOTS %s:%s" % (quants, lots.ids))
            return {'domain': {'lot_id': [('id', 'in', lots.ids)]}}
        return {}

    def create_move_lines(self, picking, move):
        for line in self:
            values = line._get_move_line_values(picking, move)
            if values.get("qty_done") <= 0:
                continue
            self.env["stock.move.line"].create(
                values
            )
        return True

    @api.multi
    def _get_move_line_values(self, picking, move):
        self.ensure_one()
        qty_todo, qty_done, total_quantity = self._get_available_quantity()
        return {
            "product_id": self.product_id.id,
            "lot_id": self.lot_id.id,
            "location_id": self.location_id.id,
            "location_dest_id": self.location_dest_id.id,
            "owner_id": self.owner_id.id,
            'package_id': self.package_id.id,
            "product_uom_qty": qty_done,
            "qty_done": qty_done,
            "product_uom_id": self.product_uom.id,
            "picking_id": picking.id,
            "move_id": move.id,
            # "exclude_product_uom_qty": exclude_product_uom_qty,
        }

    def _get_available_quantity(self):
        """We check here if the actual amount changed in the stock.

        We don't care about the reservations but we do care about not moving
        more than exists."""
        self.ensure_one()
        if not self.product_id:
            return 0, 0, 0
        if self.env.context.get("planned"):
            # for planned transfer we don't care about the amounts at all
            return self.product_uom_qty, 0, 0
        search_args = [
            ('location_id', '=', self.location_id.id),
            ('product_id', '=', self.product_id.id),
        ]
        if self.lot_id:
            search_args.append(('lot_id', '=', self.lot_id.id))
        else:
            search_args.append(('lot_id', '=', False))
        res = self.env['stock.quant'].read_group(search_args, ['quantity'], [])
        available_qty = res[0]['quantity']
        if not available_qty:
            # if it is immediate transfer and product doesn't exist in that
            # location -> make the transfer of 0.
            return 0, 0, 0
        rounding = self.product_uom.rounding
        available_qty_lt_move_qty = self._compare(
            available_qty, self.product_uom_qty - self.exclude_product_uom_qty, rounding) == -1
        if available_qty_lt_move_qty:
            return self.product_uom_qty, self.real_product_uom_qty, available_qty
        return 0, self.product_uom_qty - self.exclude_product_uom_qty, available_qty
