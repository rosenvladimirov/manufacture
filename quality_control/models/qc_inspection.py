# Copyright 2010 NaN Projectes de Programari Lliure, S.L.
# Copyright 2014 Serv. Tec. Avanzados - Pedro M. Baeza
# Copyright 2014 Oihane Crucelaegui - AvanzOSC
# Copyright 2017 Eficent Business and IT Consulting Services S.L.
# Copyright 2017 Simone Rubino - Agile Business Group
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, exceptions, fields, models, _
from odoo.tools import formatLang
import odoo.addons.decimal_precision as dp
from odoo.addons.quality_control.models.qc_trigger_line import _filter_trigger_lines

import logging

_logger = logging.getLogger(__name__)


class QcInspection(models.Model):
    _name = 'qc.inspection'
    _description = 'Quality control inspection'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    @api.depends('inspection_lines', 'inspection_lines.success')
    def _compute_success(self):
        for i in self:
            i.success = all([x.success for x in i.inspection_lines])

    @api.multi
    def _links_get(self):
        link_obj = self.env['res.request.link']
        return [(r.object, r.name) for r in link_obj.search([])]

    @api.depends('object_id')
    def _compute_product_id(self):
        for i in self:
            if i.object_id and i.object_id._name == 'product.product':
                i.product_id = i.object_id
            else:
                i.product_id = False

    @api.multi
    @api.depends('inspection_lines', 'inspection_lines.qualitative_value')
    def _compute_critical_msg(self):
        for record in self:
            trigger_lines = record._get_local_qc_triggers()
            level_failed = failed_inspections = done_inspections = 0.0
            for trigger_line in sorted(trigger_lines, key=lambda r: str(r.level_failed * 100), reverse=False):
                failed_inspections += trigger_line.test.failed_inspections
                done_inspections += trigger_line.test.done_inspections
            if done_inspections:
                level_failed = failed_inspections / done_inspections

            _logger.info("ALL TRIGERS %s:%s %s" % (trigger_lines, record.test, record.product_id.product_tmpl_id.display_name))
            for line in trigger_lines:
                _logger.info("TRIGER %s >= %s" % (record.test.level_failed, line.level_failed))

                if level_failed >= line.level_failed:
                    record.critical_msg = True
                    if not record.critical_description:
                        record.critical_description = record.test.critical_description
                    break

            # qc_trigger = record.product_id.product_tmpl_id.qc_triggers
            # trigger_lines = set()
            # for model in ['qc.trigger.product_category_line',
            #               'qc.trigger.product_template_line',
            #               'qc.trigger.product_line']:
            #     trigger_lines = trigger_lines.union(
            #         self.env[model].get_trigger_line_for_product(
            #             qc_trigger, record.product_id, partner=False))
            # _logger.info("ALL TRIGERS %s:%s" % (qc_trigger, trigger_lines))
            #
            # for test in _filter_trigger_lines(trigger_lines):
            #     _logger.info("TEST %s" % test.name)
            #     if record.test != test:
            #         record.critical_msg = True
            #         record.critical_description = test.critical_description

    name = fields.Char(
        string='Inspection number', required=True, default='/',
        readonly=True, states={'draft': [('readonly', False)]}, copy=False)
    date = fields.Datetime(
        string='Date', required=True, readonly=True, copy=False,
        default=fields.Datetime.now,
        states={'draft': [('readonly', False)]})
    object_id = fields.Reference(
        string='Reference', selection=_links_get, readonly=True,
        states={'draft': [('readonly', False)]}, ondelete="set null")
    product_id = fields.Many2one(
        comodel_name="product.product", compute="_compute_product_id",
        store=True, help="Product associated with the inspection",
        oldname='product')
    qty = fields.Float(string="Quantity", default=1.0)
    test = fields.Many2one(
        comodel_name='qc.test', string='Test', readonly=True)
    critical_msg = fields.Boolean('Critical level', compute='_compute_critical_msg')
    level_failed = fields.Float('Critical level', related='test.level_failed')
    active = fields.Boolean('Active', default=True,
                            help="If unchecked, it will allow you to hide the inspection without removing it.")
    inspection_lines = fields.One2many(
        comodel_name='qc.inspection.line', inverse_name='inspection_id',
        string='Inspection lines', readonly=True,
        states={'ready': [('readonly', False)]})
    internal_notes = fields.Text(string='Internal notes')
    external_notes = fields.Text(
        string='External notes',
        states={'success': [('readonly', True)],
                'failed': [('readonly', True)]})
    state = fields.Selection(
        [('draft', 'Draft'),
         ('ready', 'Ready'),
         ('waiting', 'Waiting supervisor approval'),
         ('success', 'Quality success'),
         ('failed', 'Quality failed'),
         ('canceled', 'Canceled')],
        string='State', readonly=True, default='draft',
        track_visibility='onchange')
    success = fields.Boolean(
        compute="_compute_success", string='Success',
        help='This field will be marked if all tests have succeeded.',
        store=True)
    auto_generated = fields.Boolean(
        string='Auto-generated', readonly=True, copy=False,
        help='If an inspection is auto-generated, it can be canceled but not '
             'removed.')
    company_id = fields.Many2one(
        comodel_name='res.company', string='Company', readonly=True,
        states={'draft': [('readonly', False)]},
        default=lambda self: self.env['res.company']._company_default_get(
            'qc.inspection'))
    user = fields.Many2one(
        comodel_name='res.users', string='Responsible',
        track_visibility='always', default=lambda self: self.env.user)
    critical_description = fields.Text('Message for critical')

    @api.multi
    def _get_local_qc_triggers(self, qc_trigger_domain=False, force_object_id=False):
        trigger_lines = set()
        self.ensure_one()
        if self.object_id and qc_trigger_domain:
            object_id = force_object_id or self.object_id
            qc_trigger = self.env['qc.trigger'].search(qc_trigger_domain)
            if 'product_id' in object_id._fields:
                for model in ['qc.trigger.product_category_line',
                              'qc.trigger.product_template_line',
                              'qc.trigger.product_line']:
                    partner = (object_id.partner_id
                               if qc_trigger.partner_selectable else False)
                    trigger_lines = trigger_lines.union(
                        self.env[model].get_trigger_line_for_product(
                            qc_trigger, object_id.product_id, partner=partner))
        return trigger_lines

    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'] \
                .next_by_code('qc.inspection')
        return super(QcInspection, self).create(vals)

    @api.multi
    def unlink(self):
        for inspection in self:
            _logger.info("UNLINK %s:%s:%s" % (self._context, inspection.state, inspection.auto_generated))
            if self._context.get('force_unlink', False):
                super(QcInspection, self).unlink()
            if inspection.auto_generated:
                raise exceptions.UserError(
                    _("You cannot remove an auto-generated inspection."))
            if inspection.state != 'draft':
                raise exceptions.UserError(
                    _("You cannot remove an inspection that is not in draft "
                      "state."))
        return super(QcInspection, self).unlink()

    @api.multi
    def action_draft(self):
        self.write({'state': 'draft'})

    @api.multi
    def action_todo(self):
        for inspection in self:
            if not inspection.test:
                raise exceptions.UserError(
                    _("You must first set the test to perform."))
        self.write({'state': 'ready'})

    @api.multi
    def action_confirm(self):
        for inspection in self:
            for line in inspection.inspection_lines:
                if line.question_type == 'qualitative':
                    if not line.qualitative_value:
                        raise exceptions.UserError(
                            _("You should provide an answer for all "
                              "qualitative questions."))
                else:
                    if not line.uom_id:
                        raise exceptions.UserError(
                            _("You should provide a unit of measure for "
                              "quantitative questions."))
            if inspection.success:
                inspection.state = 'success'
            else:
                inspection.state = 'waiting'

    @api.multi
    def action_approve(self):
        for inspection in self:
            if inspection.success:
                inspection.state = 'success'
            else:
                inspection.state = 'failed'

    @api.multi
    def action_cancel(self):
        self.write({'state': 'canceled'})

    @api.multi
    def set_test(self, trigger_line, force_fill=False):
        for inspection in self:
            header = self._prepare_inspection_header(
                inspection.object_id, trigger_line)
            del header['state']  # don't change current status
            del header['auto_generated']  # don't change auto_generated flag
            del header['user']  # don't change current user
            inspection.write(header)
            inspection.inspection_lines.unlink()
            inspection.inspection_lines = inspection._prepare_inspection_lines(
                trigger_line.test, force_fill=force_fill)

    @api.multi
    def _make_inspection(self, object_ref, trigger_line, add_values=False):
        """Overridable hook method for creating inspection from test.
        :param object_ref: Object instance
        :param trigger_line: Trigger line instance
        :return: Inspection object
        """
        values = self._prepare_inspection_header(object_ref, trigger_line)
        if add_values:
            values.update(add_values)
        inspection = self.create(values)
        inspection.set_test(trigger_line)
        return inspection

    @api.multi
    def _prepare_inspection_header(self, object_ref, trigger_line):
        """Overridable hook method for preparing inspection header.
        :param object_ref: Object instance
        :param trigger_line: Trigger line instance
        :return: List of values for creating the inspection
        """
        return {
            'object_id': object_ref and '%s,%s' % (object_ref._name, object_ref.id) or False,
            'state': 'ready',
            'test': trigger_line.test.id,
            'user': trigger_line.user.id,
            'auto_generated': True,
        }

    @api.multi
    def _prepare_inspection_lines(self, test, force_fill=False):
        new_data = []
        for line in test.test_lines:
            data = self._prepare_inspection_line(
                test, line, fill=test.fill_correct_values or force_fill)
            new_data.append((0, 0, data))
        return new_data

    @api.multi
    def _prepare_inspection_line(self, test, line, fill=None):
        data = {
            'name': line.name,
            'test_line': line.id,
            'notes': line.notes,
            'min_value': line.min_value,
            'max_value': line.max_value,
            'test_uom_id': line.uom_id.id,
            'uom_id': line.uom_id.id,
            'question_type': line.type,
            'possible_ql_values': [x.id for x in line.ql_values]
        }
        if fill:
            if line.type == 'qualitative':
                # Fill with the first correct value found
                for value in line.ql_values:
                    if value.ok:
                        data['qualitative_value'] = value.id
                        break
            else:
                # Fill with a value inside the interval
                data['quantitative_value'] = (line.min_value +
                                              line.max_value) * 0.5
        return data


