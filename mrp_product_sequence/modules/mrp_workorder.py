# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    toggle_block = fields.Boolean('Block toggle work_component')

    @api.multi
    def toggle_work_component(self):
        for record in self:
            if not record.toggle_block:
                super().toggle_work_component()

    @api.model
    def create(self, values):
        if 'product_id' in values:
            product_id = self.env['product.product'].browse(values['product_id'])
            if product_id.lot_sequence_id:
                values['toggle_block'] = True
                values['work_component'] = True
        return super().create(values)

    def _check_component(self, product, qty=1.0, lot=False, code=False, use_date=False, work_production=False):
        res = super()._check_component(product, qty=qty, lot=lot, code=code, use_date=use_date, work_production=work_production)
        if res and not self.final_lot_id and self.product_id.lot_sequence_id:
            lot_id = self.env['stock.production.lot'].create(self._check_product_create(
                self.product_id.lot_sequence_id._next(),
                self.product_id, False))
            self.final_lot_id = lot_id
        return res

    def _generate_lot_ids(self):
        super()._generate_lot_ids()
        if self.product_id.lot_sequence_id:
            lot_id = self.env['stock.production.lot'].create(self._check_product_create(
                self.product_id.lot_sequence_id._next(),
                self.product_id, False))
            self.final_lot_id = lot_id
