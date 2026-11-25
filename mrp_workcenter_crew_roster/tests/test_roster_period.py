# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Удобствата на наряда на монтажа в Crew Roster (№146 на Теолино, ADR-0071).

Любо, 12.10: „пак си искам удобствата от стария и освен това в новия не е
свързан към записи на WC, и хора“:

* „До“ разгръща реда в един наряд на работен ден със същата смяна —
  почивните дни, празниците и вече попълнените дни се прескачат;
* изборът на хора — позволените в центъра;
* нарядите се виждат от картата на центъра и на служителя.
"""
from datetime import datetime, timedelta

from odoo import Command
from odoo.exceptions import UserError

from .common import DAYS, MONDAY, CrewRosterCommon


class TestRosterPeriod(CrewRosterCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        lines = []
        for dow in range(5):
            lines += [
                (dow, 8, 12, "morning", "%s Morning" % DAYS[dow]),
                (dow, 12, 13, "lunch", "%s Lunch" % DAYS[dow]),
                (dow, 13, 17, "afternoon", "%s Afternoon" % DAYS[dow]),
            ]
        cls.cal_week = cls._make_calendar("Montage Mon-Fri", lines)
        cls.wc_mont = cls._make_workcenter("WC Montage", cls.cal_week)
        cls.wc_mont.employee_ids = cls.emp1 | cls.emp2

    def _roster(self, day, **vals):
        return self.Roster.create(
            dict(
                {
                    "workcenter_id": self.wc_mont.id,
                    "date": day,
                    "shift_key": "08:00",
                    "employee_ids": [Command.set((self.emp1 | self.emp2).ids)],
                },
                **vals,
            )
        )

    def _days(self):
        return sorted(
            self.Roster.search([("workcenter_id", "=", self.wc_mont.id)]).mapped("date")
        )

    def test_until_makes_one_roster_per_working_day(self):
        # понеделник → понеделник след седмица: съботата и неделята отпадат
        self._roster(MONDAY, date_to=MONDAY + timedelta(days=7))
        self.assertEqual(
            self._days(),
            [MONDAY + timedelta(days=d) for d in (0, 1, 2, 3, 4, 7)],
        )
        rosters = self.Roster.search([("workcenter_id", "=", self.wc_mont.id)])
        self.assertEqual(set(rosters.mapped("shift_key")), {"08:00"})
        for roster in rosters:
            self.assertEqual(roster.employee_ids, self.emp1 | self.emp2)
        self.assertFalse(any(rosters.mapped("date_to")), "„До“ не остава в базата")

    def test_holiday_and_filled_day_are_skipped(self):
        wednesday = MONDAY + timedelta(days=2)
        self.env["resource.calendar.leaves"].create(
            {
                "name": "Holiday",
                "calendar_id": self.cal_week.id,
                "date_from": datetime.combine(wednesday, datetime.min.time()),
                "date_to": datetime.combine(wednesday, datetime.max.time()),
            }
        )
        thursday = self._roster(
            MONDAY + timedelta(days=3), employee_ids=[Command.set(self.emp3.ids)]
        )
        self._roster(MONDAY, date_to=MONDAY + timedelta(days=4))
        self.assertEqual(
            self._days(), [MONDAY + timedelta(days=d) for d in (0, 1, 3, 4)]
        )
        self.assertEqual(thursday.employee_ids, self.emp3, "попълненият ден не се пипа")

    def test_until_on_an_existing_roster(self):
        roster = self._roster(MONDAY)
        roster.write({"date_to": MONDAY + timedelta(days=2)})
        self.assertEqual(self._days(), [MONDAY + timedelta(days=d) for d in (0, 1, 2)])

    def test_period_longer_than_three_months_is_refused(self):
        with self.assertRaises(UserError):
            self._roster(MONDAY, date_to=MONDAY + timedelta(days=93))

    def test_crew_choice_is_the_people_of_the_center(self):
        roster = self._roster(MONDAY)
        self.assertEqual(roster.allowed_employee_ids, self.emp1 | self.emp2)

    def test_rosters_from_the_center_and_the_employee(self):
        self._roster(MONDAY, date_to=MONDAY + timedelta(days=1))
        self.assertEqual(self.wc_mont.crew_roster_count, 2)
        self.assertEqual(self.emp1.crew_roster_count, 2)
        self.assertEqual(self.emp3.crew_roster_count, 0)
        action = self.wc_mont.action_crew_rosters()
        self.assertEqual(action["res_model"], "mrp.workcenter.roster")
        self.assertEqual(action["context"]["crew_workcenter_id"], self.wc_mont.id)
        action = self.emp1.action_crew_rosters()
        self.assertEqual(
            self.Roster.search(action["domain"]),
            self.Roster.search([("workcenter_id", "=", self.wc_mont.id)]),
        )

    # Етикетът на центъра в Ганта (т. 4; Клаудио 12.10) ─────────────────────

    def _label(self, day_from, days):
        # Периодът на Ганта е в UTC; София е +3 през октомври.
        start = datetime.combine(day_from, datetime.min.time()) - timedelta(hours=3)
        return self.wc_mont._crew_names_label(start, start + timedelta(days=days)).get(
            self.wc_mont.id
        )

    def test_label_is_the_crew_when_it_is_the_same_all_period(self):
        self._roster(MONDAY, date_to=MONDAY + timedelta(days=4))
        self.assertEqual(self._label(MONDAY, 1), "Crew One, Crew Two")
        self.assertEqual(self._label(MONDAY, 7), "Crew One, Crew Two")

    def test_label_says_different_crews_when_it_changes(self):
        self._roster(MONDAY)
        self._roster(MONDAY + timedelta(days=1), employee_ids=[Command.set(self.emp3.ids)])
        self.assertEqual(self._label(MONDAY, 1), "Crew One, Crew Two", "денят — неговата бригада")
        self.assertEqual(self._label(MONDAY + timedelta(days=1), 1), "Crew Three")
        self.assertEqual(self._label(MONDAY, 7), "different crews")

    def test_no_roster_no_label(self):
        self._roster(MONDAY + timedelta(days=7))
        self.assertIsNone(self._label(MONDAY, 7), "нарядът след периода не влиза")
