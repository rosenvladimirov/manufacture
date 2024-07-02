#  -*- coding: utf-8 -*-
#  Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    """ Manufacturing Orders """
    _inherit = 'mrp.production'

    @api.multi
    def action_auto_fs(self):
        work_center_id = self.env.ref('europlacer.pnp')
        files = []
        for production_id in self.search([('state', '=', 'progress')], order='date_planned_start ASC'):
            workorder_ids = production_id.mapped("workorder_ids")
            if workorder_ids.filtered(lambda r: r.state in ['ready', 'progress'] and r.operation_id.workcenter_id.id == work_center_id.id):
                track_ids = self.env['europlacer.trac'].search([('production_id', '=', production_id.id)])
                for track_id in track_ids:
                    files.append(track_id.filename.upper())
                sub_path = production_id.product_id.product_tmpl_id.description_short or production_id.product_id.description_short
                _logger.info("START RE-COLLECT %s sub_path: %s, files: %s" % (production_id.name, sub_path, len(files)))
                self.env['europlacer.fs'].with_delay().action_restore(self, 0, sub_path=sub_path,
                                                                      production_id=production_id.id,
                                                                      exclude=files,
                                                                      force_move=True)
