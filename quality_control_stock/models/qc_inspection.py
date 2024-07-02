# Copyright 2014 Serv. Tec. Avanzados - Pedro M. Baeza
# Copyright 2018 Simone Rubino - Agile Business Group
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models

import logging

_logger = logging.getLogger(__name__)


class QcInspection(models.Model):
    _inherit = 'qc.inspection'

    @api.multi
    @api.depends('object_id')
    def _compute_picking(self):
        for inspection in self:
            inspection.picking_id = False
            if inspection.object_id:
                if inspection.object_id._name == 'stock.move':
                    inspection.picking_id = inspection.object_id.picking_id
                elif inspection.object_id._name == 'stock.picking':
                    inspection.picking_id = inspection.object_id
                elif inspection.object_id._name == 'stock.move.line':
                    inspection.picking_id = inspection.object_id.picking_id

    @api.multi
    @api.depends('object_id')
    def _compute_lot(self):
        for inspection in self:
            inspection.lot_id = False
            if inspection.object_id:
                if inspection.object_id._name == 'stock.move.line':
                    inspection.lot_id = \
                        inspection.object_id.lot_id
                elif inspection.object_id._name == 'stock.move':
                    inspection.lot_id = \
                        self.env['stock.move.line'].search([
                            ('lot_id', '!=', False),
                            ('move_id', '=', inspection.object_id.id)
                        ])[:1].lot_id
                elif inspection.object_id._name == 'stock.production.lot':
                    inspection.lot_id = inspection.object_id

    @api.multi
    @api.depends('object_id')
    def _compute_product_id(self):
        """Overriden for getting the product from a stock move."""
        self.ensure_one()
        super(QcInspection, self)._compute_product_id()
        if self.object_id:
            if self.object_id._name == 'stock.move':
                self.product_id = self.object_id.product_id
            elif self.object_id._name == 'stock.move.line':
                self.product_id = self.object_id.product_id
            elif self.object_id._name == 'stock.production.lot':
                self.product_id = self.object_id.product_id

    @api.onchange('object_id')
    def onchange_object_id(self):
        if self.object_id:
            if self.object_id._name == 'stock.move':
                self.qty = self.object_id.quantity_done
            elif self.object_id._name == 'stock.move.line':
                self.qty = self.object_id.qty_done

    @api.multi
    def _get_local_qc_triggers(self, qc_trigger_domain=False):
        self.ensure_one()
        object_id = self.object_id
        _logger.info("OBJECT %s" % object_id)
        if object_id and object_id._name == 'stock.picking':
            return super(QcInspection, self).\
                _get_local_qc_triggers([('picking_type_id', '=', object_id.picking_type_id.id)])
        elif object_id and object_id._name in ('stock.move', 'stock.move.line'):
            return super(QcInspection, self).\
                _get_local_qc_triggers([('picking_type_id', '=', object_id.picking_id.picking_type_id.id)],
                                       object_id.picking_id)
        return super(QcInspection, self)._get_local_qc_triggers(qc_trigger_domain=qc_trigger_domain)

    @api.multi
    def _prepare_inspection_header(self, object_ref, trigger_line):
        res = super(QcInspection, self)._prepare_inspection_header(
            object_ref, trigger_line)
        # Fill qty when coming from pack operations
        if object_ref and object_ref._name == 'stock.move.line':
            res['qty'] = object_ref.move_id.quantity_done
            res['qty_checked'] = object_ref.qty_done
            res['product_id'] = object_ref.product_id.id
            res['lot_id'] = object_ref.lot_id and object_ref.lot_id.id or False
        if object_ref and object_ref._name == 'stock.move':
            res['qty'] = object_ref.quantity_done
            res['qty_checked'] = object_ref.quantity_done
            res['product_id'] = object_ref.product_id.id

        if object_ref and 'product_id' in object_ref._fields:
            if object_ref._name in ('stock.move', 'stock.move.line'):
                if object_ref.picking_id.picking_type_code == 'incoming':
                    res['internal_notes'] = object_ref.product_id.description_pickingin
                elif object_ref.picking_id.picking_type_code == 'internal':
                    res['internal_notes'] = object_ref.product_id.description_picking
                elif object_ref.picking_id.picking_type_code == 'outgoing':
                    res['internal_notes'] = object_ref.product_id.description_pickingout
        _logger.info('VALUES %s' % res)
        return res

    picking_id = fields.Many2one(
        comodel_name="stock.picking", compute="_compute_picking", store=True)
    lot_id = fields.Many2one(
        comodel_name='stock.production.lot', compute="_compute_lot",
        store=True)


class QcInspectionLine(models.Model):
    _inherit = 'qc.inspection.line'

    picking_id = fields.Many2one(
        comodel_name="stock.picking", related="inspection_id.picking_id",
        store=True)
    lot_id = fields.Many2one(
        comodel_name="stock.production.lot", related="inspection_id.lot_id",
        store=True)
