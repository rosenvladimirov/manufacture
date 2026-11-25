# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Делът на бригадата в продължителността (№145 на Теолино, ADR-0070).

* прозорец = d × (1 − дял) + d × дял ÷ бригадата на центъра за деня;
* без бригада — пълното време и „No crew“;
* делът е на операцията, поръчката го носи;
* „Plan“ дели на бригадата на всеки кандидат (алтернативите);
* влачене/разтягане в Ганта не превръща прозореца в duration_expected;
* сменен БРОЙ хора ⇒ нов край и избутване на следващите в пистата;
* себестойността при дял > 0 — по сбора от time_ids (вариант б);
* дял 0 — както досега.
"""
from datetime import timedelta
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from ..models.mrp_workcenter_person_minutes import CREW_SHARE, crew_window_factor
from .common import MONDAY, CrewWorkorderCommon


@tagged("post_install", "-at_install", "crew_roster")
class TestPersonMinutes(CrewWorkorderCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wc_pm = cls._make_workcenter("WC Montage PM", cls.cal_pg)

    def _crew(self, employees, workcenter=None):
        return self._roster(workcenter or self.wc_pm, MONDAY, "08:00", employees)

    def _slot(self, start, minutes, share, workcenter=None):
        workcenter = (workcenter or self.wc_pm).with_context(**{CREW_SHARE: share})
        return workcenter._get_first_available_slot(start, minutes)

    def _wo(self, start, minutes, share, workcenter=None):
        return self._make_wo(workcenter or self.wc_pm, start, minutes=minutes, crew_share=share)

    def test_factor(self):
        self.assertEqual(crew_window_factor(0.0, 4), 1.0)
        self.assertEqual(crew_window_factor(1.0, 1), 1.0)
        self.assertEqual(crew_window_factor(1.0, 0), 1.0)
        self.assertAlmostEqual(crew_window_factor(1.0, 2), 0.5)
        self.assertAlmostEqual(crew_window_factor(0.75, 3), 0.5)

    def test_full_share_divides_by_the_crew(self):
        self._crew(self.emp1 | self.emp2)
        nine = self._utc(MONDAY, 9)
        self.assertEqual(self._slot(nine, 120.0, 1.0), (nine, self._utc(MONDAY, 10)))
        wo = self._wo(nine, 120.0, 100.0)
        self.assertEqual(wo._calculate_date_finished(), self._utc(MONDAY, 10))
        self.assertEqual(wo.duration_expected, 120.0, "човеко-минутите не се пипат")

    def test_partial_share(self):
        """75 % от 120 мин с трима: 30 + 90 ÷ 3 = 60 мин."""
        self._crew(self.emp1 | self.emp2 | self.emp3)
        nine = self._utc(MONDAY, 9)
        self.assertEqual(self._slot(nine, 120.0, 0.75)[1], self._utc(MONDAY, 10))
        wo = self._wo(nine, 120.0, 75.0)
        self.assertEqual(wo._calculate_date_finished(), self._utc(MONDAY, 10))

    def test_zero_share_is_unchanged(self):
        self._crew(self.emp1 | self.emp2)
        nine = self._utc(MONDAY, 9)
        self.assertEqual(self._slot(nine, 120.0, 0.0)[1], self._utc(MONDAY, 11))
        wo = self._wo(nine, 120.0, 0.0)
        self.assertFalse(wo.crew_no_crew)
        self.assertEqual(wo._calculate_date_finished(), self._utc(MONDAY, 11))
        wo.write({"date_finished": nine + timedelta(minutes=90)})
        self.assertAlmostEqual(wo.duration_expected, 90.0, places=2)

    def test_without_a_crew_the_full_duration_and_no_crew(self):
        nine = self._utc(MONDAY, 9)
        self.assertEqual(self._slot(nine, 120.0, 1.0)[1], self._utc(MONDAY, 11))
        wo = self._wo(nine, 120.0, 100.0)
        self.assertTrue(wo.crew_no_crew)
        self.assertEqual(wo.crew_names, "No crew")

    def test_share_comes_from_the_operation(self):
        bom = self.env["mrp.bom"].create(
            {"product_tmpl_id": self.product.product_tmpl_id.id, "product_qty": 1.0}
        )
        operation = self.env["mrp.routing.workcenter"].create(
            {"name": "Assembly", "bom_id": bom.id, "workcenter_id": self.wc_pm.id,
             "crew_share": 75.0}
        )
        wo = self._make_wo(self.wc_pm, self._utc(MONDAY, 9), operation_id=operation.id)
        self.assertEqual(wo.crew_share, 75.0)
        # промяна в операцията не пипа заварената поръчка
        operation.crew_share = 50.0
        self.assertEqual(wo.crew_share, 75.0)
        with self.assertRaises(ValidationError):
            operation.crew_share = 120.0

    def test_plan_passes_the_share_to_every_candidate(self):
        """„Plan“ на ядрото: всеки кандидат (центърът и алтернативите) търси
        слот с дела на поръчката."""
        wc_alt = self._make_workcenter("WC Montage PM alt", self.cal_pg)
        self.wc_pm.alternative_workcenter_ids = wc_alt
        wo = self._wo(self._utc(MONDAY, 9), 120.0, 75.0)
        wo.leave_id = False
        seen = []
        Workcenter = type(self.env["mrp.workcenter"])

        def fake(workcenter, *args, **kwargs):
            seen.append((workcenter.id, workcenter.env.context.get(CREW_SHARE)))
            return False, "no slot"

        with patch.object(Workcenter, "_get_first_available_slot", autospec=True, side_effect=fake):
            with self.assertRaises(UserError):
                wo._plan_workorder(replan=True)
        self.assertEqual(sorted(seen), sorted([(self.wc_pm.id, 0.75), (wc_alt.id, 0.75)]))

    def test_bigger_crew_on_the_alternative_finishes_first(self):
        """Кандидатите се сравняват по края — всеки със своята бригада."""
        wc_alt = self._make_workcenter("WC Montage PM alt", self.cal_pg)
        self._crew(self.emp1)
        self._crew(self.emp2 | self.emp3, workcenter=wc_alt)
        nine = self._utc(MONDAY, 9)
        own = self._slot(nine, 120.0, 1.0)
        alt = self._slot(nine, 120.0, 1.0, workcenter=wc_alt)
        self.assertEqual(own[1], self._utc(MONDAY, 11))
        self.assertEqual(alt[1], self._utc(MONDAY, 10))

    def test_gantt_resize_keeps_person_minutes(self):
        self._crew(self.emp1 | self.emp2)
        nine = self._utc(MONDAY, 9)
        wo = self._wo(nine, 120.0, 100.0)
        # разтягане: само краят — 90 мин прозорец × 2 души
        wo.write({"date_finished": nine + timedelta(minutes=90)})
        self.assertAlmostEqual(wo.duration_expected, 180.0, places=2)

    def test_gantt_drag_keeps_the_divided_window(self):
        self._crew(self.emp1 | self.emp2)
        nine = self._utc(MONDAY, 9)
        wo = self._wo(nine, 120.0, 100.0)
        ten = self._utc(MONDAY, 10)
        # влачене: началото и краят заедно — краят се смята наново
        wo.write({"date_start": ten, "date_finished": ten + timedelta(minutes=120)})
        self.assertEqual(wo.date_finished, ten + timedelta(minutes=60))
        self.assertEqual(wo.duration_expected, 120.0)

    def test_changing_the_crew_size_replans_and_pushes(self):
        roster = self._crew(self.emp1 | self.emp2)
        nine = self._utc(MONDAY, 9)
        first = self._wo(nine, 120.0, 100.0)
        first.write({"date_finished": first._calculate_date_finished()})
        self.assertEqual(first.date_finished, self._utc(MONDAY, 10))
        second = self._wo(self._utc(MONDAY, 10), 60.0, 100.0)
        second.write({"date_finished": second._calculate_date_finished()})
        # един човек по-малко: първата става 2 ч и бута втората
        roster.employee_ids = self.emp1
        self.assertEqual(first.date_finished, self._utc(MONDAY, 11))
        self.assertEqual(first.duration_expected, 120.0)
        self.assertGreaterEqual(second.date_start, first.date_finished)

    def test_chain_push_keeps_the_divided_window(self):
        """Избутаната от веригата поръчка пази своя прозорец (дял ÷ бригадата)."""
        self._crew(self.emp1 | self.emp2)
        first = self._wo(self._utc(MONDAY, 9), 120.0, 100.0)
        first.write({"date_finished": first._calculate_date_finished()})
        second = self._wo(self._utc(MONDAY, 10), 60.0, 100.0)
        second.write({"date_finished": second._calculate_date_finished()})
        self.assertEqual(second.date_finished, self._utc(MONDAY, 10, 30))
        half = self._utc(MONDAY, 9, 30)
        first.write({"date_start": half, "date_finished": half + timedelta(minutes=60)})
        self.assertEqual(first.date_finished, self._utc(MONDAY, 10, 30))
        # Избутаната почва секунда след края на предходната, краят ѝ остава
        # (CREW_GAP, Росен 12.10.2026 — пренесено от 19.0.1.8.1).
        self.assertEqual(second.date_start, self._utc(MONDAY, 10, 30) + timedelta(seconds=1))
        self.assertEqual(second.date_finished, self._utc(MONDAY, 11))

    def test_cost_by_the_sum_of_person_minutes(self):
        """Вариант б: бригада 2, 60 мин стенни ⇒ машинната част = costs_hour × 2 ч."""
        loss = self.env["mrp.workcenter.productivity.loss"].search(
            [("loss_type", "=", "productive")], limit=1
        )
        nine = self._utc(MONDAY, 9)

        def cost(share):
            # всеки случай на свой център — иначе веригата бута започнатата
            workcenter = self._make_workcenter("WC cost %s" % share, self.cal_pg)
            workcenter.costs_hour = 10.0
            wo = self._wo(nine, 120.0, share, workcenter=workcenter)
            for employee in self.emp1 | self.emp2:
                self.env["mrp.workcenter.productivity"].create(
                    {
                        "workorder_id": wo.id,
                        "workcenter_id": workcenter.id,
                        "loss_id": loss.id,
                        "employee_id": employee.id,
                        "date_start": nine,
                        "date_end": nine + timedelta(hours=1),
                    }
                )
            return wo._cal_cost()

        self.assertAlmostEqual(cost(100.0) - cost(0.0), 10.0, places=2)
