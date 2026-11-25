# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import datetime, timedelta

from pytz import utc

from odoo import fields
from odoo.tests import tagged

from .common import MONDAY, CrewWorkorderCommon

SATURDAY = MONDAY + timedelta(days=5)


@tagged("post_install", "-at_install", "crew_roster")
class TestLoad(CrewWorkorderCommon):
    """Тест 9 от TECH_DESIGN §6: натоварване и капацитет в часове (M11,
    Р27) и „Закъснява“ по SPEC §4."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ICP.set_param("mrp_workcenter_crew_roster.default_capacity_hours", "8")
        # Служител на календар пон–пет (И2): капацитетът му НЕ идва оттам.
        lines = [(dow, 8, 17, "morning", "Weekday") for dow in range(5)]
        cls.cal_weekdays = cls._make_calendar("Weekdays only", lines)
        cls.emp_weekdays = cls.env["hr.employee"].create(
            {"name": "Crew Weekdays", "resource_calendar_id": cls.cal_weekdays.id}
        )
        cls.wc_nocal = cls.env["mrp.workcenter"].create(
            {"name": "WC without calendar", "resource_calendar_id": False}
        )
        # Бъдещ понеделник: лентата в Ганта не брои миналото.
        today = datetime.now(utc).astimezone(cls.tz).date()
        cls.future_monday = today + timedelta(days=7 - today.weekday())

    def _capacity(self, employee, day):
        _load, capacity = self.WO._crew_load_and_capacity(employee, [day])
        return capacity.get((employee.id, day), 0.0)

    # --- лентата в Ганта: часове --------------------------------------

    def test_progress_bar_in_hours(self):
        """480 минути на човек → 8,0 часа; таванът е часовете на смяната."""
        self.env.user.tz = "Europe/Sofia"
        day = self.future_monday
        self._roster(self.wc_pg, day, "08:00", self.emp1)
        wo = self._make_wo(self.wc_pg, self._utc(day, 8), minutes=480.0)
        self.assertEqual(wo.employee_assigned_ids, self.emp1)
        start = self._utc(day, 0)
        stop = self._utc(day + timedelta(days=1), 0)
        bar = self.WO._gantt_progress_bar(
            "employee_assigned_ids", [self.emp1.id, self.emp2.id], start, stop
        )
        self.assertAlmostEqual(bar[self.emp1.id]["value"], 8.0)
        self.assertAlmostEqual(bar[self.emp1.id]["max_value"], 8.0)
        self.assertEqual(bar[self.emp2.id]["value"], 0.0)
        self.assertIn("warning", bar)
        # Стандартното поле си остава на EE.
        bar_wc = self.WO._gantt_progress_bar("workcenter_id", [self.wc_pg.id], start, stop)
        self.assertIn(self.wc_pg.id, bar_wc)

    # --- капацитет ------------------------------------------------------

    def test_capacity_from_roster_shift(self):
        self._roster(self.wc_pg, MONDAY, "08:00", self.emp1)
        wo_a = self._make_wo(self.wc_pg, self._utc(MONDAY, 8), minutes=480.0)
        self.assertAlmostEqual(self._capacity(self.emp1, MONDAY), 8.0)
        self.assertFalse(wo_a.is_overloaded)
        wo_b = self._make_wo(
            self.wc_pg, self._utc(MONDAY, 15), minutes=60.0, overlap=True
        )
        # Претоварването е изчисляемо без съхранение и зависи от ДРУГИТЕ
        # поръчки — в една транзакция кешът се изчиства изрично.
        self.env.invalidate_all()
        self.assertTrue(wo_a.is_overloaded)
        self.assertTrue(wo_b.is_overloaded)
        self.assertIn("Crew One", wo_b.overload_message)
        self.assertIn("9.00", wo_b.overload_message)

    def test_capacity_sums_shifts_of_the_day(self):
        """Две смени в един ден (на два центъра): 8 ч + 12 ч нощна."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.emp1)
        self._roster(self.wc_2x12, MONDAY, "20:00", self.emp1)
        self.assertAlmostEqual(self._capacity(self.emp1, MONDAY), 20.0)
        wo = self._make_wo(self.wc_2x12, self._utc(MONDAY, 20), minutes=1140.0)
        self.assertFalse(wo.is_overloaded, wo.overload_message)

    def test_capacity_from_center_calendar_without_roster(self):
        """Без наряд (Р25, ръчен екип): смяната на поръчката от календара на
        центъра — дневната на 2×12 е 08–20 с обяд, т.е. 11 ч."""
        wo = self._make_wo(
            self.wc_2x12, self._utc(MONDAY, 9), minutes=600.0, crew=self.emp3
        )
        self.assertAlmostEqual(self._capacity(self.emp3, MONDAY), 11.0)
        self.assertFalse(wo.is_overloaded)
        wo.duration_expected = 720.0
        self.assertTrue(wo.is_overloaded)

    def test_capacity_parameter_without_calendar(self):
        self.ICP.set_param("mrp_workcenter_crew_roster.default_capacity_hours", "5")
        wo = self._make_wo(
            self.wc_nocal, self._utc(MONDAY, 9), minutes=240.0, crew=self.emp3
        )
        self.assertAlmostEqual(self._capacity(self.emp3, wo.crew_date), 5.0)
        self.assertFalse(wo.is_overloaded)
        wo.duration_expected = 360.0
        self.assertTrue(wo.is_overloaded)

    def test_saturday_with_roster_not_overloaded(self):
        """И2: служител на календар пон–пет, наряд в събота — не е претоварен;
        календарът на служителя не се ползва (Р27)."""
        self._roster(self.wc_pg, SATURDAY, "08:00", self.emp_weekdays)
        wo = self._make_wo(self.wc_pg, self._utc(SATURDAY, 8), minutes=420.0)
        self.assertEqual(wo.employee_assigned_ids, self.emp_weekdays)
        self.assertAlmostEqual(self._capacity(self.emp_weekdays, SATURDAY), 8.0)
        self.assertFalse(wo.is_overloaded, wo.overload_message)

    def test_done_not_counted(self):
        self._roster(self.wc_pg, MONDAY, "08:00", self.emp1)
        wo_done = self._make_wo(self.wc_pg, self._utc(MONDAY, 8), minutes=480.0)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 9), minutes=60.0, overlap=True)
        self.assertTrue(wo.is_overloaded)
        wo_done.state = "done"
        self.env.invalidate_all()
        self.assertFalse(wo.is_overloaded)
        self.assertFalse(wo_done.is_overloaded)

    # --- „Закъснява“ ------------------------------------------------------

    def test_is_late(self):
        now = fields.Datetime.now()
        future = now.replace(microsecond=0) + timedelta(days=7)
        mo_future = self._make_mo(deadline=future)
        mo_past = self._make_mo(deadline=now - timedelta(days=1))
        wo_on_time = self._make_wo(
            self.wc_pg, future - timedelta(hours=3), minutes=60.0, mo=mo_future
        )
        wo_after = self._make_wo(
            self.wc_pg, future - timedelta(minutes=30), minutes=60.0, mo=mo_future
        )
        wo_past = self._make_wo(
            self.wc_pg, future, minutes=60.0, mo=mo_past, overlap=True
        )
        wo_done = self._make_wo(self.wc_pg, future, minutes=60.0, mo=self._make_mo(
            deadline=now - timedelta(days=1)
        ), overlap=True)
        wo_done.state = "done"
        wo_no_deadline = self._make_wo(self.wc_pg, future, minutes=60.0, overlap=True)
        self.assertEqual(wo_after.deadline, future)
        expected = {
            wo_on_time: False,
            wo_after: True,
            wo_past: True,
            wo_done: False,
            wo_no_deadline: False,
        }
        for wo, late in expected.items():
            self.assertEqual(wo.is_late, late, wo.display_name)
        ids = [wo.id for wo in expected]
        late = self.WO.search([("id", "in", ids), ("is_late", "=", True)])
        self.assertEqual(late, wo_after | wo_past)
        not_late = self.WO.search([("id", "in", ids), ("is_late", "=", False)])
        self.assertEqual(not_late, wo_on_time | wo_done | wo_no_deadline)
        self.assertEqual(
            self.WO.search([("id", "in", ids), ("is_late", "!=", True)]), not_late
        )
