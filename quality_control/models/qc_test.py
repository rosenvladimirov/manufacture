# Copyright 2010 NaN Projectes de Programari Lliure, S.L.
# Copyright 2014 Serv. Tec. Avanzados - Pedro M. Baeza
# Copyright 2014 Oihane Crucelaegui - AvanzOSC
# Copyright 2017 Eficent Business and IT Consulting Services S.L.
# Copyright 2017 Simone Rubino - Agile Business Group
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, exceptions, fields, models, _
import odoo.addons.decimal_precision as dp


class QcTest(models.Model):
    """
    A test is a group of questions along with the values that make them valid.
    """
    _name = 'qc.test'
    _description = 'Quality control test'

    @api.multi
    def _links_get(self):
        link_obj = self.env['res.request.link']
        return [(r.object, r.name) for r in link_obj.search([])]

    @api.onchange('type')
    def onchange_type(self):
        if self.type == 'generic':
            self.object_id = False

    active = fields.Boolean('Active', default=True)
    name = fields.Char(
        string='Name', required=True, translate=True)
    test_lines = fields.One2many(
        comodel_name='qc.test.question', inverse_name='test',
        string='Questions', copy=True)
    object_id = fields.Reference(
        string='Reference object', selection=_links_get,)
    fill_correct_values = fields.Boolean(
        string='Pre-fill with correct values')
    type = fields.Selection(
        [('generic', 'Generic'),
         ('related', 'Related')],
        string='Type', required=True, default='generic')
    category = fields.Many2one(
        comodel_name='qc.test.category', string='Category')
    company_id = fields.Many2one(
        comodel_name='res.company', string='Company',
        default=lambda self: self.env['res.company']._company_default_get(
            'qc.test'))
    level_failed = fields.Float(
        compute="_compute_count_inspections", string='Inspections failed level',
        digits=dp.get_precision('Inspections failed level'),
        store=True)
    critical_description = fields.Text('Message for critical')

    qc_inspections_ids = fields.One2many(
        comodel_name='qc.inspection', inverse_name='test', copy=False,
        string='Inspections', help="Inspections related to this lot.")
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
            ('test', 'in', self.ids),
        ], ['test', 'state', 'active'], ['test', 'state', 'active'], lazy=False)
        test_data = {}
        for d in data:
            test_data.setdefault(d['test'][0], {}).setdefault(d['state'], 0)
            test_data[d['test'][0]][d['state']] += d['__count']
        for test in self:
            count_data = test_data.get(test.id, {})
            test.created_inspections = sum(count_data.values())
            test.passed_inspections = count_data.get('success', 0)
            test.failed_inspections = count_data.get('failed', 0)
            test.done_inspections = \
                (test.passed_inspections + test.failed_inspections)
            if test.done_inspections > 0:
                test.level_failed = test.failed_inspections / test.done_inspections
            else:
                test.level_failed = 0.0


class QcTestQuestion(models.Model):
    """Each test line is a question with its valid value(s)."""
    _name = 'qc.test.question'
    _description = 'Quality control question'
    _order = 'sequence, id'

    @api.constrains('ql_values')
    def _check_valid_answers(self):
        for tc in self:
            if (tc.type == 'qualitative' and tc.ql_values and
                    not tc.ql_values.filtered('ok')):
                raise exceptions.ValidationError(
                    _("Question '%s' is not valid: "
                      "you have to mark at least one value as OK.")
                    % tc.name_get()[0][1])

    @api.constrains('min_value', 'max_value')
    def _check_valid_range(self):
        for tc in self:
            if tc.type == 'quantitative' and tc.min_value > tc.max_value:
                raise exceptions.ValidationError(
                    _("Question '%s' is not valid: "
                      "minimum value can't be higher than maximum value.")
                    % tc.name_get()[0][1])

    sequence = fields.Integer(
        string='Sequence', required=True, default="10")
    test = fields.Many2one(comodel_name='qc.test', string='Test')
    name = fields.Char(
        string='Name', required=True, translate=True)
    type = fields.Selection(
        [('qualitative', 'Qualitative'),
         ('quantitative', 'Quantitative')], string='Type', required=True)
    ql_values = fields.One2many(
        comodel_name='qc.test.question.value', inverse_name="test_line",
        string='Qualitative values', copy=True)
    notes = fields.Text(string='Notes')
    min_value = fields.Float(string='Min',
                             digits=dp.get_precision('Quality Control'))
    max_value = fields.Float(string='Max',
                             digits=dp.get_precision('Quality Control'),)
    uom_id = fields.Many2one(comodel_name='product.uom', string='Uom')


class QcTestQuestionValue(models.Model):
    _name = 'qc.test.question.value'
    _description = 'Possible values for qualitative questions.'

    test_line = fields.Many2one(
        comodel_name="qc.test.question", string="Test question")
    name = fields.Char(
        string='Name', required=True, translate=True)
    ok = fields.Boolean(
        string='Correct answer?',
        help="When this field is marked, the answer is considered correct.")
