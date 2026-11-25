# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.api import call_kw
from odoo.tests import tagged

from .common import MONDAY, CrewRosterCommon


@tagged("post_install", "-at_install", "crew_roster")
class TestCopyPrevious(CrewRosterCommon):
    """Тест 8 от TECH_DESIGN §6 (без „Преизчисли“): M8 „Копирай от вчера“."""

    def _roster(self, workcenter, day, key, employees):
        return self.Roster.create(
            {
                "workcenter_id": workcenter.id,
                "date": day,
                "shift_key": key,
                "employee_ids": [Command.set(employees.ids)],
            }
        )

    def _crew(self, workcenter, day, key):
        return self.Roster.search(
            [
                ("workcenter_id", "=", workcenter.id),
                ("date", "=", day),
                ("shift_key", "=", key),
            ]
        ).employee_ids

    def test_copy_skips_empty_days(self):
        """Сряда взима понеделник — последния попълнен ден, вторник е празен."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.emp1 | self.emp2)
        wednesday = MONDAY + timedelta(days=2)
        created = self.Roster.action_copy_previous(self.wc_pg, wednesday)
        self.assertEqual(len(created), 1)
        self.assertEqual(created.date, wednesday)
        self.assertEqual(created.employee_ids, self.emp1 | self.emp2)
        # Вторник остава празен — копирането е само за избрания ден.
        self.assertFalse(self._crew(self.wc_pg, MONDAY + timedelta(days=1), "08:00"))

    def test_copy_does_not_overwrite(self):
        self._roster(self.wc_pg, MONDAY, "08:00", self.emp1 | self.emp2)
        tuesday = MONDAY + timedelta(days=1)
        filled = self._roster(self.wc_pg, tuesday, "08:00", self.emp3)
        created = self.Roster.action_copy_previous(self.wc_pg, tuesday)
        self.assertFalse(created)
        self.assertEqual(filled.employee_ids, self.emp3)

    def test_copy_by_shift_key(self):
        """При две смени всяка копира от своя ключ."""
        self._roster(self.wc_2x12, MONDAY, "08:00", self.emp1)
        self._roster(self.wc_2x12, MONDAY, "20:00", self.emp2 | self.emp3)
        tuesday = MONDAY + timedelta(days=1)
        created = self.Roster.action_copy_previous(self.wc_2x12, tuesday)
        self.assertEqual(len(created), 2)
        self.assertEqual(self._crew(self.wc_2x12, tuesday, "08:00"), self.emp1)
        self.assertEqual(
            self._crew(self.wc_2x12, tuesday, "20:00"), self.emp2 | self.emp3
        )

    def test_copy_fills_only_missing_shift(self):
        """Попълнената смяна се пази, празната се допълва."""
        self._roster(self.wc_2x12, MONDAY, "08:00", self.emp1)
        self._roster(self.wc_2x12, MONDAY, "20:00", self.emp2)
        tuesday = MONDAY + timedelta(days=1)
        self._roster(self.wc_2x12, tuesday, "08:00", self.emp3)
        created = self.Roster.action_copy_previous(self.wc_2x12, tuesday)
        self.assertEqual(created.shift_key, "20:00")
        self.assertEqual(self._crew(self.wc_2x12, tuesday, "08:00"), self.emp3)
        self.assertEqual(self._crew(self.wc_2x12, tuesday, "20:00"), self.emp2)

    def test_copy_ignores_other_workcenter_and_later_days(self):
        self._roster(self.wc_2x12, MONDAY, "08:00", self.emp1)
        self._roster(self.wc_pg, MONDAY + timedelta(days=3), "08:00", self.emp2)
        created = self.Roster.action_copy_previous(
            self.wc_pg, MONDAY + timedelta(days=1)
        )
        self.assertFalse(created, "по-късен ден и чужд център не са източник")

    def test_button_uses_context(self):
        self._roster(self.wc_pg, MONDAY, "08:00", self.emp1)
        tuesday = MONDAY + timedelta(days=1)
        with self.assertRaises(UserError):
            self.Roster.action_copy_from_yesterday()
        action = self.Roster.with_context(
            crew_workcenter_id=self.wc_pg.id,
            crew_date=fields.Date.to_string(tuesday),
        ).action_copy_from_yesterday()
        self.assertEqual(action["tag"], "soft_reload")
        self.assertEqual(self._crew(self.wc_pg, tuesday, "08:00"), self.emp1)
        # Втори натиск: нищо за копиране → известие, без презапис.
        action = self.Roster.with_context(
            crew_workcenter_id=self.wc_pg.id,
            crew_date=fields.Date.to_string(tuesday),
        ).action_copy_from_yesterday()
        self.assertEqual(action["tag"], "display_notification")

    def test_button_via_call_kw(self):
        """19.0.1.6.1 (дефект от живия тест 09.10): бутонът в хедъра на
        списъка минава през `call_button` → `call_kw`, който подава ids
        като първи аргумент — празни (нищо избрано) и избрани наряди."""
        roster = self._roster(self.wc_pg, MONDAY, "08:00", self.emp1)
        tuesday = MONDAY + timedelta(days=1)
        context = {
            "crew_workcenter_id": self.wc_pg.id,
            "crew_date": fields.Date.to_string(tuesday),
        }
        action = call_kw(
            self.Roster, "action_copy_from_yesterday", [[]], {"context": context}
        )
        self.assertEqual(action["tag"], "soft_reload")
        self.assertEqual(self._crew(self.wc_pg, tuesday, "08:00"), self.emp1)
        # С избран наряд: избраните не се ползват — нищо за копиране.
        action = call_kw(
            self.Roster, "action_copy_from_yesterday", [roster.ids], {"context": context}
        )
        self.assertEqual(action["tag"], "display_notification")
