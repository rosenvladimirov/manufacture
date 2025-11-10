# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    bom_lot_id = fields.Many2one(
        'mrp.bom.lot',
        string='BOM for Lot/Serial number',
        help='BOM specific to lot/serial number',
        tracking=True
    )

    @api.onchange('lot_producing_id', 'product_id')
    def _onchange_lot_producing_id(self):
        """Автоматично зареждане на BOM за лот при избор на лот"""
        if self.lot_producing_id and self.product_id:
            # Търсене на потвърден BOM за този лот
            bom_lot = self.env['mrp.bom.lot'].search([
                ('lot_id', '=', self.lot_producing_id.id),
                ('product_id', '=', self.product_id.id),
                ('state', '=', 'confirmed')
            ], limit=1)

            if bom_lot:
                self.bom_lot_id = bom_lot
                return {
                    'warning': {
                        'title': _('BOM for lot found'),
                        'message': _('Found a BOM specific to this lot. '
                                     'Use the "Load Lot BOM" button'
                                     'to apply the adjusted amounts.')
                    }
                }

    def action_load_lot_bom(self):
        """Зареждане на количествата от BOM за лот"""
        self.ensure_one()

        if not self.bom_lot_id:
            raise UserError('Please select BOM for lot first!')

        if self.bom_lot_id.state != 'confirmed':
            raise UserError('Lot BOM must be confirmed!')

        # Актуализиране на количествата на материалите
        for move in self.move_raw_ids:
            # Намиране на съответния ред от BOM за лот
            lot_bom_line = self.bom_lot_id.line_ids.filtered(
                lambda l: l.product_id == move.product_id
            )

            if lot_bom_line:
                # Коригиране на количеството
                factor = self.product_qty / self.bom_lot_id.product_qty
                new_qty = lot_bom_line[0].product_qty * factor
                move.product_uom_qty = new_qty

        # Маркиране на BOM за лот като използван
        self.bom_lot_id.state = 'done'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Successfully'),
                'message': _('The quantities are adjusted according to the BOM for the lot'),
                'type': 'success',
                'sticky': False,
            }
        }
