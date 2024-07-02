# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.addons.mrp.models.procurement import ProcurementRule as procurementrule

import logging
_logger = logging.getLogger(__name__)


class ProcurementRule(models.Model):
    _inherit = 'procurement.rule'

    @api.multi
    def _run_manufacture(self, product_id, product_qty, product_uom, location_id, name, origin, values):
        if self._context.get('selection_follow') != 'normal':
            return super(ProcurementRule, self)._run_manufacture(product_id, product_qty, product_uom, location_id, name, origin, values)
        return True

    @api.multi
    def _get_matching_bom(self, product_id, values):
        if values.get('bom_id', False):
            return values['bom_id']
        picking_type = self.picking_type_id

        if self._context.get('selection_follow', 'normal') == 'sub':
            picking_type = False
        return self.env['mrp.bom'].with_context(
            company_id=values['company_id'].id, force_company=values['company_id'].id
        )._bom_find(product=product_id, picking_type=picking_type)  # TDE FIXME: context bullshit

procurementrule._get_matching_bom = ProcurementRule._get_matching_bom
