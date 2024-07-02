# Copyright 2014 Serv. Tec. Avanzados - Pedro M. Baeza
# Copyright 2018 Simone Rubino - Agile Business Group
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.addons.quality_control.models.qc_trigger_line import \
    _filter_trigger_lines


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    @api.multi
    @api.depends('qc_inspections_ids')
    def _compute_count_inspections(self):
        for production in self:
            production.created_inspections = len(production.qc_inspections_ids.filtered(lambda r: not r.workorder_id))

    # @api.multi
    # @api.depends('qc_inspections_ids')
    # def _compute_succes_count_inspections(self):
    #     for production in self:
    #         production.created_inspections = len(production.qc_inspections_ids.filtered(lambda r: r.success))

    qc_inspections_ids = fields.One2many(
        comodel_name='qc.inspection', inverse_name='production_id', copy=False,
        string='Inspections', help="Inspections related to this production.")
    created_inspections = fields.Integer(compute="_compute_count_inspections")
    # succes_created_inspections = fields.Integer(compute="_compute_succes_count_inspections")


    @api.multi
    def post_inventory(self):
        done_moves = self.mapped('move_finished_ids').filtered(
            lambda r: r.state == 'done')
        res = super(MrpProduction, self).post_inventory()
        inspection_model = self.env['qc.inspection']
        action = self.env.ref("quality_control.action_qc_inspection").read()[0]
        form_view = self.env.ref("quality_control.qc_inspection_form_view").id
        qc_trigger = self.env.ref('quality_control_mrp.qc_trigger_mrp')
        new_done_moves = self.mapped('move_finished_ids').filtered(
            lambda r: r.state == 'done') - done_moves
        if new_done_moves:
            qc_trigger = self.env.ref('quality_control_mrp.qc_trigger_mrp')
        for move in new_done_moves:
            trigger_lines = set()
            for model in ['qc.trigger.product_category_line',
                          'qc.trigger.product_template_line',
                          'qc.trigger.product_line']:
                trigger_lines = trigger_lines.union(
                    self.env[model].get_trigger_line_for_product(
                        qc_trigger, move.product_id))
            for trigger_line in _filter_trigger_lines(trigger_lines):
                plan_id, qty_checked = self.env['qc.inspection'].get_plan_solutions(move.product_qty, move.product_id, False, trigger_line)
                inspection = inspection_model._make_inspection(move, trigger_line)
                if inspection:
                    inspection.production_id = self.id
                    action.update({
                        "view_mode": "form",
                        "views": [(form_view, "form")],
                        "res_id": inspection.id,
                        "target": "new",
                    })
                    res = action
        return res

    @api.multi
    def button_mark_done(self):
        res = super(MrpProduction, self).button_mark_done()
        for production in self:
            inspection = production.qc_inspections_ids.filtered(lambda r: not r.workorder_id)
            if len(inspection.ids) > 0:
                action = self.env.ref("quality_control.action_qc_inspection").read()[0]
                form_view = self.env.ref("quality_control.qc_inspection_form_view").id
                action.update({
                    "view_mode": "form",
                    "views": [(form_view, "form")],
                    "res_id": inspection[0].id,
                    "target": "new",
                })
                res = action
        return res
