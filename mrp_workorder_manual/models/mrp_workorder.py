# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    employee_id = fields.Many2one('hr.employee', string='Worker')
    use_bins = fields.Boolean('Use BIN\'s', help='Please checked it if use bins to hold components and lots')

    @api.multi
    def button_start(self):
        self.ensure_one()
        # As button_start is automatically called in the new view
        if self.state in ('done', 'cancel'):
            return True

        # Need a loss in case of the real time exceeding the expected
        timeline = self.env['mrp.workcenter.productivity']
        if self.duration < self.duration_expected:
            loss_id = self.env['mrp.workcenter.productivity.loss'].search([('loss_type','=','productive')], limit=1)
            if not len(loss_id):
                raise UserError(_("You need to define at least one productivity loss in the category 'Productivity'. Create one from the Manufacturing app, menu: Configuration / Productivity Losses."))
        else:
            loss_id = self.env['mrp.workcenter.productivity.loss'].search([('loss_type','=','performance')], limit=1)
            if not len(loss_id):
                raise UserError(_("You need to define at least one productivity loss in the category 'Performance'. Create one from the Manufacturing app, menu: Configuration / Productivity Losses."))
        for workorder in self:
            if workorder.production_id.state != 'progress':
                workorder.production_id.write({
                    'state': 'progress',
                    'date_start': datetime.now(),
                })
            timeline.create({
                'workorder_id': workorder.id,
                'workcenter_id': workorder.workcenter_id.id,
                'description': _('Time Tracking: [%s] %s') % (self.employee_id.name, self.env.user.name),
                'loss_id': loss_id[0].id,
                'date_start': datetime.now(),
                'user_id': self.env.user.id,
                'employee_id': self.employee_id.id,
            })
        return self.write({'state': 'progress',
                    'date_start': datetime.now(),
        })
