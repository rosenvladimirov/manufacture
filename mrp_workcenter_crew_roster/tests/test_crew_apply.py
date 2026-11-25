# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import timedelta

from lxml import etree

from odoo import Command
from odoo.tests import new_test_user, tagged

from .common import MONDAY, CrewWorkorderCommon

TUESDAY = MONDAY + timedelta(days=1)


@tagged("post_install", "-at_install", "crew_roster")
class TestCrewApply(CrewWorkorderCommon):
    """Тест 3 от TECH_DESIGN §6: прилагане на наряда към екипа (M2, Р25)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.crew12 = cls.emp1 | cls.emp2

    def assertCrew(self, workorder, employees, msg=None):
        self.assertEqual(
            set(workorder.employee_assigned_ids.ids), set(employees.ids), msg
        )

    # --- Т3: ден и смяна на поръчката ---------------------------------

    def test_crew_slot(self):
        """Блокът, който съдържа началото; празнина → следващият блок;
        нощната смяна е на деня на началото си."""
        cases = [
            (self.wc_pg, MONDAY, 9, MONDAY, "08:00"),
            (self.wc_pg, MONDAY, 12, MONDAY, "08:00"),  # в обедната пауза
            (self.wc_pg, MONDAY, 7, MONDAY, "08:00"),  # преди смяната
            (self.wc_pg, MONDAY, 18, TUESDAY, "08:00"),  # след смяната
            (self.wc_2x12, MONDAY, 21, MONDAY, "20:00"),
            (self.wc_2x12, TUESDAY, 3, MONDAY, "20:00"),  # нощта след полунощ
            (self.wc_2x12, TUESDAY, 8, TUESDAY, "08:00"),
        ]
        for wc, day, hour, crew_date, key in cases:
            wo = self._make_wo(wc, self._utc(day, hour))
            self.assertEqual(
                (wo.crew_date, wo.crew_shift_key), (crew_date, key), (wc.name, day, hour)
            )

    # --- M2: кога се прилага --------------------------------------------

    def test_apply_on_create(self):
        roster = self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 9), crew=self.emp3)
        self.assertCrew(wo, self.crew12, "нарядът замества екипа от create")
        self.assertEqual(wo.roster_id, roster)
        self.assertAlmostEqual(wo.minutes_per_person, 30.0)

    def test_apply_on_workcenter_change(self):
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        self._roster(self.wc_2x12, MONDAY, "08:00", self.emp3)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 9))
        self.assertCrew(wo, self.crew12)
        wo.workcenter_id = self.wc_2x12
        self.assertEqual(wo.crew_shift_key, "08:00")
        self.assertCrew(wo, self.emp3)

    def test_apply_on_date_change(self):
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        self._roster(self.wc_pg, TUESDAY, "08:00", self.emp3)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 9))
        self.assertCrew(wo, self.crew12)
        wo.write(
            {
                "date_start": self._utc(TUESDAY, 9),
                "date_finished": self._utc(TUESDAY, 10),
            }
        )
        self.assertEqual(wo.crew_date, TUESDAY)
        self.assertCrew(wo, self.emp3)

    def test_apply_on_leave_change(self):
        """В 19 _plan_workorder пише leave_id, а датите идват от него."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        self._roster(self.wc_pg, TUESDAY, "08:00", self.emp3)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 9))
        leave = self.env["resource.calendar.leaves"].create(
            {
                "name": "Crew slot",
                "calendar_id": self.cal_pg.id,
                "resource_id": self.wc_pg.resource_id.id,
                "date_from": self._utc(TUESDAY, 10),
                "date_to": self._utc(TUESDAY, 11),
                "time_type": "other",
            }
        )
        wo.leave_id = leave
        self.assertEqual(wo.date_start, self._utc(TUESDAY, 10))
        self.assertCrew(wo, self.emp3)

    def test_roster_for_day_but_not_for_shift_empties(self):
        """Центърът има наряд за деня, но не и за смяната → празен екип."""
        self._roster(self.wc_2x12, MONDAY, "08:00", self.emp3)
        wo = self._make_wo(self.wc_2x12, self._utc(MONDAY, 21), crew=self.emp1)
        self.assertEqual(wo.crew_shift_key, "20:00")
        self.assertFalse(wo.employee_assigned_ids)
        self.assertFalse(wo.roster_id)
        self.assertEqual(wo.minutes_per_person, 0.0)

    def test_r25_center_without_roster_untouched(self):
        """Р25: център без нито един наряд за деня — екипът не се пипа."""
        # Друг център и друг ден имат наряди — не влияят.
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        self._roster(self.wc_2x12, TUESDAY, "08:00", self.emp1)
        wo = self._make_wo(self.wc_2x12, self._utc(MONDAY, 9), crew=self.emp3)
        self.assertCrew(wo, self.emp3)
        wo.write(
            {
                "date_start": self._utc(MONDAY, 10),
                "date_finished": self._utc(MONDAY, 11),
            }
        )
        self.assertCrew(wo, self.emp3)

    # --- M2: промяна на наряда ---------------------------------------------

    def test_roster_changes_reach_workorders(self):
        roster = self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 9))
        roster.employee_ids = [Command.set(self.emp3.ids)]
        self.assertCrew(wo, self.emp3, "промяна на хората в наряда")

        # Нов наряд за ден без наряд замества ръчния екип.
        wo_tue = self._make_wo(self.wc_pg, self._utc(TUESDAY, 9), crew=self.emp2)
        self.assertCrew(wo_tue, self.emp2)
        roster_tue = self._roster(self.wc_pg, TUESDAY, "08:00", self.emp1)
        self.assertCrew(wo_tue, self.emp1, "нов наряд")

        # Преместен наряд: старият ден губи наряда (Р25 — не се пипа),
        # новият ден го получава.
        wo_wed = self._make_wo(
            self.wc_pg, self._utc(TUESDAY + timedelta(days=1), 9), crew=self.emp3
        )
        roster_tue.date = TUESDAY + timedelta(days=1)
        self.assertCrew(wo_wed, self.emp1, "наряд, преместен в друг ден")
        self.assertCrew(wo_tue, self.emp1, "старият ден е без наряд — Р25")

    def test_roster_unlink(self):
        """Изтрит наряд: ако денят остава под наряд — празен екип; ако
        центърът вече няма наряд за деня — екипът не се пипа (Р25)."""
        day_roster = self._roster(self.wc_2x12, MONDAY, "08:00", self.emp1)
        night_roster = self._roster(self.wc_2x12, MONDAY, "20:00", self.emp2)
        wo_day = self._make_wo(self.wc_2x12, self._utc(MONDAY, 9))
        wo_night = self._make_wo(self.wc_2x12, self._utc(MONDAY, 21))
        self.assertCrew(wo_day, self.emp1)
        self.assertCrew(wo_night, self.emp2)
        night_roster.unlink()
        self.assertFalse(wo_night.employee_assigned_ids)
        day_roster.unlink()
        self.assertCrew(wo_day, self.emp1)

    def test_mrp_user_roster_reaches_workorders(self):
        """MRP User без HR група: нарядът му стига до поръчките (права)."""
        user = new_test_user(
            self.env,
            login="crew_apply_user",
            email="crew_apply_user@crew-test.invalid",
            groups="mrp.group_mrp_user",
            company_id=self.company.id,
            company_ids=[Command.set(self.company.ids)],
        )
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 9), crew=self.emp3)
        roster = self.Roster.with_user(user).create(
            {
                "workcenter_id": self.wc_pg.id,
                "date": MONDAY,
                "shift_key": "08:00",
                "employee_ids": [Command.set(self.crew12.ids)],
            }
        )
        self.assertCrew(wo, self.crew12)
        roster.with_user(user).write({"employee_ids": [Command.unlink(self.emp2.id)]})
        self.assertCrew(wo, self.emp1)

    # --- приключени, рекурсия ---------------------------------------------------

    def test_done_not_touched(self):
        roster = self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo_done = self._make_wo(self.wc_pg, self._utc(MONDAY, 9))
        wo_cancel = self._make_wo(self.wc_pg, self._utc(MONDAY, 10))
        wo_open = self._make_wo(self.wc_pg, self._utc(MONDAY, 11))
        wo_done.state = "done"
        wo_cancel.state = "cancel"
        roster.employee_ids = [Command.set(self.emp3.ids)]
        self.assertCrew(wo_open, self.emp3)
        self.assertCrew(wo_done, self.crew12, "приключената не се пипа")
        self.assertCrew(wo_cancel, self.crew12, "отказаната не се пипа")
        # И при запис на датите на приключената/отказаната.
        for wo, hour in ((wo_done, 9), (wo_cancel, 10)):
            wo.write(
                {
                    "date_start": self._utc(MONDAY, hour, 30),
                    "date_finished": self._utc(MONDAY, hour + 1, 30),
                }
            )
            self.assertCrew(wo, self.crew12, "запис на датите на %s" % wo.state)
        # Друг календар на центъра: отворената сменя смяната си,
        # приключената пази деня и смяната.
        lines = [(dow, 7, 15, "morning", "Early") for dow in range(7)]
        self.wc_pg.resource_calendar_id = self._make_calendar("Early shift", lines)
        self.assertEqual(wo_open.crew_shift_key, "07:00")
        self.assertEqual(
            (wo_done.crew_date, wo_done.crew_shift_key), (MONDAY, "08:00")
        )
        # Нов наряд за новата смяна стига до отворената, не до приключената.
        self._roster(self.wc_pg, MONDAY, "07:00", self.emp1)
        self.assertCrew(wo_open, self.emp1)
        self.assertCrew(wo_done, self.crew12)
        # force=True прилага и върху приключените (нарядът на смяната ѝ).
        wo_done._crew_apply(force=True)
        self.assertCrew(wo_done, self.emp3)

    def test_recursion_guard(self):
        """Собственият запис на екипа е под гарда: запис под него не
        прилага наряда отново (на него стъпва и двигателят в стъпка 5)."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        self._roster(self.wc_2x12, MONDAY, "08:00", self.emp3)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 9))
        wo.with_context(crew_roster_applying=True).write(
            {"workcenter_id": self.wc_2x12.id}
        )
        self.assertCrew(wo, self.crew12, "под гарда нарядът не се прилага")
        wo.write(
            {
                "date_start": self._utc(MONDAY, 10),
                "date_finished": self._utc(MONDAY, 11),
            }
        )
        self.assertCrew(wo, self.emp3)

    # --- инсталация, изгледи --------------------------------------------------

    def test_init_fills_only_open(self):
        """При инсталация се попълват само незавършените поръчки."""
        crew = self.emp1 | self.emp2
        wo_open = self._make_wo(self.wc_pg, self._utc(MONDAY, 9), crew=crew)
        wo_done = self._make_wo(self.wc_pg, self._utc(MONDAY, 10), crew=crew)
        wo_done.state = "done"
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE mrp_workorder SET crew_date = NULL, crew_shift_key = NULL, "
            "minutes_per_person = NULL WHERE id IN %s",
            [(wo_open.id, wo_done.id)],
        )
        self.env.invalidate_all()
        self.WO._crew_init_open_workorders()
        self.env.invalidate_all()
        self.assertEqual((wo_open.crew_date, wo_open.crew_shift_key), (MONDAY, "08:00"))
        self.assertAlmostEqual(wo_open.minutes_per_person, 30.0)
        self.assertFalse(wo_done.crew_date)
        self.assertFalse(wo_done.crew_shift_key)
        self.env.cr.execute(
            "SELECT minutes_per_person FROM mrp_workorder WHERE id = %s", [wo_done.id]
        )
        self.assertIsNone(self.env.cr.fetchone()[0])

    def test_crew_readonly_in_views(self):
        """Р24: екипът е само за четене във формата и в списъка."""
        for xmlid, view_type in (
            ("mrp.mrp_production_workorder_form_view_inherit", "form"),
            ("mrp.mrp_production_workorder_tree_editable_view", "list"),
        ):
            arch = self.WO.get_view(self.env.ref(xmlid).id, view_type)["arch"]
            nodes = etree.fromstring(arch).xpath("//field[@name='employee_assigned_ids']")
            self.assertTrue(nodes, xmlid)
            for node in nodes:
                self.assertIn(node.get("readonly"), ("1", "True", "true"), xmlid)
