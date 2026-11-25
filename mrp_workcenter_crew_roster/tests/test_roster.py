# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import datetime, timedelta

from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, new_test_user, tagged
from odoo.tools import mute_logger

from .common import MONDAY, CrewRosterCommon


@tagged("post_install", "-at_install", "crew_roster")
class TestRoster(CrewRosterCommon):
    """Тест 1 от TECH_DESIGN §6: нарядът, ограниченията и правата (Р24)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_mrp = new_test_user(
            cls.env,
            login="crew_mrp_user",
            email="crew_mrp_user@crew-test.invalid",
            groups="mrp.group_mrp_user",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )
        cls.user_manager = new_test_user(
            cls.env,
            login="crew_mrp_manager",
            email="crew_mrp_manager@crew-test.invalid",
            groups="mrp.group_mrp_manager",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )

    def _roster_vals(self, **overrides):
        vals = {
            "workcenter_id": self.wc_pg.id,
            "date": MONDAY,
            "shift_key": "08:00",
            "employee_ids": [Command.set((self.emp1 | self.emp2).ids)],
        }
        vals.update(overrides)
        return vals

    def test_create_and_computed(self):
        roster = self.Roster.create(self._roster_vals())
        self.assertEqual(roster.crew_size, 2)
        self.assertAlmostEqual(roster.shift_hours, 8.0)
        self.assertFalse(roster.shift_missing)
        self.assertEqual(roster.company_id, self.wc_pg.company_id)
        # 08:00 в София през октомври (EEST, UTC+3) е 05:00 UTC.
        self.assertEqual(roster.shift_start, datetime(2026, 10, 5, 5, 0))
        self.assertEqual(roster.shift_stop, datetime(2026, 10, 5, 14, 0))
        self.assertIn("08:00–17:00", roster.display_name)
        self.assertIn(self.wc_pg.name, roster.display_name)

    def test_unique_shift(self):
        """Един наряд на (център, ден, смяна) — models.Constraint."""
        self.Roster.create(self._roster_vals())
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.Roster.create(self._roster_vals(employee_ids=[Command.set(self.emp3.ids)]))
            self.env.flush_all()

    def test_same_shift_other_day_or_center_allowed(self):
        self.Roster.create(self._roster_vals())
        self.Roster.create(self._roster_vals(date=MONDAY + timedelta(days=1)))
        self.Roster.create(
            self._roster_vals(workcenter_id=self.wc_2x12.id, shift_key="08:00")
        )
        self.Roster.create(
            self._roster_vals(workcenter_id=self.wc_2x12.id, shift_key="20:00")
        )
        self.assertEqual(
            self.Roster.search_count([("date", ">=", MONDAY)]), 4
        )

    def test_empty_crew_raises(self):
        with self.assertRaises(ValidationError):
            self.Roster.create(self._roster_vals(employee_ids=[]))
        roster = self.Roster.create(self._roster_vals())
        with self.assertRaises(ValidationError):
            roster.employee_ids = [Command.clear()]

    def test_shift_key_must_be_block_start(self):
        """Начало, което не е начало на блок → грешка (13:00 е след обяда)."""
        with self.assertRaises(ValidationError):
            self.Roster.create(self._roster_vals(shift_key="13:00"))
        # Нощната опашка 00:00 в календара 2×12 не е смяна.
        with self.assertRaises(ValidationError):
            self.Roster.create(
                self._roster_vals(workcenter_id=self.wc_2x12.id, shift_key="00:00")
            )
        # Ден без смяна (календар само за понеделник).
        cal = self._make_calendar("Monday only", [(0, 8, 17, "morning", "Mon")])
        wc = self._make_workcenter("WC monday", cal)
        with self.assertRaises(ValidationError):
            self.Roster.create(
                self._roster_vals(workcenter_id=wc.id, date=MONDAY + timedelta(days=1))
            )

    def test_shift_missing_after_calendar_change(self):
        roster = self.Roster.create(self._roster_vals())
        self.cal_pg.attendance_ids.filtered(
            lambda a: a.dayofweek == "0" and a.day_period == "morning"
        ).hour_from = 7
        self.assertTrue(roster.shift_missing)
        self.assertFalse(roster.shift_start)

    def test_default_workcenter_from_context(self):
        """`crew_workcenter_id` в контекста дава центъра; onchange попълва смяната."""
        model = self.Roster.with_context(crew_workcenter_id=self.wc_pg.id)
        with Form(model) as form:
            self.assertEqual(form.workcenter_id, self.wc_pg)
            form.date = MONDAY
            self.assertEqual(form.shift_key, "08:00", "единствената смяна се избира сама")
            form.employee_ids.add(self.emp1)
        roster = form.record
        self.assertEqual(roster.workcenter_id, self.wc_pg)
        # При две смени onchange не избира сам.
        model = self.Roster.with_context(crew_workcenter_id=self.wc_2x12.id)
        form = Form(model)
        form.date = MONDAY
        self.assertFalse(form.shift_key)

    def test_rights_user_creates_writes_not_unlinks(self):
        """Р24: MRP User създава и пише, но не трие; мениджърът трие."""
        roster = self.Roster.with_user(self.user_mrp).create(self._roster_vals())
        roster.with_user(self.user_mrp).write(
            {"employee_ids": [Command.link(self.emp3.id)]}
        )
        self.assertEqual(roster.crew_size, 3)
        with self.assertRaises(AccessError):
            roster.with_user(self.user_mrp).unlink()
        self.assertTrue(roster.exists())
        roster.with_user(self.user_manager).unlink()
        self.assertFalse(roster.exists())

    def test_multi_company_rule(self):
        """Нарядът на друга фирма не се вижда от потребител без тази фирма."""
        company_b = self.env["res.company"].create({"name": "Crew Company B"})
        cal_b = self._make_calendar(
            "B calendar", [(0, 8, 17, "morning", "Mon")]
        )
        cal_b.company_id = company_b
        wc_b = self._make_workcenter("WC B", cal_b, company=company_b)
        emp_b = self.env["hr.employee"].create(
            {"name": "Crew B", "company_id": company_b.id}
        )
        roster_b = self.Roster.create(
            {
                "workcenter_id": wc_b.id,
                "date": MONDAY,
                "shift_key": "08:00",
                "employee_ids": [Command.set(emp_b.ids)],
            }
        )
        roster_a = self.Roster.create(self._roster_vals())
        self.assertEqual(roster_b.company_id, company_b)
        visible = self.Roster.with_user(self.user_mrp).search([])
        self.assertIn(roster_a, visible)
        self.assertNotIn(roster_b, visible)
        with self.assertRaises(AccessError):
            roster_b.with_user(self.user_mrp).read(["date"])

    def test_check_company_employee(self):
        """`_check_company_auto`: служител на чужда фирма не влиза в наряда."""
        company_b = self.env["res.company"].create({"name": "Crew Company C"})
        emp_b = self.env["hr.employee"].create(
            {"name": "Foreign", "company_id": company_b.id}
        )
        with self.assertRaises(UserError):
            self.Roster.create(
                self._roster_vals(employee_ids=[Command.set(emp_b.ids)])
            )
