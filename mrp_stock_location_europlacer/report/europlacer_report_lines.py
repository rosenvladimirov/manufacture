# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, tools, fields, api, _

import logging

_logger = logging.getLogger(__name__)


class EuroplacerReportLines(models.AbstractModel):
    _name = 'europlacer.report.lines'
    _description = 'Europlacer Report lines for traceability SN'
    _auto = False
    _rec_name = 'dummy_batch'
    _order = 'dummy_batch desc'

    production_id = fields.Many2one('mrp.production', 'Production', readonly=True)
    production_name = fields.Char('Production Ref #')
    dummy_batch = fields.Char('Batch SN', readonly=True)
    dummy_product_sn = fields.Char('Product SN', readonly=True)
    left_concerned_pattern = fields.Char('Concerned Pattern', readonly=True)
    right_concerned_pattern = fields.Char('Concerned Pattern', readonly=True)

    def _select(self):
        sql = """SELECT DISTINCT et.dummy_batch, el.dummy_product_sn, el.concerned_pattern AS left_concerned_pattern, 
        ecp.right_concerned_pattern AS right_concerned_pattern, et.production_id, pr.name AS production_name
"""
        return sql

    def _from(self):
        sql = """europlacer_trac_line el 
LEFT JOIN europlacer_trac AS et ON el.trac_id = et.id 
LEFT JOIN mrp_production AS pr ON et.production_id = pr.id 
LEFT JOIN mrp_concerned_pattern AS ecp ON ecp.production_id = et.production_id AND ecp.sequence::text = el.concerned_pattern::text"""
        return sql

    @api.model_cr
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""CREATE or REPLACE VIEW %s as (%s FROM %s)""" % (self._table,
                                                                               self._select(),
                                                                               self._from()))
