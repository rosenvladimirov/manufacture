# -*- coding: utf-8 -*-
import time

from odoo import http, tools, _
from odoo.http import request
from odoo.addons.web.controllers.main import ensure_db
import json

import logging

_logger = logging.getLogger(__name__)


class WebsiteWorkorder(http.Controller):

    # give work order token and return the BOM from production order
    # [server url]/workorder/get_bom?access_token=[token]
    @http.route(['/workorder/get_bom'], type='http', auth="public", website=True, csrf=False)
    def workorder_get_bom(self, access_token=None, **post):
        workorder_id = request.env['mrp.workorder'].sudo().search([('access_token', '=', access_token)])
        if workorder_id and workorder_id.production_id.bom_id:
            result = {}
            manufacture_route = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
            product = workorder_id.product_id
            bom = workorder_id.production_id.bom_id
            factor = product.uom_id._compute_quantity(1.0, bom.product_uom_id) / bom.product_qty
            boms, exploded_lines = bom.with_context(dict(self._context, force_phantom=True)).\
                explode(product, factor, picking_type=bom.picking_type_id)
            for bom_line, line_data in exploded_lines:
                if not bom_line.product_id.ref_note_manufacture or \
                        manufacture_route.id not in bom_line.product_id.mapped('route_ids').ids:
                    continue
                result[bom_line.product_id.default_code] = bom_line.product_id.ref_note_manufacture
            if result:
                return json.dumps({'result':  result})
        return json.dumps({'error': {
                'title': _('No information'),
                'message': 'In search work order is not information about bom!!!'
            }})
