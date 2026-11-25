# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from odoo.tests import Form, tagged

from .common import CrewRosterCommon


@tagged("post_install", "-at_install", "crew_roster")
class TestPlanSelect(CrewRosterCommon):
    """„Plan Work Center“: един център (Р12) или няколко с алтернативите
    им (Р40)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wc_alt = cls._make_workcenter("WC Alternative", cls.cal_pg)
        cls.wc_pg.alternative_workcenter_ids = cls.wc_alt

    def _wizard(self, workcenters):
        return self.env["mrp.workcenter.plan.select"].create(
            {"workcenter_ids": [(6, 0, workcenters.ids)]}
        )

    def test_open_roster_for_selected_workcenter(self):
        action = self._wizard(self.wc_2x12).action_open_roster()
        self.assertEqual(action["res_model"], "mrp.workcenter.roster")
        self.assertEqual(action["domain"], [("workcenter_id", "=", self.wc_2x12.id)])
        self.assertEqual(action["context"], {"crew_workcenter_id": self.wc_2x12.id})
        # Ф3: никакъв default_* в контекста.
        self.assertFalse([k for k in action["context"] if k.startswith("default_")])

    def test_open_roster_for_several_workcenters(self):
        """Р40: няколко центъра — домейн по всички, без центъра в контекста."""
        action = self._wizard(self.wc_pg | self.wc_2x12).action_open_roster()
        self.assertEqual(
            action["domain"],
            [("workcenter_id", "in", (self.wc_pg | self.wc_2x12).ids)],
        )
        self.assertEqual(action["context"], {})

    def test_single_workcenter_gantt_is_the_plan_button(self):
        """Един център — същото действие като smart бутона „Plan“."""
        action = self._wizard(self.wc_2x12).action_open_gantt()
        self._assert_same_crew_gantt_action(action, self.wc_2x12.action_crew_plan_gantt())

    def test_several_workcenters_gantt_shows_all(self):
        """Р40: Гантът е по всички центрове наведнъж; съветникът ги получава,
        „Recompute“ (един център) — не."""
        both = self.wc_pg | self.wc_2x12
        action = self._wizard(both).action_open_gantt()
        # Краткосрочният план — само планираните МО (Росен 14.10.2026).
        self.assertEqual(
            action["domain"],
            [("workcenter_id", "in", both.ids), ("production_id.is_planned", "=", True)],
        )
        self._assert_crew_gantt_context(action["context"], {"crew_workcenter_ids": both.ids})
        self.assertEqual(
            action["view_id"][0],
            self.env.ref("mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_view").id,
        )

    def test_selected_workcenter_adds_its_alternatives(self):
        """Р40: изборът на център довлича алтернативите му."""
        with Form(self.env["mrp.workcenter.plan.select"]) as form:
            form.workcenter_ids.add(self.wc_pg)
            self.assertEqual([wc.id for wc in form.workcenter_ids], [self.wc_pg.id, self.wc_alt.id])

    def test_removed_alternative_stays_removed(self):
        """Махната алтернатива не се връща при следващ избор."""
        with Form(self.env["mrp.workcenter.plan.select"]) as form:
            form.workcenter_ids.add(self.wc_pg)
            form.workcenter_ids.remove(id=self.wc_alt.id)
            form.workcenter_ids.add(self.wc_2x12)
            self.assertEqual(
                sorted([wc.id for wc in form.workcenter_ids]),
                sorted([self.wc_pg.id, self.wc_2x12.id]),
            )
