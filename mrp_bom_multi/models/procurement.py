# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError

import logging

_logger = logging.getLogger(__name__)


class ProcurementRule(models.Model):
    _inherit = 'procurement.rule'

    def _get_domain_for_merge(self, vals):
        # _logger.info("VALS %s" % vals)
        domain = [
            ('product_id', '=', vals.get('product_id')),
            ('picking_type_id', '=', vals.get('picking_type_id')),
            ('bom_id', '=', vals.get('bom_id', False)),
            # ('routing_id', '=', vals.get('routing_id', False)),
            ('company_id', '=', vals.get('company_id', False)),
            ('location_dest_id', '=', vals.get('location_dest_id', False)),
        ]
        if vals.get('sale_id', False):
            domain.append(('sale_id', '=', vals.get('sale_id', False)))
        _logger.info("DOMAIN %s" % domain)
        return domain

    @api.multi
    def _run_manufacture(self, product_id, product_qty, product_uom, location_id, name, origin, values):
        company = self.env['res.company']
        partner = self.env['res.partner']
        bom_line = self.env['mrp.bom.line']
        sale_line_ids = self.env['sale.order.line']
        company_id = False
        qty = 0.0
        production_id = self.env['mrp.production']
        if values.get('move_dest_ids') and not self._context.get('stop_split_by_partner', False):
            product_qty_vals = {}
            for move in values['move_dest_ids']:
                if move.production_id:
                    production_id |= move.production_id
                partner |= move.partner_id or move.picking_partner_id
                company |= move.company_id
                qty += move.product_uom_qty
                _logger.info("MOVE %s" % move.name)
                if move.bom_line_id:
                    bom_line |= move.bom_line_id
                if not product_qty_vals.get(move.partner_id):
                    product_qty_vals[move.partner_id] = 0
                # for future develop to separate by partner qty
                product_qty_vals[move.partner_id] += move.product_uom_qty
                if move.sale_line_id:
                    sale_line_ids |= move.sale_line_id
            if partner:
                values.update({
                    'partner_id': partner[0].id,
                })
            if sale_line_ids:
                values.update({
                    'sale_line_ids': [(6, False, sale_line_ids.ids)],
                })
        # _logger.info("_run_manufacture %s:%s(%s)" % (qty, values, product_id.product_tmpl_id.allow_merge))
        if qty != 0.0 and product_id.product_tmpl_id.allow_merge:
            Production = self.env['mrp.production']
            ProductionSudo = Production.sudo().with_context(force_company=values['company_id'].id)
            bom = self._get_matching_bom(product_id, values)
            if not bom:
                msg = _('There is no Bill of Material found for the product %s. Please define a Bill of Material for '
                        'this product.') % (product_id.display_name,)
                raise UserError(msg)

            # update merged data
            if bom_line \
                    and bom_line[0] \
                    and product_id.bom_ids \
                    and bom_line[0].mrp_multi_bom_id.id in product_id.bom_ids.ids:
                bom_id = bom_line[0].mrp_multi_bom_id
            else:
                bom_id = product_id.bom_ids and product_id.bom_ids[-1] or False
            if bom_id and bom_id.routing_id.operation_ids:
                routing_id = bom_id.routing_id.id
            else:
                routing_id = False
            picking_type_id = self.env['mrp.production']._get_default_picking_type()
            move = values.get('move_dest_ids')[0]
            if company:
                company_id = company[0]
            # if self.env['mrp.production.merge'].search([('oring_production_id', '=', production_id.id)]):
            #     return True
            domain_values = dict(values)
            domain_values.update({
                'product_id': product_id.id,
                'product_qty': product_qty,
                'product_uom': product_uom.id,
                'location_dest_id': location_id.id,
                'bom_id': bom_id and bom_id.id or False,
                'routing_id': routing_id,
                'picking_type_id': picking_type_id,
                'company_id': company and company_id.id or False,
                'sale_id': move.sale_line_id and move.sale_line_id.order_id.id or False,
            })
            if move.raw_material_production_id and move.raw_material_production_id.sale_id:
                domain_values.update({
                    'sale_id': move.raw_material_production_id.sale_id.id,
                })
            domain = self._get_domain_for_merge(domain_values)
            for_merge = self.env['mrp.production.merge'].search(domain)
            # for_merge = for_merge.filtered(lambda r: r.production_id.state == 'confirmed')
            # _logger.info("FOR MERGE %s:%s" % (for_merge, for_merge and for_merge[0].production_id.state or 'none'))
            if for_merge and for_merge[0].production_id.state == 'confirmed':
                production = for_merge[0].production_id
                production.sale_line_ids |= sale_line_ids
                update_qty_wizard = self.env['change.production.qty'].create({
                    'mo_id': production.id,
                    'product_qty': production.product_qty + product_qty,
                })
                update_qty_wizard.change_prod_qty()
            else:
                # full copy of logic maybe will be better make monkey patch
                # create the MO as SUPERUSER because the current user may not have the rights to do it (mto product launched by a sale for example)
                production = ProductionSudo.create(
                    self._prepare_mo_vals(product_id, product_qty, product_uom, location_id, name, origin, values, bom))
                if move.procure_method != 'make_to_stock':
                    move.procure_method = 'make_to_stock'
                # _logger.info("PRODUCTION ALLOW SUB %s" % production)
                for move in values['move_dest_ids']:
                    self.env['mrp.production.merge'].create(production._prepare_for_merge(dict(
                        product_qty=product_qty,
                        stock_move_id=move.id,
                        sale_id=production.sale_id and production.sale_id.id or False,
                        sale_line_id=move.sale_line_id,
                        picking_id=move.picking_id and move.picking_id.id or False,
                        oring_production_id=production_id and production_id[0].id or False,
                    )))
            origin_production = values.get('move_dest_ids') and values['move_dest_ids'][0]. \
                raw_material_production_id or False
            orderpoint = values.get('orderpoint_id')
            if orderpoint:
                production.message_post_with_view('mail.message_origin_link',
                                                  values={'self': production, 'origin': orderpoint},
                                                  subtype_id=self.env.ref('mail.mt_note').id)
            if origin_production:
                production.message_post_with_view('mail.message_origin_link',
                                                  values={'self': production, 'origin': origin_production},
                                                  subtype_id=self.env.ref('mail.mt_note').id)
            return True
        return super(ProcurementRule, self)._run_manufacture(product_id, product_qty, product_uom, location_id, name,
                                                             origin, values)

    def _prepare_mo_vals(self, product_id, product_qty, product_uom, location_id, name, origin, values, bom):
        res = super(ProcurementRule, self)._prepare_mo_vals(product_id, product_qty, product_uom, location_id, name,
                                                            origin, values, bom)
        sale = values.get('group_id') and values['group_id'].sale_id or False
        analytic_account_id = sale and sale.analytic_account_id or False
        res.update({
            'partner_id': values.get('partner_id') and values['partner_id'] or False,
            'sale_id': sale and sale.id or False,
            'sale_line_ids': values.get('sale_line_ids') and values['sale_line_ids'] or False,
            'analytic_account_id': analytic_account_id and analytic_account_id.id or False
        })
        if self._context.get('selection_follow'):
            res.update({
                'sub_production': self._context['selection_follow'],
            })
        if values.get('user_id'):
            res.update({
                'user_id': values['user_id'],
            })
        # _logger.info("MANUFACTURE %s" % res)
        return res
