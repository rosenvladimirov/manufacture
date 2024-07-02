# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
import logging

from odoo.exceptions import AccessError
from odoo.tools import float_compare
from odoo.addons.queue_job.job import job
from odoo.addons import decimal_precision as dp

_logger = logging.getLogger(__name__)


class MrpSplitProductionWizard(models.TransientModel):
    _name = "wiz.mrp.split.production"
    _description = "Wizard for split production"

    @api.model
    def _get_default_picking_type(self):
        return self.env['stock.picking.type'].search([
            ('code', '=', 'mrp_operation'),
            ('warehouse_id.company_id', 'in', [self.env.context.get('company_id', self.env.user.company_id.id), False])],
            limit=1).id

    split_to = fields.Integer(
        string='Split to parts',
        default=1
    )
    production_ids = fields.Many2many(
        comodel_name='mrp.production',
        string='Productions',
    )
    production_line_ids = fields.One2many(
        string="MRP production lines",
        comodel_name="wiz.mrp.split.production.line",
        inverse_name="production_split_wizard_id",
    )
    sale_id = fields.Many2one(
        comodel_name='sale.order',
        string='Sale order',
    )
    mrp_product_tmpl_id = fields.Many2one(
        comodel_name='product.template',
        string="Product Template")
    mrp_product_attribute_ids = fields.One2many(
        comodel_name='template.split.configurator.attribute',
        inverse_name='split_manage_variant_id',
        string='Product Template configurator Attributes')
    picking_type_id = fields.Many2one(
        'stock.picking.type', 'Operation Type',
        default=_get_default_picking_type, required=True)
    location_src_id = fields.Many2one(
        comodel_name='stock.location',
        string='Source material location',
    )
    location_dest_id = fields.Many2one(
        comodel_name='stock.location',
        string='Destination production location',
    )
    state = fields.Selection(
        selection=lambda self: self._selection_get_states(),
        string='Production do',
        default='split',
        copy=False,
        readonly=False,
        states={'split': [('readonly', False)]},
    )
    date_planned_start = fields.Datetime(
        'Deadline Start', default=fields.Datetime.now,
    )
    date_planned_finished = fields.Datetime(
        'Deadline End', default=fields.Datetime.now,
    )
    part = fields.Float(
        string='Part size',
        digits=dp.get_precision('Product Unit of Measure'),
        compute='_compute_part',
    )
    rest = fields.Float(
        string='Res of parts',
        digits=dp.get_precision('Product Unit of Measure'),
        compute='_compute_rest',
    )
    force_mark_as_done = fields.Boolean('Force mark as done', default=True)
    force_un_reserve_done = fields.Boolean('Force un-reserve', default=True)

    @api.model
    def _selection_get_states(self):
        states = [
            ('split', _('Split')),
            ('restore', _('Restore')),
            ('plan', _('Plan order')),
            ('backorder', _('Back order')),
            ('produce', _('Produce production')),
            ('location', _('Change locations')),
            ('bom', _('BOM update')),
            ('dates', _('Dates change')),
            ('reserve', _('UN-Reserve')),
            ('cancel', _('Cancel')),
            ('delete', _('Delete'))
        ]
        return states

    @api.onchange('mrp_product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        for record in self:
            template = record.mrp_product_tmpl_id
            if template.attribute_line_ids:
                record.mrp_product_attribute_ids = [(6, False, [])]
                values_ids = []

                for val in template.attribute_line_ids:
                    attribute = template.attribute_line_ids.filtered(lambda x: x.attribute_id == val.attribute_id)
                    values_ids.append((0, 0, {
                        'product_tmpl_id': template.id,
                        'attribute_id': val.attribute_id.id,
                        'type_attribute': val.type_attribute,
                        'possible_value_ids': attribute.value_ids.sorted(),
                    }))
                # _logger.info("VALUES COMPONENT %s" % values_ids)
                record.mrp_product_attribute_ids = values_ids
            else:
                record.mrp_product_attribute_ids = [(6, False, [])]

    @api.multi
    def _compute_part(self):
        for record in self:
            record.part = sum([x.part for x in record.production_line_ids])

    @api.multi
    def _compute_rest(self):
        for record in self:
            record.part = sum([x.part for x in record.production_line_ids])

    @api.onchange('production_line_ids')
    @api.depends('part', 'rest')
    def onchange_production_line_ids(self):
        for record in self:
            record.part = sum([x.part for x in record.production_line_ids])
            record.part = sum([x.part for x in record.production_line_ids])

    @api.onchange('mrp_product_attribute_ids')
    @api.depends('production_line_ids')
    def _onchange_product_attribute_ids(self):
        for record in self:
            value_ids = record.mrp_product_attribute_ids.mapped('value_id')
            system_all = record.mrp_product_attribute_ids.filtered(lambda r: r.system_all)
            _logger.info('CHECK VALUES %s or %s' % (value_ids, system_all))
            if value_ids or system_all:
                mrp_product_attribute_ids = value_ids
                for value in system_all:
                    attribute_line_ids = record.mrp_product_tmpl_id. \
                        attribute_line_ids.filtered(lambda r: r.attribute_id == value.attribute_id)
                    if attribute_line_ids:
                        for value_id in attribute_line_ids.mapped('value_ids'):
                            mrp_product_attribute_ids |= value_id
                production_ids = record.production_line_ids.mapped('production_id')
                _logger.info('CHECK VALUES 1 %s' % list(set(mrp_product_attribute_ids)))
                if record.mrp_product_tmpl_id:
                    production_ids = production_ids. \
                        filtered(lambda r: r.product_id.product_tmpl_id == record.mrp_product_tmpl_id)
                _logger.info('CHECK VALUES 2 %s' % production_ids)
                production_ids = production_ids. \
                    filtered(lambda r: set(r.product_id.attribute_value_ids.ids) & set(mrp_product_attribute_ids.ids))
                _logger.info('CHECK VALUES 3 %s' % production_ids)
                if production_ids:
                    record.production_line_ids = [(6, False, [])]
                    record.production_line_ids = self._collect_productions(production_ids)
                    record.production_ids = [(6, False, production_ids.ids)]
                    record.onchange_split_to()
            else:
                if record.sale_id:
                    domain = [('state', '=', 'confirmed')]
                    domain += [('sale_id', '=', record.sale_id.id)]
                    production_ids = self.env['mrp.production'].search(domain)
                    record.production_line_ids = [(6, False, [])]
                    record.production_line_ids = self._collect_productions(production_ids)
                    record.production_ids = [(6, False, production_ids.ids)]
                    record.onchange_split_to()

    @api.model
    def _collect_productions(self, production_ids):
        production = []
        sequence = 1
        for line in production_ids.sorted(lambda r: r.name):
            production.append((0, False, {
                'production_id': line.id,
                'bom_id': line.bom_id.id,
                'bom_ids': [(6, False, line.product_id.bom_ids.ids)],
                'product_id': line.product_id.id,
                'product_qty': line.product_qty,
                'oring_product_qty': line.oring_product_qty,
                'sequence': sequence,
                'location_src_id': line.location_src_id.id,
                'location_dest_id': line.location_dest_id.id,
                'date_planned_start': line.date_planned_start,
                'date_planned_finished': line.date_planned_finished,
            }))
            sequence += 1
        return production

    @api.model
    def default_get(self, fields_list):
        res = super(MrpSplitProductionWizard, self).default_get(fields_list)
        production_ids = False
        if self._context.get('active_ids'):
            production_ids = self.env['mrp.production'].browse(self._context['active_ids'])
        if production_ids:
            production = self._collect_productions(production_ids)
            res['production_line_ids'] = production
            res['production_ids'] = [(6, False, production_ids.ids)]
        return res

    @api.onchange('sale_id')
    def onchange_sale_id(self):
        for record in self:
            if record.sale_id:
                production_ids = self.env['mrp.production']. \
                    search([('sale_id', '=', record.sale_id.id), ('state', '=', 'confirmed')])
                if production_ids:
                    record.production_line_ids = [(6, False, [])]
                    record.production_line_ids = self._collect_productions(production_ids)
                    record.production_ids = [(6, False, production_ids.ids)]

    @api.onchange('split_to')
    @api.depends('production_line_ids')
    def onchange_split_to(self):
        for record in self:
            if record.split_to > 0:
                for line in record.production_line_ids:
                    line.split_to = record.split_to
                    line.part, line.rest = divmod(line.product_qty, record.split_to)

    @api.onchange('date_planned_start', 'date_planned_finished')
    @api.depends('production_line_ids')
    def onchange_dates(self):
        for record in self:
            for line in record.production_line_ids:
                if record.date_planned_start:
                    line.date_planned_start = record.date_planned_start
                if record.date_planned_finished:
                    line.date_planned_finished = record.date_planned_finished

    @api.onchange('location_src_id', 'location_dest_id', 'picking_type_id')
    @api.depends('production_line_ids')
    def onchange_locations(self):
        for record in self:
            for line in record.production_line_ids:
                if record.location_src_id:
                    line.location_src_id = record.location_src_id
                if record.location_dest_id:
                    line.location_dest_id = record.location_dest_id
                if record.picking_type_id:
                    line.picking_type_id = record.picking_type_id

    @api.multi
    def action_all(self):
        action = {'type': 'ir.actions.act_window_close'}
        for record in self:
            if record.state == 'split':
                action = record.action_split_production()
            elif record.state == 'restore':
                action = record.action_restore_change()
            elif record.state == 'backorder':
                action = record.action_backorder_production()
            elif record.state == 'produce':
                action = record.action_produce_production()
            elif record.state == 'location':
                action = record.action_change_location_production()
            elif record.state == 'bom':
                action = record.action_bom_change()
            elif record.state == 'dates':
                action = record.action_dates_production()
            elif record.state == 'reserve':
                action = record.action_reserve_production()
            elif record.state == 'cancel':
                action = record.action_cancel_production()
            elif record.state == 'delete':
                action = record.action_delete_production()
        return action

    @api.multi
    def action_split_production(self):
        for record in self:
            production_copy_ids = self.env['mrp.production']
            for line in record.production_line_ids:
                production = line.production_id
                production.oring_product_qty = production.product_qty
                product_qty = 0.0
                rest_product_qty = production.product_qty
                for line_range in range(0, line.split_to):
                    if line.part > 0:
                        product_qty += line.part
                        production_copy = production.copy()
                        production_copy.date_planned_start = production.date_planned_start
                        production_copy.date_planned_finished = production.date_planned_finished
                        production_copy.date_start = production.date_start
                        production_copy.date_finished = production.date_finished
                        production_copy.origin = "%s:%s" % (production.origin, production.name)
                        production_copy.location_src_id = line.location_src_id
                        production_copy.location_dest_id = line.location_dest_id
                        production_copy_ids |= production_copy
                        update_qty_wizard = self.env['change.production.qty'].create({
                            'mo_id': production_copy.id,
                            'product_qty': line.part,
                        })
                        update_qty_wizard.change_prod_qty()
                        production_copy.button_unreserve()
                if product_qty != 0.0 and production.oring_product_qty - product_qty > 0:
                    production_copy_ids |= production
                    rest = production.oring_product_qty - product_qty
                    if line.rest != 0.0:
                        rest = line.rest
                    product_qty += rest
                    production_copy = production.copy()
                    production_copy.date_planned_start = production.date_planned_start
                    production_copy.date_planned_finished = production.date_planned_finished
                    production_copy.date_start = production.date_start
                    production_copy.date_finished = production.date_finished
                    production_copy.origin = "%s:%s" % (production.origin, production.name)
                    production_copy.location_src_id = production.location_src_id
                    production_copy.location_dest_id = production.location_dest_id
                    production_copy_ids |= production_copy
                    update_qty_wizard = self.env['change.production.qty'].create({
                        'mo_id': production_copy.id,
                        'product_qty': rest,
                    })
                    update_qty_wizard.change_prod_qty()
                    production.button_unreserve()
                rest_product_qty -= product_qty
                if float_compare(rest_product_qty, 0.0, precision_digits=production.product_uom_id.rounding) == 0:
                    production.action_cancel()
                    production.origin = '%s(canceled  by split)' % production.origin
            action_ref = self.env.ref('mrp.mrp_production_action')
            if not action_ref or not production_copy_ids:
                return {'type': 'ir.actions.act_window_close'}
            action = action_ref.read()[0]
            action['domain'] = [('id', 'in', production_copy_ids.ids)]
            return action
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    @job(default_channel='root.mrp')
    def server_action_cancel_production(self):
        for record in self:
            for line in record.production_line_ids:
                line.production_id.action_cancel()

    @api.multi
    def action_cancel_production(self):
        self.with_delay().server_action_cancel_production()
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    @job(default_channel='root.mrp')
    def server_action_change_location_production(self):
        for record in self:
            for line in record.production_line_ids:
                line.production_id.picking_type_id = line.picking_type_id
                line.production_id.location_src_id = line.location_src_id
                line.production_id.location_dest_id = line.location_dest_id
                for move_id in line.production_id.move_raw_ids:
                    move_id.location_id = line.location_src_id
                    for move_line_id in move_id.move_line_ids:
                        move_line_id.location_id = line.location_src_id
                for move_id in line.production_id.move_finished_ids:
                    move_id.location_dest_id = line.location_dest_id
                    for move_line_id in move_id.move_line_ids:
                        move_line_id.location_dest_id = line.location_dest_id
                for stock_move_line_id in line.production_id.stock_move_lines_ids. \
                        filtered(lambda r: r.state != 'cancel'
                                           and r.location_dest_id != line.location_src_id):
                    stock_move_line_id.location_dest_id = line.location_src_id
                    stock_move_line_id.picking_id.location_dest_id = line.location_src_id

    @api.multi
    def action_change_location_production(self):
        self.with_delay().server_action_change_location_production()
        return {'type': 'ir.actions.act_window_close'}

    @api.onchange('picking_type_id')
    def onchange_picking_type(self):
        location = self.env.ref('stock.stock_location_stock')
        try:
            location.check_access_rule('read')
        except (AttributeError, AccessError):
            location = self.env['stock.warehouse'].search([('company_id', '=', self.env.user.company_id.id)], limit=1).lot_stock_id
        self.location_src_id = self.picking_type_id.default_location_src_id.id or location.id
        self.location_dest_id = self.picking_type_id.default_location_dest_id.id or location.id

    @api.multi
    @job(default_channel='root.mrp')
    def server_action_plan_production(self):
        for record in self:
            for line in record.production_line_ids.filtered(lambda r: r.production_id.state == 'confirmed'):
                line.production_id.button_plan()

    @api.multi
    def action_change_plan_production(self):
        self.with_delay().server_action_plan_production()
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    def action_delete_production(self):
        for record in self:
            for line in record.production_line_ids.filtered(lambda r: r.production_id.state == 'confirmed'):
                line.production_id.action_cancel()
                line.production_id.unlink()
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    def action_regenerate_sub_levels(self):
        for record in self:
            productions = record.production_line_ids.mapped('production_id')
            if len(productions.ids) > 0:
                for production in productions:
                    production.write({'sub_production': 'sub'})
                productions.with_delay().server_update_procurement_for_moves()
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    @job(default_channel='root.mrp')
    def server_action_bom_change(self):
        for record in self:
            for line in record.production_line_ids:
                production = line.production_id
                if line.bom_id != production.bom_id:
                    production.bom_id = line.bom_id
                update_qty_wizard = self.env['change.production.qty'].create({
                    'mo_id': production.id,
                    'product_qty': production.product_qty,
                    'update_base_new_bom': True,
                })
                update_qty_wizard.change_prod_qty()

    @api.multi
    def action_bom_change(self):
        self.with_delay().server_action_bom_change()
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    def action_restore_change(self):
        for record in self:
            for line in record.production_line_ids:
                production = line.production_id
                update_qty_wizard = self.env['change.production.qty'].create({
                    'mo_id': production.id,
                    'product_qty': production.oring_product_qty,
                })
                update_qty_wizard.change_prod_qty()
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    def action_dates_production(self):
        for record in self:
            for line in record.production_line_ids:
                line.production_id.date_planned_start = line.date_planned_start
                line.production_id.date_planned_finished = line.date_planned_finished
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    def action_reserve_production(self):
        for record in self:
            for line in record.production_line_ids:
                line.button_unreserve()

    @api.multi
    def action_produce_production(self):
        self.with_delay().server_action_produce_production()
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    def server_action_produce_production(self):
        for record in self:
            production_produce_ids = self.env['mrp.production']
            for line in record.production_line_ids:
                production_produce_ids |= line.production_id
            for picking_id in production_produce_ids.mapped('picking_move_ids').filtered(lambda r: r.state == 'done'):
                picking_id.mrp_action_assign()
            production_produce_ids = self.env['mrp.production']
            for line in record.production_line_ids:
                production = line.production_id
                if production.check_to_done \
                        and (not any([x for x in production.move_raw_ids if x.product_uom_qty != x.quantity_done])
                             or record.force_mark_as_done):
                    _logger.info(
                        f"START MARK AS DONE: {production.name} - {production.check_to_done}:{record.force_mark_as_done}")
                    try:
                        # production.button_mark_done()
                        production.post_inventory()
                        moves_to_cancel = (production.move_raw_ids | production.move_finished_ids).filtered(
                            lambda x: x.state not in ('done', 'cancel'))
                        moves_to_cancel._action_cancel()
                        production.write({'state': 'done', 'date_finished': fields.Datetime.now()})
                    except ValueError:
                        _logger.info(_('Error when validate production order'))
                else:
                    produce_wizard = self.env['wiz.mrp.workorder.process'].with_context({
                        # 'active_model': 'mrp.production',
                        # 'active_id': production.id,
                        'default_mo_id': production.id,
                        'force_mark_as_done': record.force_mark_as_done,
                        'force_un_reserve_done': record.force_un_reserve_done,
                        # 'default_product_qty': line.part,
                    }).create({})
                    produce_wizard.server_action_process_workorder()
                    if production.state != 'done':
                        production_produce_ids |= production

            action_ref = self.env.ref('mrp.mrp_production_action')
            if not action_ref or not production_produce_ids:
                return {'type': 'ir.actions.act_window_close'}
            action = action_ref.read()[0]
            action['domain'] = [('id', 'in', production_produce_ids.ids)]
            return action
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    def action_backorder_production(self):
        for record in self:
            production_copy_ids = self.env['mrp.production']
            for line in record.production_line_ids:
                production = line.production_id
                production.oring_product_qty = production.product_qty
                rest_product_qty = production.product_qty - production.qty_produced
                production_copy = production.copy()
                production_copy.date_planned_start = production.date_planned_start
                production_copy.date_planned_finished = production.date_planned_finished
                production_copy.date_start = production.date_start
                production_copy.date_finished = production.date_finished
                production_copy.stock_move_lines_ids = [(6, False, production.stock_move_lines_ids.ids)]
                production_copy.origin = "%s:%s" % (production.origin, production.name)
                production_copy_ids |= production_copy
                update_qty_wizard = self.env['change.production.qty'].create({
                    'mo_id': production_copy.id,
                    'product_qty': rest_product_qty,
                })
                update_qty_wizard.change_prod_qty()
                production_copy.button_unreserve()

                update_qty_wizard = self.env['change.production.qty'].create({
                    'mo_id': production.id,
                    'product_qty': production.qty_produced,
                })
                update_qty_wizard.change_prod_qty()
                # for wo in production.workorder_ids.filtered(lambda r: r.state == 'progress'):
                #     wo.button_finish()
                production_copy_ids |= production
                production.button_mark_done()

            action_ref = self.env.ref('mrp.mrp_production_action')
            if not action_ref or not production_copy_ids:
                return {'type': 'ir.actions.act_window_close'}
            action = action_ref.read()[0]
            action['domain'] = [('id', 'in', production_copy_ids.ids)]
            return action
        return {'type': 'ir.actions.act_window_close'}

    @api.model_cr
    def _transient_clean_rows_older_than(self, seconds):
        assert self._transient, "Model %s is not transient, it cannot be vacuumed!" % self._name
        # Never delete rows used in last 5 minutes
        seconds = max(seconds, 300)
        query = ("SELECT id FROM " +
                 self._table + " WHERE"
                               " COALESCE(write_date, create_date, (now() at time zone 'UTC'))::timestamp"
                               " < ((now() at time zone 'UTC') - interval %s)")
        self._cr.execute(query, ("%s seconds" % seconds,))
        ids = [x[0] for x in self._cr.fetchall()]
        # Remove before it the rows in wiz.mrp.split.production
        if self._table == 'wiz.mrp.split.production':
            for line in self.sudo().browse(ids):
                lines = self.env['wiz.mrp.split.production.line'].sudo().search(
                    [('production_split_wizard_id', '=', line.id)])
                if lines:
                    lines.sudo().unlink()
                variants = self.env['template.split.configurator.attribute'].sudo(). \
                    search([('split_manage_variant_id', '=', line.id)])
                if variants:
                    variants.sudo().unlink()
        self.sudo().browse(ids).unlink()
