# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.addons.queue_job.job import job


import logging
_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    @api.multi
    @job
    def _button_mark_done_with_delay(self):
        return super(MrpProduction, self).button_mark_done()

    @api.multi
    def _button_mark_done(self):
        return super(MrpProduction, self).button_mark_done()

    @api.multi
    def button_mark_done(self):
        # action = self.env.ref('mrp_production_delay.action_delay_mrp_production_wizard')
        # action['context'] = {'default_production_order_id': self.id}
        # return action
        if self._context.get('on_background'):
            return self.with_delay()._button_mark_done_with_delay()
        else:
            return super(MrpProduction, self).button_mark_done()
