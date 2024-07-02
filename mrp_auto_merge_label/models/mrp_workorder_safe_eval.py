# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _, tools
from odoo.tools import safe_eval

import logging
_logger = logging.getLogger(__name__)


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    @api.one
    def action_print_lot(self):
        ids = self.final_lot_id.ids
        ctx = self._context.copy()
        ctx['active_model'] = 'stock.production.lot'
        ctx['active_ids'] = ids
        docids = self.env['stock.production.lot'].browse(ids)
        return self.product_id.print_label_id.with_context(ctx).\
            report_action(docids, data={'model': 'stock.production.lot', 'ids': ids})

    def _post_record_production(self):
        if self.final_lot_id and self.product_id:
            if self.product_id.ref_lot:
                render_result = self.product_id.ref_lot
                pair_product_ids = self.product_id.ref_lot_pair_ids
                locals_dict = {
                    'object': self,
                }
                component_ids = self.production_id.move_raw_ids.filtered(lambda r: r.product_id.id in pair_product_ids.ids)
                _logger.info("PAIR %s:%s:%s" % (self.product_id, self.product_id.ref_lot_pair_ids, component_ids))
                if component_ids:
                    move_ids = component_ids.mapped('move_line_ids').\
                        filtered(lambda r: r.lot_produced_id == self.final_lot_id)
                    locals_dict.update({
                        'components': move_ids,
                    })
                    try:
                        render_result = safe_eval(render_result, locals_dict)
                    except ValueError:
                        _logger.info("Failed to render template %r using values %r" %
                                     (render_result, locals_dict), exc_info=True)
                if render_result:
                    self.final_lot_id.ref = render_result
            if self.product_id.print_label_id:
                self.action_print_lot()
        return super()._post_record_production()
