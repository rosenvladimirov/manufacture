#  Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    def _put_in_pack(self, packing_qty):
        packages = self.env['stock.quant.package']
        finished_move_line_ids = self.production_id.finished_move_line_ids.filtered(lambda p: not p.result_package_id)
        if len(finished_move_line_ids.ids) > 0 and self.product_id.packaging_ids:
            package_id = False
            # lot_ids = finished_move_line_ids.mapped('lot_id')
            package_qty_count = len(finished_move_line_ids) // packing_qty
            for index in range(0, int(package_qty_count) + 1):
                if not package_id:
                    package_id = self.env['stock.quant.package'].create({})
                package_lot_ids = finished_move_line_ids[int(packing_qty) * index:int(packing_qty) * index + int(packing_qty)]
                package_lot_ids.write({
                    'result_package_id': package_id.id,
                })
            packages |= package_id
            if len(finished_move_line_ids.ids) > packing_qty.qty:
                self._put_in_pack(packing_qty)
        return packages

    def _get_ranges(self):
        packages = self.production_id.finished_move_line_ids.mapped('result_package_id')
        res = {}
        for package in packages:
            ranges = []
            field_name = self.product_id.product_tmpl_id.use_ref and 'ref' or 'name'
            tracking = ['serial']
            finished_move_line_ids = self.production_id.finished_move_line_ids. \
                filtered(lambda r: r.result_package_id.id == package.id
                                   and r.product_id.product_tmpl_id.tracking in tracking)
            lots = [getattr(x, field_name) for x in finished_move_line_ids.mapped('lot_id') if x.name.isdigit()]
            if len(lots) > 100:
                lots = lots[:100]
            if len(lots) > 0:
                try:
                    lots = list(map(int, lots))
                    lots = sorted(lots, key=lambda r: r)
                    ranges.append([lots[0], lots[-1]])
                    res[package] = ranges
                except ValueError:
                    _logger.info("Convert SN/Lot impossible %s" % [getattr(x, field_name) for x in
                                                                   finished_move_line_ids.mapped('lot_id') if
                                                                   x.name.isdigit()])
        return res

    def action_package_glabel_print(self):
        self.ensure_one()
        ranges = self._get_ranges()
        package_label = self.product_id.product_tmpl_id.use_ref and 'package_label_102_76' or 'package_label_ref_102_76'
        ctx = self._context.copy()
        if self._context.get('packages'):
            packages = self.env['stock.quant.package'].browse(self._context['packages'])
        else:
            packages = self.production_id.finished_move_line_ids.mapped('result_package_id')
        for package in packages:
            ctx['active_model'] = 'stock.quant.package'
            ctx['active_ids'] = package.ids
            ctx['picking_id'] = self.id
            ctx['picking_ranges'] = ranges[package]
            ctx['picking_ref_ranges'] = ranges[package]
            ctx['gap_in_ranges'] = ['']
            docids = self.env['stock.quant.package'].browse(packages.ids)
            if docids:
                # _logger.info("Actions %s" % self.env['ir.actions.report']._get_report_from_name('package_label_60_30'))
                return self.env['ir.actions.report']._get_report_from_name(package_label).with_context(ctx).report_action(
                    docids)
        else:
            return False

    @api.multi
    def record_production(self):
        self.ensure_one()
        res = super().record_production()
        packing_qty_ids = self.product_id.packaging_ids
        if len(packing_qty_ids) > 0:
            packing_qty = int(packing_qty_ids[0].qty)
            if self.qty_produced // packing_qty and self.qty_produced // packing_qty:
                packages = self._put_in_pack(packing_qty)
                action = self.env.ref('mrp_workorder_lot_series.action_package_glabel_print')
                action.with_context(dict(self._context, packages=packages)).run()
        return res

    def _check_product(self, product, qty=1.0, lot=False, code=False, use_date=False):
        if product and product.product_tmpl_id.use_ref and not code:
            code = lot
        return super()._check_product(product, qty=qty, lot=lot, code=code, use_date=use_date)
