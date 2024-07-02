# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from itertools import groupby

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.addons.queue_job.job import job

from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round
from odoo.addons import decimal_precision as dp

import logging

_logger = logging.getLogger(__name__)


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    def _generate_lot_ids(self):
        super(MrpWorkorder, self)._generate_lot_ids()
        unlink = self.active_move_line_ids.filtered(lambda r: r.move_id.bom_line_id.skip_alternative)
        if unlink:
            unlink.unlink()
