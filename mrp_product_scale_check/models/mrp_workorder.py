# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import time

from odoo import api, fields, models, _
from odoo.addons.product_scale_check.models.server import WORKERS
from odoo.exceptions import UserError


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    scale_done = fields.Boolean(string='Weight check', copy=False)
    current_weight = fields.Float(string='Current weight', copy=False)
    scale_id = fields.Many2one(comodel_name='product.scale.check', string='Scale')

    def weight_action(self):
        if self.scale_id:
            self.current_weight = 0.0
            self.scale_done = False
            scale_ip_address = self.scale_id.scale_ip_address
            self.scale_id._prepare_weight_scale(self.product_id.pattern_weight, self.product_id.tolerance)
            if WORKERS.get(scale_ip_address):
                WORKERS[scale_ip_address].update({
                    'scale_done': self.scale_done,
                    'checked_weight': self.current_weight,
                })
                start = time.time()
                while not self.scale_done:
                    if time.time() - start >= 15:
                        break
                    self.current_weight = WORKERS[scale_ip_address]['checked_weight']
                    if WORKERS[scale_ip_address].get('scale_done', False):
                        self.scale_done = WORKERS[scale_ip_address]['scale_done']
                    else:
                        time.sleep(2)
                if scale_ip_address and WORKERS.get(scale_ip_address):
                    WORKERS[scale_ip_address]['scale'].kill()

    def _post_record_production(self):
        res = super(MrpWorkorder, self)._post_record_production()
        final_move_ids = self.move_line_ids.filtered(
            lambda move_line: not move_line.done_move and move_line.lot_produced_id.id == self.final_lot_id.id and move_line.qty_done > 0)
        final_move_ids.write({
            'scale_done': self.scale_done,
            'current_weight': self.current_weight,
        })
        return res

    @api.multi
    def record_production(self):
        for record in self:
            if record.product_id.pattern_weight and not record.scale_done and record.scale_id:
                raise UserError(_(f"Product scale check {record.product_id.pattern_weight} is wrong"))
        return super(MrpWorkorder, self).record_production()
