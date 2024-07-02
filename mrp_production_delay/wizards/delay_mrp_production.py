# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from itertools import groupby
from odoo import api, models, fields, _
# from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class MrpProductionDelay(models.TransientModel):
    _name = 'mrp.production.delay'
    _description = "Delay mark is done manufacture order wizard"

    @api.multi
    def action_delay_mrp_production(self):
        records = self.env['mrp.production'].browse(self._context.get('active_ids', []))
        _logger.info("RECORDS %s(%s)" % (records, self._context))
        if records:
            batch = self.env['queue.job.batch'].get_new_batch('Production mark is done')
            for record in records:
                record.with_context(job_batch=batch).with_delay()._button_mark_done_with_delay()
            batch.enqueue()
