#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.fields import first

from odoo.addons.mrp.tests.common import TestMrpCommon


class TestMRPProduction(TestMrpCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create a BOM with product_qty=1 so the factor is always
        # equal to the MO quantity (avoids ambiguity with _compute_product_qty).
        cls.bom_loss = cls.env["mrp.bom"].create({
            "product_id": cls.product_4.id,
            "product_tmpl_id": cls.product_4.product_tmpl_id.id,
            "product_uom_id": cls.uom_unit.id,
            "product_qty": 1.0,
            "consumption": "flexible",
            "type": "normal",
            "bom_line_ids": [
                (0, 0, {"product_id": cls.product_2.id, "product_qty": 2}),
                (0, 0, {"product_id": cls.product_1.id, "product_qty": 4}),
            ],
        })

    def _create_mo(self, bom, qty=1):
        return self.env["mrp.production"].create({
            "product_id": bom.product_tmpl_id.product_variant_id.id,
            "bom_id": bom.id,
            "product_qty": qty,
        })

    def test_line_quantity_with_loss(self):
        """Loss factor increases component quantity on the MO."""
        loss = 0.1  # 10 %
        bom_line = first(self.bom_loss.bom_line_ids)
        bom_line.loss = loss

        order = self._create_mo(self.bom_loss)

        # factor = order.product_qty / bom.product_qty
        factor = order.product_qty / self.bom_loss.product_qty
        expected_qty = bom_line.product_qty * factor * (1.0 + loss)

        order_line = order.move_raw_ids.filtered(
            lambda ol: ol.bom_line_id == bom_line
        )
        self.assertAlmostEqual(order_line.product_uom_qty, expected_qty, places=4)

    def test_line_quantity_with_negative_loss(self):
        """Negative loss (efficiency) reduces component quantity."""
        loss = -0.1  # -10 %
        bom_line = first(self.bom_loss.bom_line_ids)
        bom_line.loss = loss

        order = self._create_mo(self.bom_loss)

        factor = order.product_qty / self.bom_loss.product_qty
        expected_qty = bom_line.product_qty * factor * (1.0 + loss)

        order_line = order.move_raw_ids.filtered(
            lambda ol: ol.bom_line_id == bom_line
        )
        self.assertAlmostEqual(order_line.product_uom_qty, expected_qty, places=4)

    def test_line_quantity_with_loss_scaled(self):
        """Loss is correctly applied when MO qty differs from BOM qty."""
        loss = 0.1  # 10 %
        bom_line = first(self.bom_loss.bom_line_ids)
        bom_line.loss = loss

        mo_qty = 5
        order = self._create_mo(self.bom_loss, qty=mo_qty)

        factor = order.product_qty / self.bom_loss.product_qty
        expected_qty = bom_line.product_qty * factor * (1.0 + loss)

        order_line = order.move_raw_ids.filtered(
            lambda ol: ol.bom_line_id == bom_line
        )
        self.assertAlmostEqual(order_line.product_uom_qty, expected_qty, places=4)
