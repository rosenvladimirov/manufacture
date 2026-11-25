# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import datetime

from pytz import utc

from odoo import Command
from odoo.tests import new_test_user, tagged

from .common import CrewWorkorderCommon


@tagged("post_install", "-at_install", "crew_roster")
class TestButtonStart(CrewWorkorderCommon):
    """Тест 4 от TECH_DESIGN §6 (Р5, M3): стартиращият извън наряда не
    влиза в екипа, а времето му се отчита."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Денонощен календар: всеки ден е отделна смяна „00:00“ (M1), така
        # `date_start = now` на button_start попада в днешния наряд,
        # независимо от часа на пускане на теста.
        lines = [(dow, 0, 24, "morning", "Round the clock") for dow in range(7)]
        cls.cal_24 = cls._make_calendar("Round the clock", lines)
        cls.wc_24 = cls._make_workcenter("WC 24h", cls.cal_24)
        cls.user_starter = new_test_user(
            cls.env,
            login="crew_starter",
            email="crew_starter@crew-test.invalid",
            groups="mrp.group_mrp_user",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )
        cls.emp3.user_id = cls.user_starter

    def _today_local(self):
        return datetime.now(utc).astimezone(self.tz).date()

    def test_start_outside_roster(self):
        today = self._today_local()
        self._roster(self.wc_24, today, "00:00", self.emp1 | self.emp2)
        wo = self._make_wo(self.wc_24, self._utc(today, 0, 30))
        self.assertEqual(
            set(wo.employee_assigned_ids.ids), {self.emp1.id, self.emp2.id}
        )
        wo.with_user(self.user_starter).button_start()
        self.assertEqual(wo.state, "progress")
        self.assertEqual(wo.crew_date, today)
        self.assertEqual(
            set(wo.employee_assigned_ids.ids),
            {self.emp1.id, self.emp2.id},
            "стартиращият не влиза в екипа (Р5)",
        )
        self.assertIn(self.emp3, wo.employee_ids, "работещите остават")
        self.assertTrue(
            wo.time_ids.filtered(
                lambda t: t.employee_id == self.emp3 and not t.date_end
            ),
            "времето на стартиращия се отчита",
        )

    def test_start_without_roster_keeps_standard(self):
        """Р25: център без наряд за деня — стандартното поведение на EE.
        В 18 button_start на EE не добавя стартиращия в екипа (в 19 го
        добавя), затова екипът остава какъвто е."""
        today = self._today_local()
        wo = self._make_wo(self.wc_24, self._utc(today, 0, 30))
        before = wo.employee_assigned_ids
        wo.with_user(self.user_starter).button_start()
        self.assertEqual(wo.state, "progress")
        self.assertEqual(wo.employee_assigned_ids, before)