class QcInspectionLine(models.Model):
    _name = 'qc.inspection.line'
    _description = "Quality control inspection line"

    # @api.multi
    # @api.depends('qualitative_value')
    # def _compute_has_msg(self):
    #     for record in self:
    #         msg = record._get_critical_msg()
    #         if msg.get(record):
    #             record.inspection_id.critical_msg = msg[record]

    @api.depends('question_type', 'uom_id', 'test_uom_id', 'max_value',
                 'min_value', 'quantitative_value', 'qualitative_value',
                 'possible_ql_values')
    def _compute_quality_test_check(self):
        for l in self:
            if l.question_type == 'qualitative':
                l.success = l.qualitative_value.ok
            else:
                if l.uom_id.id == l.test_uom_id.id:
                    amount = l.quantitative_value
                else:
                    amount = self.env['product.uom']._compute_quantity(
                        l.quantitative_value,
                        l.test_uom_id.id)
                l.success = l.max_value >= amount >= l.min_value

    @api.depends('possible_ql_values', 'min_value', 'max_value', 'test_uom_id',
                 'question_type')
    def _compute_valid_values(self):
        for l in self:
            if l.question_type == 'qualitative':
                l.valid_values = \
                    ", ".join([x.name for x in l.possible_ql_values if x.ok])
            else:
                l.valid_values = "%s ~ %s" % (
                    formatLang(self.env, l.min_value),
                    formatLang(self.env, l.max_value))
                if self.env.ref("product.group_uom") \
                        in self.env.user.groups_id:
                    l.valid_values += " %s" % l.test_uom_id.name

    inspection_id = fields.Many2one(
        comodel_name='qc.inspection', string='Inspection', ondelete='cascade')
    name = fields.Char(string="Question", readonly=True)
    product_id = fields.Many2one(
        comodel_name="product.product", related="inspection_id.product_id",
        store=True,  oldname='product')
    test_line = fields.Many2one(
        comodel_name='qc.test.question', string='Test question',
        readonly=True)
    possible_ql_values = fields.Many2many(
        comodel_name='qc.test.question.value', string='Answers')
    quantitative_value = fields.Float(
        'Quantitative value', digits=dp.get_precision('Quality Control'),
        help="Value of the result for a quantitative question.")
    qualitative_value = fields.Many2one(
        comodel_name='qc.test.question.value', string='Qualitative value',
        help="Value of the result for a qualitative question.",
        domain="[('id', 'in', possible_ql_values)]")
    notes = fields.Text(string='Notes')
    min_value = fields.Float(
        string='Min', digits=dp.get_precision('Quality Control'),
        readonly=True, help="Minimum valid value for a quantitative question.")
    max_value = fields.Float(
        string='Max', digits=dp.get_precision('Quality Control'),
        readonly=True, help="Maximum valid value for a quantitative question.")
    test_uom_id = fields.Many2one(
        comodel_name='product.uom', string='Test UoM', readonly=True,
        help="UoM for minimum and maximum values for a quantitative "
             "question.")
    test_uom_category = fields.Many2one(
        comodel_name="product.uom.categ", related="test_uom_id.category_id",
        store=True)
    uom_id = fields.Many2one(
        comodel_name='product.uom', string='UoM',
        domain="[('category_id', '=', test_uom_category)]",
        help="UoM of the inspection value for a quantitative question.")
    question_type = fields.Selection(
        [('qualitative', 'Qualitative'),
         ('quantitative', 'Quantitative')],
        string='Question type', readonly=True)
    valid_values = fields.Char(string="Valid values", store=True,
                               compute="_compute_valid_values")
    success = fields.Boolean(
        compute="_compute_quality_test_check", string="Success?", store=True)

