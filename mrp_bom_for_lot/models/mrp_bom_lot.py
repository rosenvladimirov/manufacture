# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class MrpBomLot(models.Model):
    _name = 'mrp.bom.lot'
    _description = 'BOM for Lot/Serial Number'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='/'
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product template',
        required=True,
        tracking=True
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product variant',
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        tracking=True
    )
    master_bom_id = fields.Many2one(
        'mrp.bom',
        string='Master BOM',
        required=True,
        domain="['|', ('product_tmpl_id', '=', product_tmpl_id), ('product_id', '=', product_id)]",
        tracking=True
    )
    lot_id = fields.Many2one(
        'stock.lot',
        string='Lot/Serial Number',
        domain="[('product_id', '=', product_id)]",
        tracking=True
    )
    lot_name = fields.Char(
        string='Lot/Serial Name',
        help='Ако лотът още не съществува, въведете име тук'
    )
    line_ids = fields.One2many(
        'mrp.bom.lot.line',
        'bom_lot_id',
        string='Components',
        copy=True
    )
    product_qty = fields.Float(
        string='Quantity',
        default=1.0,
        required=True,
        tracking=True
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of measure',
        related='master_bom_id.product_uom_id',
        readonly=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Used'),
        ('cancel', 'Cancel')
    ], string='Статус', default='draft', tracking=True)

    notes = fields.Text(string='Comment')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('mrp.bom.lot') or '/'
        return super(MrpBomLot, self).create(vals_list)

    @api.onchange('master_bom_id')
    def _onchange_master_bom_id(self):
        """Зареждане на компонентите от главния BOM"""
        if self.master_bom_id:
            # self.product_tmpl_id = self.master_bom_id.product_tmpl_id
            # self.product_id = self.master_bom_id.product_id
            self._load_master_bom_lines()

    def _load_master_bom_lines(self):
        """Зарежда редовете от главния BOM"""
        if not self.master_bom_id:
            return

        lines = []
        for bom_line in self.master_bom_id.bom_line_ids.filtered(lambda l: l.lot_dynamic):
            lines.append((0, 0, {
                'master_bom_line_id': bom_line.id,
                'product_id': bom_line.product_id.id,
                'product_qty': bom_line.product_qty,
                'product_uom_id': bom_line.product_uom_id.id,
                'stage_id': False,  # Ще се зададе ръчно
            }))
        self.line_ids = lines

    def action_load_from_master(self):
        """Бутон за презареждане на редове от главния BOM"""
        self.ensure_one()
        if not self.master_bom_id:
            raise UserError('Please select master BOM first!')

        self.line_ids = [(5, 0, 0)]  # Изтриване на съществуващите редове
        self._load_master_bom_lines()

        # Изпращане на съобщение през bus за refresh
        self.env['bus.bus']._sendone(
            self.env.user.partner_id,
            'mail.message/inbox',
            {
                'type': 'success',
                'tag': 'display_notification',
                'title': 'Successfully',
                'message': 'The lines are loaded from the master BOM',
            }
        )

    def action_confirm(self):
        """Потвърждаване на BOM"""
        self.ensure_one()
        if not self.line_ids:
            raise UserError('You cannot validate a BOM without components!')

        # Проверка за разлики и добавяне на нови редове в master BOM
        self._sync_new_products_to_master_bom()

        self.state = 'confirmed'

    def _sync_new_products_to_master_bom(self):
        """Синхронизира нови продукти от lot BOM към master BOM"""
        self.ensure_one()

        if not self.master_bom_id:
            return

        # Вземаме всички product_id от master BOM
        master_product_ids = self.master_bom_id.bom_line_ids.mapped('product_id.id')

        # Вземаме всички product_id от текущия lot BOM
        lot_product_ids = self.line_ids.mapped('product_id.id')

        # Намираме продуктите, които са в lot BOM, но не са в master BOM
        new_product_ids = set(lot_product_ids) - set(master_product_ids)

        if not new_product_ids:
            return

        # Добавяме новите продукти в master BOM с lot_dynamic = True
        for line in self.line_ids.filtered(lambda l: l.product_id.id in new_product_ids):
            self.master_bom_id.bom_line_ids.create({
                'bom_id': self.master_bom_id.id,
                'product_id': line.product_id.id,
                'product_qty': line.product_qty,
                'product_uom_id': line.product_uom_id.id,
                'lot_dynamic': True,
                'sequence': line.sequence,
            })

        # Изпращане на съобщение за успешна синхронизация
        if new_product_ids:
            self.env['bus.bus']._sendone(
                self.env.user.partner_id,
                'mail.message/inbox',
                {
                    'type': 'info',
                    'tag': 'display_notification',
                    'title': 'Синхронизация',
                    'message': f'{len(new_product_ids)} нови компонента са добавени в master BOM като динамични',
                }
            )

    def action_cancel(self):
        """Отказ на BOM"""
        self.state = 'cancel'

    def action_draft(self):
        """Връщане в чернова"""
        self.state = 'draft'
