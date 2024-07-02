# Copyright 2014 Serv. Tec. Avanzados - Pedro M. Baeza
# Copyright 2018 Simone Rubino - Agile Business Group
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.addons.quality_control.models.qc_trigger_line import \
    _filter_trigger_lines

import logging
_logger = logging.getLogger(__name__)


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    @api.multi
    @api.depends('qc_inspections_ids')
    def _compute_count_inspections(self):
        for wo in self:
            wo.created_inspections = len(wo.qc_inspections_ids)

    qc_inspections_ids = fields.One2many(
        comodel_name='qc.inspection', inverse_name='workorder_id', copy=False,
        string='Inspections', help="Inspections related to this work order.")
    created_inspections = fields.Integer(compute="_compute_count_inspections")

    @api.multi
    def record_production(self):
        final_lot_id = False
        for wo in self:
            final_lot_id = wo.final_lot_id
        res = super(MrpWorkorder, self).record_production()
        for wo in self:
            if res:
                qc_trigger = self.env.ref('quality_control_mrp_workorder.qc_trigger_mrp_wo')
                inspection_model = self.env['qc.inspection']
                trigger_lines = set()
                for model in ['qc.trigger.product_category_line',
                              'qc.trigger.product_template_line',
                              'qc.trigger.product_line']:
                    trigger_lines = trigger_lines.union(
                        self.env[model].get_trigger_line_for_product(
                            qc_trigger, wo.product_id))
                # _logger.info("TRIGERS %s" % trigger_lines)
                for trigger_line in _filter_trigger_lines(trigger_lines):
                    # _logger.info("TEST %s:%s:%s" % (trigger_line, trigger_line.test.operation_id, wo.operation_id))
                    if trigger_line.test.operation_id != wo.operation_id:
                        continue
                    inspection = False
                    plan_id, qty_checked = self.env['qc.inspection'].\
                        get_plan_solutions(wo.qty_producing, wo.product_id, False, trigger_line)
                    # _logger.info("PLAN %s->%s" % (plan_id, qty_checked))
                    if plan_id:
                        for level in plan_id.plan_ids:
                            if level.qty_checked != 0:
                                if level.chk_type == 'percent':
                                    divide = int(wo.qty_production/(wo.qty_production * level.qty_checked/100))
                                    # _logger.info("DEVIDE %s" % divide)
                                    if divide != 0 and int(wo.qty_produced/divide) == wo.qty_produced/divide:
                                        inspection = inspection_model._make_inspection(self, trigger_line)
                                        inspection.lot_id = final_lot_id
                                else:
                                    divide = int(wo.qty_production/level.qty_checked)
                                    if int((wo.qty_produced - 1)/divide) == (wo.qty_produced - 1)/divide:
                                        inspection = inspection_model._make_inspection(self, trigger_line)
                    else:
                        inspection = inspection_model._make_inspection(self, trigger_line)
                    # if inspection:
                    #     inspection.lot_id = final_lot_id
                    #     action = self.env.ref("quality_control.action_qc_inspection").read()[0]
                    #     form_view = self.env.ref("quality_control.qc_inspection_form_view").id
                    #     action.update({
                    #         "view_mode": "form",
                    #         "views": [(form_view, "form")],
                    #         "res_id": inspection.id,
                    #         "target": "new",
                    #     })
                    #     res = action
        return res
