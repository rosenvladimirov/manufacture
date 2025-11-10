from odoo import models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    from odoo import models

    class StockLot(models.Model):
        _inherit = 'stock.lot'

        def action_view_bom_lots(self):
            """Action за показване на BOM-овете за лота"""
            self.ensure_one()

            bom_lot_ids = self.env['mrp.bom.lot'].search([('lot_id', '=', self.id)])

            action = {
                'name': f'BOM за {self.name}',
                'type': 'ir.actions.act_window',
                'res_model': 'mrp.bom.lot',
                'view_mode': 'list,form',
                'domain': [('lot_id', '=', self.id)],
                'context': {
                    'default_lot_id': self.id,
                    'default_product_id': self.product_id.id,
                    'default_product_tmpl_id': self.product_id.product_tmpl_id.id,
                }
            }

            # Ако има точно един BOM, отвори директно form view
            if len(bom_lot_ids) == 1:
                action['view_mode'] = 'form'
                action['res_id'] = bom_lot_ids[0].id

            return action

