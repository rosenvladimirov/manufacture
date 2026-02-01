#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.fields import first

from odoo.addons.mrp.tests.common import TestMrpCommon


class TestMRPProduction(TestMrpCommon):
    def test_line_quantity_with_loss(self):
        """When a BoM line has a loss,
        the loss is added to the quantity of the generated production order line.
        """
        # Arrange
        loss = 0.1  # 10%
        bom = self.bom_1.copy()
        bom_line = first(bom.bom_line_ids)
        bom_line.loss = loss
        product_qty = bom_line.product_qty
        expected_qty = product_qty * (1.0 + loss)

        # Act
        order = self.env["mrp.production"].create(
            {
                "product_id": bom.product_tmpl_id.product_variant_id.id,
                "bom_id": bom.id,
                "product_qty": 1,
            }
        )

        # Assert
        order_line = order.move_raw_ids.filtered(
            lambda ol: ol.bom_line_id == bom_line
        )
        self.assertEqual(order_line.product_uom_qty, expected_qty)
