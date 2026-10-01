# -*- coding: utf-8 -*-
"""№119 (Любо, 01.10): „Plan“ от списъка с МО → списъкът наново с филтъра
„In Preparation“, не „To Do“. От формата на МО — без промяна."""
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPlanFromList(TransactionCase):

    def setUp(self):
        super().setUp()
        self.MO = self.env["mrp.production"]
        # МО, което „е минало в подготовка“ — за помощника стига да не е празно.
        self.moved = self.MO.browse([1])

    def test_from_the_list_opens_in_preparation(self):
        action = self.MO.with_context(staged_plan_from_list=True)._staged_plan_list_action(self.moved)
        self.assertTrue(action)
        self.assertEqual(action["res_model"], "mrp.production")
        self.assertEqual(action["context"], {"search_default_staged_in_preparation": 1})

    def test_from_the_form_nothing_changes(self):
        self.assertFalse(self.MO._staged_plan_list_action(self.moved))

    def test_nothing_moved_nothing_changes(self):
        self.assertFalse(self.MO.with_context(staged_plan_from_list=True)
                         ._staged_plan_list_action(self.MO.browse()))

    def test_the_list_button_carries_the_mark(self):
        arch = self.MO.get_view(self.env.ref("mrp.mrp_production_tree_view").id, "list")["arch"]
        self.assertIn("staged_plan_from_list", arch,
                      "без знака от изгледа „Plan“ от списъка не различава списъка от формата")
