# coding: utf-8
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _

import logging

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MrpWorkOrderAuto(models.TransientModel):
    _name = 'mrp.workorder.auto'
    _description = 'Auto import in final lots'
    # _inherit = ['barcodes.barcode_events_mixin']

    workorder_id = fields.Many2one('mrp.workorder', 'Manufacture Workorder')
    production_id = fields.Many2one('mrp.production', 'Manufacture order')
    lot_ids = fields.Many2many('stock.production.lot', string='SN/Lots')
    import_workorder_id = fields.Many2one('mrp.workorder', 'Manufacture Workorder')

    @api.model
    def default_get(self, default_fields):
        res = super(MrpWorkOrderAuto, self).default_get(default_fields)
        workorder_id = False
        if res.get('workorder_id', False):
            workorder_id = self.env['mrp.workorder'].browse(res['workorder_id'])
        if not workorder_id:
            workorder_id = self.env['mrp.workorder'].browse(self._context['active_id'])
        if workorder_id:
            res['workorder_id'] = workorder_id.id
            res['production_id'] = workorder_id.production_id.id
        return res

    @api.multi
    def generate_lots(self):
        lot_obj = self.env['stock.production.lot']
        for record in self:
            trust_lots = record.workorder_id.production_finished_move_line_ids.mapped('lot_id')
            check_lots = record.import_workorder_id.production_finished_move_line_ids.mapped('lot_id')
            # _logger.info(f"Trust lots {trust_lots}\nCheck lots {check_lots}")
            check_lots |= record.production_id.move_raw_ids.mapped('move_line_ids').\
                filtered(lambda r: r.workorder_id.id == record.import_workorder_id.id).mapped('lot_produced_id')
            for lot_id in check_lots:
                # _logger.info(f"Lot {lot_id.id} {lot_id.name not in trust_lots.mapped('name')} not in {trust_lots.mapped('name')}")
                if lot_id.id not in trust_lots.ids:
                    self.lot_ids |= lot_id
        return {
            'type': 'ir.actions.do_nothing'
        }

    @api.multi
    def generate_auto(self):
        self.ensure_one()
        if self._context.get('active_model') == 'mrp.workorder' and self._context.get('active_ids'):
            workorder = self.env['mrp.workorder'].browse(self._context['active_ids'])
        else:
            workorder = self.workorder_id

        if workorder and workorder.product_tracking:
            if workorder.working_state != 'blocked':
                for lot_id in self.lot_ids:
                    workorder.qty_producing = 1.0
                    workorder.button_empty_bins()
                    workorder.button_start()
                    if workorder.product_tracking:
                        workorder.on_barcode_scanned(lot_id.name)
                    _logger.info(
                        _('Put for produce %s in work order %s' % (workorder.qty_producing, workorder.name)))
                    try:
                        workorder.record_production()
                    except ValueError:
                        _logger.info(_('Error when validate work order'))
            else:
                raise UserError(_('The work order %s in state %s') %
                                (workorder.name, workorder.working_state))
        else:
            return {'type': 'ir.actions.act_window_close'}
