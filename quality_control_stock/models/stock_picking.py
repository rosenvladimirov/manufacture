# Copyright 2014 Serv. Tec. Avanzados - Pedro M. Baeza
# Copyright 2018 Simone Rubino - Agile Business Group
# Copyright 2019 Andrii Skrypka
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, _
from odoo.addons.quality_control.models.qc_trigger_line import\
    _filter_trigger_lines

import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    qc_inspections_ids = fields.One2many(
        comodel_name='qc.inspection', inverse_name='picking_id', copy=False,
        string='Inspections', help="Inspections related to this picking.")
    created_inspections = fields.Integer(
        compute="_compute_count_inspections", string="Created inspections")
    done_inspections = fields.Integer(
        compute="_compute_count_inspections", string="Done inspections")
    passed_inspections = fields.Integer(
        compute="_compute_count_inspections", string="Inspections OK")
    failed_inspections = fields.Integer(
        compute="_compute_count_inspections", string="Inspections failed")

    @api.depends('qc_inspections_ids', 'qc_inspections_ids.state')
    def _compute_count_inspections(self):
        data = self.env['qc.inspection'].read_group([
            ('id', 'in', self.mapped('qc_inspections_ids').ids),
        ], ['picking_id', 'state'], ['picking_id', 'state'], lazy=False)
        picking_data = {}
        for d in data:
            picking_data.setdefault(d['picking_id'][0], {})\
                .setdefault(d['state'], 0)
            picking_data[d['picking_id'][0]][d['state']] += d['__count']
        for picking in self:
            count_data = picking_data.get(picking.id, {})
            picking.created_inspections = sum(count_data.values())
            picking.passed_inspections = count_data.get('success', 0)
            picking.failed_inspections = count_data.get('failed', 0)
            picking.done_inspections = \
                (picking.passed_inspections + picking.failed_inspections)

    @api.multi
    def _create_inspection(self):
        inspection_model = self.env['qc.inspection']
        inspections = inspection_model
        for operation in self.move_lines:
            for detailed_line in operation.move_line_ids:
                qc_trigger = self.env['qc.trigger'].search(
                    [('picking_type_id', '=', self.picking_type_id.id)])
                trigger_lines = set()
                for model in ['qc.trigger.product_category_line',
                              'qc.trigger.product_template_line',
                              'qc.trigger.product_line']:
                    partner = (self.partner_id
                               if qc_trigger.partner_selectable else False)
                    trigger_lines = trigger_lines.union(
                        self.env[model].get_trigger_line_for_product(
                            qc_trigger, detailed_line.product_id, partner=partner))
                # for trigger_line in _filter_trigger_lines(trigger_lines):
                #     inspection_model._make_inspection(detailed_line, trigger_line)

                for trigger_line in _filter_trigger_lines(trigger_lines):
                    plan_id, qty_checked = self.env['qc.inspection'].\
                        get_plan_solutions(operation.quantity_done, operation.product_id, False, trigger_line)
                    # _logger.info("PLAN %s->%s" % (plan_id, qty_checked))
                    if plan_id:
                        for level in plan_id.plan_ids:
                            if level.qty_checked != 0:
                                if level.chk_type == 'percent':
                                    coefficient = detailed_line.qty_done/operation.quantity_done
                                    for inx in range(0, int(qty_checked*coefficient)+1):
                                        inspection = inspection_model._make_inspection(detailed_line, trigger_line)
                                        inspection.plan_id = plan_id
                                        inspection.qty_checked = detailed_line.qty_done*coefficient
                                        inspection.qty = detailed_line.qty_done
                                        inspections |= inspection
                                        # inspection.lot_id = detailed_line.lot_id
                                elif level.chk_type == 'lot':
                                    for inx in range(0, int(level.qty_checked)):
                                        values = {
                                            'plan_id': plan_id.id,
                                            'qty_checked': detailed_line.qty_done,
                                            'qty': detailed_line.qty_done,
                                        }
                                        inspection = inspection_model.\
                                            _make_inspection(detailed_line, trigger_line, add_values=values)
                                        inspections |= inspection
                                else:
                                    qty_checked = level.qty_checked
                                    coefficient = detailed_line.qty_done/operation.quantity_done
                                    for inx in range(0, int(qty_checked*coefficient)+1):
                                        inspection = inspection_model._make_inspection(detailed_line, trigger_line)
                                        inspection.plan_id = plan_id
                                        inspection.qty_checked = detailed_line.qty_done*coefficient
                                        inspection.qty = detailed_line.qty_done
                                        inspections |= inspection
                    else:
                        inspections |= inspection_model._make_inspection(self, trigger_line)
        if inspections:
            self.env.user.notify_warning(_('The Inspection is created. Please confirm it.'), sticky=True)

    @api.multi
    def action_done(self):
        res = super(StockPicking, self).action_done()
        self._create_inspection()
        return res
