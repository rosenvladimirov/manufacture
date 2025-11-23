from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MrpBomLotLine(models.Model):
    _name = 'mrp.bom.lot.line'
    _description = 'BOM line for Lot/Serial number'
    _order = 'sequence, id'

    bom_lot_id = fields.Many2one(
        'mrp.bom.lot',
        string='BOM for lot',
        required=True,
        ondelete='cascade',
        index=True
    )
    master_bom_line_id = fields.Many2one(
        'mrp.bom.line',
        string='Original line from BOM',
        required=False,
        ondelete='restrict'
    )
    product_id = fields.Many2one(
        'product.product',
        string='Component',
        required=True
    )
    product_qty = fields.Float(
        string='Quantity',
        required=True,
        default=1.0
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of measure',
        required=True
    )
    stage_id = fields.Many2one(
        'mrp.bom.stage',
        string='Stage',
        help='Stage of production in which the component is used'
    )
    sequence = fields.Integer(string='Последователност', default=10)
    notes = fields.Char(string='Бележки')

    master_product_qty = fields.Float(
        string='Quantity (Master BOM)',
        related='master_bom_line_id.product_qty',
        readonly=True,
        help='Default quantity from master BOM'
    )
    qty_difference = fields.Float(
        string='Разлика',
        compute='_compute_qty_difference',
        store=True,
        help='Difference to Master BOM'
    )

    @api.depends('product_qty', 'master_product_qty')
    def _compute_qty_difference(self):
        """Изчисляване на разликата спрямо главния BOM"""
        for line in self:
            line.qty_difference = line.product_qty - line.master_product_qty

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Автоматично попълване на мерна единица"""
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id

    @api.constrains('master_bom_line_id', 'bom_lot_id')
    def _check_master_bom_line(self):
        """Проверка, че редът е от главния BOM"""
        for line in self:
            # Ако има master_bom_line_id, проверяваме дали е от правилния BOM
            if line.master_bom_line_id and line.master_bom_line_id.bom_id != line.bom_lot_id.master_bom_id:
                raise ValidationError(
                    'The line must be from the master BOM of this lot BOM!'
                )
