# -*- coding: utf-8 -*-
# dXFactory Proprietary License (dXF-PL) v1.0. See LICENSE file for full copyright and licensing details.
from itertools import groupby

from odoo import fields, models, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

import logging

_logger = logging.getLogger(__name__)


class EuroplacerTrac(models.Model):
    _inherit = "europlacer.trac"

    @api.model
    def _post_populate_data(self, lpopulate):
        lpopulate = [x.id for x in lpopulate]
        quant = self.env['stock.quant']
        tracs = self.env['europlacer.trac'].sudo().browse(lpopulate)
        precision_digits = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        production = set([])
        for trac in tracs:
            if trac and trac.production_id:
                production.update([trac.production_id.id])
        for production_id in self.env['mrp.production'].browse(list(production)):
            for trac in tracs:
                for group, lines in groupby(trac.lines.sorted(lambda r: "%s-%s" % (r.product_id.id, r.lot_id.id)),
                                            lambda r: r.product_id):
                    for lot_id, lot_lines in groupby(lines, lambda r: r.lot_id):
                        available_quantity = quant._get_available_quantity(
                            group, production_id.location_src_id, lot_id=lot_id,
                        )
                        qty = len(list(lot_lines))
                        if float_compare(available_quantity, 0.0, precision_digits=precision_digits) <= 0:
                            continue
                        for move in production_id.move_raw_ids.filtered(lambda r: r.product_id == group):
                            try:
                                move._update_reserved_quantity(qty, available_quantity,
                                                               production_id.location_src_id,
                                                               lot_id=lot_id,
                                                               strict=True)
                                # move.filename = trac.filename
                            except UserError:
                                _logger.info("Exception %s" % move.product_id.name)
