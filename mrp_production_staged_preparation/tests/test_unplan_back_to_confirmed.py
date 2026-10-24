# -*- coding: utf-8 -*-
"""№159 (Любо, 13.10): Plan → „ПФП“ (preparation), Unplan → обратно Confirmed.
Пусната поръчка (staged_released) не се отпланира — трансферите вече са родени."""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestUnplanBackToConfirmed(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        komponent = cls.env["product.product"].create({"name": "T159 component", "is_storable": True})
        cls.gotov = cls.env["product.product"].create({"name": "T159 finished", "is_storable": True})
        wc = cls.env["mrp.workcenter"].create({
            "name": "T159 center",
            "resource_calendar_id": cls.env.ref("resource.resource_calendar_std").id})
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.gotov.product_tmpl_id.id, "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {"product_id": komponent.id, "product_qty": 1.0})],
            "operation_ids": [(0, 0, {"name": "T159 op", "workcenter_id": wc.id,
                                      "time_cycle_manual": 30.0})]})

    def _mo(self):
        mo = self.env["mrp.production"].create(
            {"product_id": self.gotov.id, "product_qty": 1.0, "bom_id": self.bom.id})
        mo.picking_type_id.staged_preparation_enabled = True
        mo.action_confirm()
        return mo

    def test_plan_then_unplan_is_confirmed_again(self):
        mo = self._mo()
        mo.button_plan()
        self.assertEqual(mo.state, "preparation")
        self.assertTrue(mo.is_planned)
        mo.button_unplan()
        self.assertFalse(mo.is_planned)
        self.assertEqual(mo.state, "confirmed")

    def test_released_mo_is_not_unplanned(self):
        mo = self._mo()
        mo.button_plan()
        mo.staged_released = True
        with self.assertRaises(UserError):
            mo.button_unplan()
        self.assertEqual(mo.state, "preparation")
