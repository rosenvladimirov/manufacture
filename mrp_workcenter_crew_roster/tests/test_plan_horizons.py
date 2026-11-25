# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Краткосрочно и дългосрочно планиране (Росен 14.10.2026).

„Plan Work Center“ (краткосрочно) — само поръчките на планирани МО.
„Long-Term Planning“ — ново меню, всички центрове без избора, всички
поръчки без започнатите, приключените и отменените; същият Гант.
"""
from datetime import date

from freezegun import freeze_time

from odoo.tests import tagged

from .common import CrewWorkorderCommon

DAY = date(2026, 10, 20)


@tagged("post_install", "-at_install", "crew_roster")
class TestPlanHorizons(CrewWorkorderCommon):

    def _orders(self):
        # В Odoo 19 МО е планирано, щом поръчката му има дати
        # (`_compute_is_planned`); непланираната е без дати.
        planned = self._make_wo(self.wc_pg, self._utc(DAY, 8))
        unplanned = self.WO.create({
            "name": "Crew operation",
            "workcenter_id": self.wc_pg.id,
            "production_id": self._make_mo().id,
            "product_uom_id": self.product.uom_id.id,
            "duration_expected": 60.0,
        })
        started = self._make_wo(self.wc_pg, self._utc(DAY, 12))
        started.state = "progress"
        self.assertTrue(planned.production_id.is_planned)
        self.assertFalse(unplanned.production_id.is_planned)
        return planned, unplanned, started

    def _shown(self, action, workorders):
        return self.WO.search(action["domain"] + [("id", "in", workorders.ids)])

    def test_short_term_shows_only_planned_orders(self):
        planned, unplanned, started = self._orders()
        action = self.wc_pg.action_crew_plan_gantt()
        self.assertEqual(
            self._shown(action, planned | unplanned | started), planned | started
        )

    def test_long_term_shows_all_but_started_done_cancelled(self):
        planned, unplanned, started = self._orders()
        done = self._make_wo(self.wc_pg, self._utc(DAY, 14))
        done.state = "done"
        cancelled = self._make_wo(self.wc_pg, self._utc(DAY, 15))
        cancelled.state = "cancel"
        action = self.env["mrp.workcenter"].action_crew_plan_long_term()
        self.assertEqual(
            self._shown(action, planned | unplanned | started | done | cancelled),
            planned | unplanned,
        )

    def test_long_term_is_our_gantt_for_every_work_center(self):
        action = self.env["mrp.workcenter"].action_crew_plan_long_term()
        self.assertEqual(
            action["view_id"][0] if isinstance(action["view_id"], (list, tuple))
            else action["view_id"],
            # стъпка 2: дългосрочният е върху „началото/края в плана“
            self.env.ref("mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_longterm_view").id,
        )
        workcenters = self.env["mrp.workcenter"].search([])
        self.assertEqual(set(action["context"]["crew_workcenter_ids"]), set(workcenters.ids))
        self.assertNotIn("crew_workcenter_id", action["context"])

    def test_long_term_menu(self):
        menu = self.env.ref("mrp_workcenter_crew_roster.menu_mrp_workcenter_plan_long_term")
        self.assertEqual(menu.parent_id, self.env.ref("mrp.mrp_planning_menu_root"))
        result = menu.action.run()
        self.assertEqual(result["name"], "Long-Term Planning")


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time("2026-10-05 08:00:00")
class TestLongTermUnplanned(CrewWorkorderCommon):
    """Стъпка 2: непланираните в дългосрочния план (Росен 14.10.2026)."""

    def _unplanned(self, minutes=90.0):
        mo = self._make_mo()
        mo.date_start = self._utc(DAY, 9)
        return self.WO.create({
            "name": "Crew operation",
            "workcenter_id": self.wc_pg.id,
            "production_id": mo.id,
            "product_uom_id": self.product.uom_id.id,
            "duration_expected": minutes,
        })

    def test_unplanned_stands_on_the_dates_of_its_order(self):
        wo = self._unplanned()
        self.assertFalse(wo.date_start)
        self.assertTrue(wo.crew_is_unplanned)
        self.assertEqual(wo.crew_gantt_start, self._utc(DAY, 9))
        self.assertEqual(wo.crew_gantt_stop, self._utc(DAY, 10, 30))

    def test_planned_uses_its_own_dates(self):
        wo = self._make_wo(self.wc_pg, self._utc(DAY, 8))
        self.assertFalse(wo.crew_is_unplanned)
        self.assertEqual((wo.crew_gantt_start, wo.crew_gantt_stop),
                         (wo.date_start, wo.date_finished))

    def test_long_term_gantt_is_on_the_plan_dates(self):
        action = self.env["mrp.workcenter"].action_crew_plan_long_term()
        view = self.env.ref("mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_longterm_view")
        self.assertEqual(action["views"][0], (view.id, "gantt"))
        arch = self.WO.get_view(view.id, "gantt")["arch"]
        self.assertIn('date_start="crew_gantt_start"', arch)
        self.assertIn('date_stop="crew_gantt_stop"', arch)

    def test_drop_plans_the_unplanned(self):
        """Влачене в пистата = планиране: поръчката получава дати и МО-то
        минава в краткосрочния план."""
        wo = self._unplanned()
        wo.crew_drop(self.wc_pg.id, 1, date_start=self._utc(DAY, 13))
        self.assertEqual(wo.date_start, self._utc(DAY, 13))
        self.assertFalse(wo.crew_is_unplanned)
        self.assertTrue(wo.production_id.is_planned)
        short = self.wc_pg.action_crew_plan_gantt()["domain"]
        self.assertIn(wo, self.WO.search(short + [("id", "=", wo.id)]))

    def test_resize_writes_the_real_dates(self):
        wo = self._make_wo(self.wc_pg, self._utc(DAY, 8))
        wo.crew_gantt_stop = self._utc(DAY, 10)
        self.assertEqual(wo.date_finished, self._utc(DAY, 10))
