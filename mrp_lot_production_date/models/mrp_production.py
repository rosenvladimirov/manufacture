
# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    """Разширение на Manufacturing Order за етапи"""
    _inherit = 'mrp.production'

    use_stages = fields.Boolean(
        string='Използва етапи',
        related='bom_id.use_production_stages',
        readonly=True
    )

    current_stage_id = fields.Many2one(
        'mrp.bom.stage',
        string='Текущ етап',
        tracking=True,
        copy=False
    )

    current_stage_name = fields.Char(
        string='Име на етап',
        related='current_stage_id.stage_id.name',
        readonly=True
    )

    stage_progress = fields.Float(
        string='Прогрес на етапи (%)',
        compute='_compute_stage_progress',
        store=True
    )

    stage_history_ids = fields.One2many(
        'mrp.production.stage.history',
        'production_id',
        string='История на етапи'
    )

    # ========== ВЛОЖЕНИ MANUFACTURING ORDERS ==========
    parent_production_id = fields.Many2one(
        'mrp.production',
        string='Родителско производство',
        help='Ако това е полуфабрикат, връзка към главната MO',
        ondelete='cascade',
        index=True,
        copy=False
    )

    child_production_ids = fields.One2many(
        'mrp.production',
        'parent_production_id',
        string='Подчинени производства'
    )

    child_production_count = fields.Integer(
        string='Брой подчинени',
        compute='_compute_child_production_count'
    )

    stage_sequence = fields.Integer(
        string='Sequence на етап',
        help='Поредността на етапа в родителската MO',
        copy=False
    )

    semifinished_count = fields.Integer(
        string='Брой полуфабрикати',
        compute='_compute_semifinished_count'
    )

    @api.depends('child_production_ids')
    def _compute_child_production_count(self):
        """Брои подчинените MO"""
        for record in self:
            record.child_production_count = len(record.child_production_ids)

    @api.depends('child_production_ids')
    def _compute_semifinished_count(self):
        """Брои завършените полуфабрикати"""
        for record in self:
            record.semifinished_count = len(record.child_production_ids.filtered(
                lambda m: m.state in ['done', 'progress']
            ))

    @api.depends('current_stage_id', 'bom_id.stage_ids', 'stage_history_ids')
    def _compute_stage_progress(self):
        """Изчислява прогреса на етапите"""
        for record in self:
            if not record.use_stages or not record.bom_id.stage_ids:
                record.stage_progress = 0.0
                continue

            total_stages = len(record.bom_id.stage_ids)
            if not record.current_stage_id:
                # Всички етапи са завършени
                record.stage_progress = 100.0
            else:
                completed_stages = len(record.stage_history_ids)
                record.stage_progress = (completed_stages / total_stages) * 100.0

    @api.model_create_multi
    def create(self, vals_list):
        """При създаване на производствена поръчка, стартираме първия етап"""
        productions = super(MrpProduction, self).create(vals_list)

        for production in productions:
            if production.bom_id and production.bom_id.use_production_stages and not production.parent_production_id:
                # Само за главни MO (не за полуфабрикати)
                first_stage = self.env['mrp.bom.stage'].search([
                    ('bom_id', '=', production.bom_id.id)
                ], order='sequence', limit=1)

                if first_stage:
                    production.current_stage_id = first_stage.id

        return productions

    def action_complete_stage(self):
        """Завършва текущия етап и създава Child MO за полуфабриката"""
        self.ensure_one()

        if not self.current_stage_id:
            raise UserError(_('Няма активен етап за завършване!'))

        if self.state not in ['confirmed', 'progress']:
            raise UserError(_('Производствената поръчка трябва да бъде потвърдена или в процес!'))

        bom_stage = self.current_stage_id

        _logger.info(f"Completing stage {bom_stage.name} for MO {self.name}")

        # Проверка дали всички компоненти са налични
        self._check_stage_components_availability(bom_stage)

        # ========== СЪЗДАВАМЕ CHILD MO ЗА ПОЛУФАБРИКАТА ==========
        child_mo = False
        if bom_stage.auto_create_semifinished and bom_stage.semifinished_product_id:

            # Уверяваме се, че има BOM
            if not bom_stage.semifinished_bom_id:
                _logger.warning(f"No BOM for semifinished product, creating one...")
                bom_stage.action_create_semifinished_bom()

            if not bom_stage.semifinished_bom_id:
                raise UserError(_(
                    'Няма BOM за полуфабриката "%(product)s"!\n'
                    'Моля създайте BOM или натиснете бутона "Създай BOM".',
                    product=bom_stage.semifinished_product_id.name
                ))

            semifinished_qty = bom_stage.compute_semifinished_quantity(self.product_qty)

            _logger.info(f"Creating child MO for {bom_stage.semifinished_product_id.name}, qty: {semifinished_qty}")

            # Създаваме Child Manufacturing Order
            child_mo = self.env['mrp.production'].create({
                'product_id': bom_stage.semifinished_product_id.id,
                'product_qty': semifinished_qty,
                'product_uom_id': bom_stage.semifinished_uom_id.id,
                'bom_id': bom_stage.semifinished_bom_id.id,
                'origin': f'{self.name} - {bom_stage.stage_id.name}',
                'parent_production_id': self.id,  # ⚡ Връзка към родителя
                'stage_sequence': bom_stage.sequence,
                'location_src_id': self.location_src_id.id,
                'location_dest_id': bom_stage.location_id.id if bom_stage.location_id else self.location_dest_id.id,
            })

            # Автоматично потвърждаваме Child MO
            child_mo.action_confirm()

            _logger.info(f"Created child MO: {child_mo.name}")

        # ========== ЗАПИСВАМЕ В ИСТОРИЯТА ==========
        self.env['mrp.production.stage.history'].create({
            'production_id': self.id,
            'bom_stage_id': bom_stage.id,
            'stage_id': bom_stage.stage_id.id,
            'completion_date': fields.Datetime.now(),
            'user_id': self.env.user.id,
            'produced_qty': self.product_qty,
            'semifinished_production_id': child_mo.id if child_mo else False,
        })

        # ========== ПРЕМИНАВАМЕ КЪМ СЛЕДВАЩИЯ ЕТАП ==========
        next_stage = self._move_to_next_stage()

        message = _('✓ Етап "%(stage)s" завършен!', stage=bom_stage.stage_id.name)
        if child_mo:
            message += _('\n→ Създадена MO: %(mo)s за %(product)s (%(qty)s %(uom)s)',
                        mo=child_mo.name,
                        product=child_mo.product_id.name,
                        qty=child_mo.product_qty,
                        uom=child_mo.product_uom_id.name)
        if next_stage:
            message += _('\n→ Следващ етап: %(stage)s', stage=next_stage.stage_id.name)
        else:
            message += _('\n✓ Всички етапи завършени!')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Етап завършен'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }

    def _check_stage_components_availability(self, bom_stage):
        """Проверява дали всички компоненти за етапа са налични"""
        # Тук може да добавите логика за проверка на наличност
        # В момента просто връщаме True
        return True

    def _move_to_next_stage(self):
        """Премества производството към следващия етап"""
        if not self.current_stage_id:
            return False

        # Намираме следващия етап
        next_stage = self.env['mrp.bom.stage'].search([
            ('bom_id', '=', self.bom_id.id),
            ('sequence', '>', self.current_stage_id.sequence)
        ], order='sequence', limit=1)

        if next_stage:
            self.current_stage_id = next_stage.id
            return next_stage
        else:
            # Всички етапи са завършени
            self.current_stage_id = False
            return False

    def action_view_child_productions(self):
        """Показва всички подчинени MO (полуфабрикати)"""
        self.ensure_one()

        return {
            'name': _('Полуфабрикати за %(mo)s', mo=self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('parent_production_id', '=', self.id)],
            'context': {'create': False}
        }

    def action_view_parent_production(self):
        """Показва родителската MO"""
        self.ensure_one()

        if not self.parent_production_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Информация'),
                    'message': _('Това производство няма родителска MO'),
                    'type': 'info',
                }
            }

        return {
            'name': _('Главно производство'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'res_id': self.parent_production_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_stage_history(self):
        """Показва историята на етапите"""
        self.ensure_one()

        return {
            'name': _('История на етапи за %(mo)s', mo=self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production.stage.history',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'create': False}
        }
