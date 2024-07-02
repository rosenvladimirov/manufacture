# Copyright 2019 Marcelo Frare (Ass. PNLUG - Gruppo Odoo <http://odoo.pnlug.it>)
# Copyright 2019 Stefano Consolaro (Ass. PNLUG - Gruppo Odoo <http://odoo.pnlug.it>)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models, api, _


class QcInspection(models.Model):
    """
    Extends inspection with:
        - plan control
        - nonconformity relations
        - method to fill inspection with control plan data
        - method create nonconformity from inspection
    """

    _inherit = ['qc.inspection']

    # new fields
    # the control plan to be used
    plan_id = fields.Many2one('qc.plan', 'Control Plan')
    # quantity to be checked
    qty_checked = fields.Float('Quantity checked')
    # nonconformity reference
    inspection_ids = fields.One2many('mgmtsystem.nonconformity',
                                     'inspection_id',
                                     'Nonconformity'
                                     )

    @api.model
    def create(self, values):
        """
        Extends inspection method by integrating logic to determine the control plan
        to be used and the calculation of the quantity to be checked
        """
        # calls original method
        new_record = super(QcInspection, self).create(values)

        # gets product of the inspection
        product_id = new_record.product_id

        # gets partner from picking if exists
        if new_record.picking_id:
            partner_id = self.env['stock.picking'].search([('id', '=', new_record.picking_id.id)], limit=1).partner_id.id
        else:
            partner_id = False

        new_record.plan_id, new_record.qty_checked = self.get_plan_solutions(values.get('qty', 0.0), product_id, partner_id, False)
        return new_record

    @api.model
    def get_plan_solutions(self, qty, product_id, partner_id, trigger):
        qty_checked = 0.0

        if trigger:
            domain_tmpl = [('trigger', '=', trigger.trigger.id), ('product_template', '=', product_id.product_tmpl_id.id), ('test', '=', trigger.test.id)]
            domain_categ = [('trigger', '=', trigger.trigger.id), ('product_category', '=', product_id.categ_id.id), ('test', '=', trigger.test.id)]
        else:
            domain_tmpl = [('product_template', '=', product_id.product_tmpl_id.id)]
            domain_categ = [('product_category', '=', product_id.categ_id.id)]
        domain_part = [('partners', '!=', False), ('partners', '=', partner_id)]
        domain_wh_part = [('partners', '=', False)]

        # temporary presetted solutions
        # tries to get plan for product and partner
        solution_art_prt = self.env['qc.trigger.product_template_line'].search(domain_tmpl + domain_part, limit=1)
        solution_cat_prt = ''  # plan for product category and partner
        solution_art = ''  # plan for product (article)
        solution_cat = ''  # plan for product category
        solution_prt = ''  # plan for partner

        if len(solution_art_prt) == 0:
            # tries to gets plan for category and partner
            solution_cat_prt = self.env['qc.trigger.product_category_line'].search(domain_categ + domain_part, limit=1)

        if len(solution_art_prt) + len(solution_cat_prt) == 0:
            # tries to get plan for product
            solution_art = self.env['qc.trigger.product_template_line'].search(domain_tmpl + domain_wh_part, limit=1)

        if len(solution_art_prt) + len(solution_cat_prt) + len(solution_art) == 0:
            # tries to get plan for category
            solution_cat = self.env['qc.trigger.product_category_line'].search(domain_categ + domain_wh_part, limit=1)

        if len(solution_art_prt) + len(solution_cat_prt) + len(solution_art) + len(solution_cat) == 0:
            # tries to get plan for partner
            solution_prt = self.env['qc.trigger.partner_line'].search([('partner', '=', partner_id)], limit=1)

        # gets the plan from the first positive try
        if len(solution_art_prt):
            plan_id = solution_art_prt.plan_id
        elif len(solution_cat_prt):
            plan_id = solution_cat_prt.plan_id
        elif len(solution_art):
            plan_id = solution_art.plan_id
        elif len(solution_cat):
            plan_id = solution_cat.plan_id
        elif len(solution_prt):
            plan_id = solution_prt.plan_id
        else:
            return False, 0

        # assigns plan to be used
        if plan_id.free_pass:
            # for free pass doesn't check product
            return plan_id, 0

        # gets check information from levels
        qty_related = self.env['qc.level'].search([('plan_id', '=', plan_id.id), ('qty_received', '<', qty)], limit=1, order='qty_received desc')
        # assigns qty to check
        if qty_related:
            if qty_related.chk_type == 'percent':
                # as percent of qty to check
                qty_checked = int(qty * qty_related.qty_checked / 100)
            else:
                # as absolute value
                qty_checked = qty_related.qty_checked
        else:
            return False, 0

        # verifies if enough pcs to check
        if qty_checked > qty:
            qty_checked = qty

        # checks and fix absolute minimum value lower to 1
        if qty_checked < 1:
            qty_checked = 1
        return plan_id, qty_checked

    @api.multi
    def create_nonconformity(self, **kwargs):
        """
        Opens nonconformity form view prefilled with inspection data
        """

        # gets partner if exists
        if self.picking_id.partner_id.id:
            partner = self.picking_id.partner_id.id
        else:
            partner = False

        tmp_form_name = "mgmtsystem_nonconformity.view_mgmtsystem_nonconformity_form"
        return {
            # opens nonconformity form view
            'name': _('Create Nonconformity on not compliant Inspection'),
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'mgmtsystem.nonconformity',
            'view_id': self.env.ref(tmp_form_name).id,
            'type': 'ir.actions.act_window',

            # fills fields with inspection data
            'context': {
                'default_name': _('Inspection not compliant'),
                'default_product_id': self.product_id.id,
                'default_partner_id': partner,
                'default_qty_checked': self.qty_checked,
                'default_inspection_id': self.id
            },

            'target': 'new'
        }
