# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from collections import defaultdict
from datetime import timedelta

from freezegun import freeze_time

from odoo import Command
from odoo.tests import new_test_user, tagged

from ..models.mrp_workorder_crew_split import crew_layout
from .common import MONDAY, CrewWorkorderCommon

SUNDAY = MONDAY - timedelta(days=1)
TUESDAY = MONDAY + timedelta(days=1)
# 05.10.2026 11:00 в София (UTC+3) — „сега“ за пътищата през планираното време.
FROZEN_NOW = "2026-10-05 08:00:00"


def _secs(start, end):
    return int((end - start).total_seconds())


def _union_secs(spans):
    total, last = 0, None
    for start, end in sorted(spans):
        if last is None or start > last:
            total += _secs(start, end)
            last = end
        elif end > last:
            total += _secs(last, end)
            last = end
    return total


@tagged("post_install", "-at_install", "crew_roster")
class TestCrewSplit(CrewWorkorderCommon):
    """Тест 5 от TECH_DESIGN §6: разделянето на времето при приключване
    (M4, M5; SPEC Р3, Р7, Р9, Р19–Р21, Р23, Р26). Инвариантите са в СЕКУНДИ."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Loss = cls.env["mrp.workcenter.productivity.loss"]
        cls.loss = {
            loss_type: Loss.search([("loss_type", "=", loss_type)], limit=1)
            for loss_type in ("productive", "performance", "availability")
        }
        for loss_type, loss in cls.loss.items():
            assert loss, "няма загуба от тип %s" % loss_type
        (cls.emp1 | cls.emp2 | cls.emp3).write({"tz": "Europe/Sofia"})
        cls.crew12 = cls.emp1 | cls.emp2
        # Потребител на производството БЕЗ HR група (операторът в Shop Floor).
        cls.mrp_user = new_test_user(
            cls.env,
            login="crew_split_user",
            email="crew_split_user@crew-test.invalid",
            groups="mrp.group_mrp_user",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )

    # --- помощни ---------------------------------------------------------

    def _line(self, wo, employee, start, end, loss_type="productive"):
        return self.env["mrp.workcenter.productivity"].create(
            {
                "workorder_id": wo.id,
                "workcenter_id": wo.workcenter_id.id,
                "loss_id": self.loss[loss_type].id,
                "employee_id": employee.id,
                "date_start": start,
                "date_end": end,
            }
        )

    def _split_lines(self, wo, loss_types=("productive", "performance")):
        return wo.time_ids.filtered(lambda t: t.loss_type in loss_types)

    def _per_employee(self, lines):
        result = defaultdict(int)
        for line in lines:
            result[line.employee_id] += _secs(line.date_start, line.date_end)
        return dict(result)

    def _S(self, lines):
        return sum(_secs(t.date_start, t.date_end) for t in lines)

    def _U(self, lines):
        return _union_secs([(t.date_start, t.date_end) for t in lines])

    def _leave_type(self, time_type="leave", validation="no_validation"):
        return self.env["hr.leave.type"].create(
            {
                "name": "Crew %s %s" % (time_type, validation),
                "time_type": time_type,
                "requires_allocation": "no",
                "leave_validation_type": validation,
                "request_unit": "hour",
            }
        )

    def _leave(self, employee, leave_type, day, hour_from=None, hour_to=None):
        vals = {
            "name": "Crew leave",
            "employee_id": employee.id,
            "holiday_status_id": leave_type.id,
            "request_date_from": day,
            "request_date_to": day,
        }
        if hour_from is not None:
            vals.update(
                request_unit_hours=True,
                request_hour_from=hour_from,
                request_hour_to=hour_to,
            )
        return self.env["hr.leave"].create(vals)

    # --- подреждането (M5.5), без база ------------------------------------

    def test_layout_invariants(self):
        """Всеки получава L, последният и остатъка; S е точно; U е покрито
        изцяло и нищо не излиза извън [0, U)."""
        for count in range(1, 6):
            for covered in range(1, 25):
                for total in range(covered, covered * 4 + 3):
                    layout = crew_layout(total, covered, count)
                    lengths = [sum(length for _o, length in parts) for parts in layout]
                    share = total // count
                    case = (total, covered, count)
                    self.assertEqual(sum(lengths), total, case)
                    self.assertEqual(lengths[:-1], [share] * (count - 1), case)
                    spans = [(o, o + n) for parts in layout for o, n in parts]
                    self.assertTrue(all(0 <= a < b <= covered for a, b in spans), case)
                    self.assertEqual(_union_secs_int(spans), covered, case)

    # --- M5: реално време -----------------------------------------------

    def test_sequential_split(self):
        """Един човек 08–10, наряд от двама: по 60 мин, разпръснато по реда
        на id; старият ред е изтрит, общото и обединението са запазени."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 8), minutes=120)
        old = self._line(wo, self.emp3, self._utc(MONDAY, 8), self._utc(MONDAY, 10))
        duration = wo.duration
        wo.button_finish()
        self.assertEqual(wo.state, "done")
        self.assertFalse(old.exists(), "старият ред се трие")
        lines = self._split_lines(wo).sorted("date_start")
        self.assertEqual(
            [(t.employee_id, t.date_start, t.date_end) for t in lines],
            [
                (self.emp1, self._utc(MONDAY, 8), self._utc(MONDAY, 9)),
                (self.emp2, self._utc(MONDAY, 9), self._utc(MONDAY, 10)),
            ],
        )
        self.assertEqual(self._S(lines), 7200)
        self.assertEqual(self._U(lines), 7200)
        self.assertAlmostEqual(wo.duration, duration, places=2)
        self.assertTrue(wo.crew_split_signature)
        self.assertEqual(
            [r["employee_id"] for r in wo.crew_time_original], [self.emp3.id]
        )

    def test_r20_more_people_than_roster(self):
        """Р20: трима по 60 мин едновременно, наряд от двама → S = 180 мин и
        U = 60 мин се запазват, всеки по 90 мин."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 8))
        for employee in self.emp1 | self.emp2 | self.emp3:
            self._line(wo, employee, self._utc(MONDAY, 8), self._utc(MONDAY, 9))
        wo.button_finish()
        lines = self._split_lines(wo)
        self.assertEqual(self._S(lines), 10800)
        self.assertEqual(self._U(lines), 3600)
        self.assertEqual(
            self._per_employee(lines), {self.emp1: 5400, self.emp2: 5400}
        )
        self.assertAlmostEqual(wo.duration, 60.0, places=2)

    def test_remainder_goes_to_last(self):
        """S = 6001 с при трима: 2000 + 2000 + 2001 — сборът е точен в секунди."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.emp1 | self.emp2 | self.emp3)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 8))
        start = self._utc(MONDAY, 8)
        self._line(wo, self.emp3, start, start + timedelta(seconds=6001))
        wo.button_finish()
        lines = self._split_lines(wo)
        self.assertEqual(self._S(lines), 6001)
        self.assertEqual(self._U(lines), 6001)
        self.assertEqual(
            self._per_employee(lines),
            {self.emp1: 2000, self.emp2: 2000, self.emp3: 2001},
        )

    def test_overlap_partial(self):
        """Застъпване 08:00–09:00 и 08:30–09:30: S = 120, U = 90 мин; двама
        по 60 мин, обединението е покрито изцяло."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 8))
        self._line(wo, self.emp3, self._utc(MONDAY, 8), self._utc(MONDAY, 9))
        self._line(wo, self.emp1, self._utc(MONDAY, 8, 30), self._utc(MONDAY, 9, 30))
        wo.button_finish()
        lines = self._split_lines(wo)
        self.assertEqual(self._S(lines), 7200)
        self.assertEqual(self._U(lines), 5400)
        self.assertEqual(self._per_employee(lines), {self.emp1: 3600, self.emp2: 3600})
        self.assertAlmostEqual(wo.duration, 90.0, places=2)

    def test_performance_split_other_untouched(self):
        """Р26: делят се и `performance`; престоите (availability) не се пипат."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 8))
        self._line(wo, self.emp3, self._utc(MONDAY, 8), self._utc(MONDAY, 9))
        self._line(
            wo, self.emp3, self._utc(MONDAY, 9), self._utc(MONDAY, 9, 30), "performance"
        )
        block = self._line(
            wo, self.emp3, self._utc(MONDAY, 9, 30), self._utc(MONDAY, 10), "availability"
        )
        wo.button_finish()
        performance = self._split_lines(wo, ("performance",))
        self.assertEqual(
            self._per_employee(performance), {self.emp1: 900, self.emp2: 900}
        )
        self.assertEqual(self._U(performance), 1800)
        productive = self._split_lines(wo, ("productive",))
        self.assertEqual(
            self._per_employee(productive), {self.emp1: 1800, self.emp2: 1800}
        )
        self.assertTrue(block.exists(), "престоят не се пипа")
        self.assertEqual(block.employee_id, self.emp3)
        self.assertEqual(
            (block.date_start, block.date_end),
            (self._utc(MONDAY, 9, 30), self._utc(MONDAY, 10)),
        )

    def test_create_not_write_employee_cost(self):
        """M5.6: само `create` — ставката на новия ред е на новия човек, не
        замразената на стария ред."""
        self.emp1.hourly_cost = 10.0
        self.emp2.hourly_cost = 10.0
        self.emp3.hourly_cost = 30.0
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 8))
        old = self._line(wo, self.emp3, self._utc(MONDAY, 8), self._utc(MONDAY, 10))
        self.assertEqual(old.employee_cost, 30.0)
        wo.button_finish()
        lines = self._split_lines(wo)
        self.assertEqual(
            sorted(lines.mapped("employee_cost")), [10.0, 10.0],
            "ставката е на човека от наряда, не замразената 30 на стария ред",
        )
        self.assertNotIn(old.id, lines.ids)

    # --- Р19: две смени; парчета извън смените ------------------------------

    def test_r19_two_shifts(self):
        """Поръчка 19–21 на 2×12: дневната смяна (08:00) дели своя час между
        своя наряд, нощната (20:00) — своя."""
        self._roster(self.wc_2x12, MONDAY, "08:00", self.crew12)
        self._roster(self.wc_2x12, MONDAY, "20:00", self.emp3)
        wo = self._make_wo(self.wc_2x12, self._utc(MONDAY, 19), minutes=120)
        self._line(wo, self.emp1, self._utc(MONDAY, 19), self._utc(MONDAY, 21))
        wo.button_finish()
        lines = self._split_lines(wo)
        self.assertEqual(
            self._per_employee(lines),
            {self.emp1: 1800, self.emp2: 1800, self.emp3: 3600},
        )
        night = lines.filtered(lambda t: t.employee_id == self.emp3)
        self.assertEqual(night.date_start, self._utc(MONDAY, 20))
        self.assertEqual(self._U(lines), 7200)

    def test_night_shift_over_midnight(self):
        """Нощната смяна 20–08 е един блок: 23:00–01:00 се дели само между
        нощния наряд на деня на началото."""
        self._roster(self.wc_2x12, MONDAY, "20:00", self.crew12)
        wo = self._make_wo(self.wc_2x12, self._utc(MONDAY, 23), minutes=120)
        self._line(wo, self.emp3, self._utc(MONDAY, 23), self._utc(TUESDAY, 1))
        wo.button_finish()
        lines = self._split_lines(wo)
        self.assertEqual(self._per_employee(lines), {self.emp1: 3600, self.emp2: 3600})

    def test_piece_after_shift_goes_to_previous_block(self):
        """Парче извън смените (извънреден час 17–18) отива към предходния
        блок — нищо не се губи."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 16), minutes=120)
        self._line(wo, self.emp3, self._utc(MONDAY, 16), self._utc(MONDAY, 18))
        wo.button_finish()
        lines = self._split_lines(wo)
        self.assertEqual(self._S(lines), 7200)
        self.assertEqual(self._U(lines), 7200)
        self.assertEqual(self._per_employee(lines), {self.emp1: 3600, self.emp2: 3600})

    def test_piece_before_shift_goes_to_next_block(self):
        """M5.2 (решение 06.10): 07–08 в понеделник е ПРЕДИ смяната от 08:00
        в същия местен ден → отива към нея (а не към неделния блок, който е
        с друг наряд) и се дели с 08–09 между наряда на понеделник."""
        self._roster(self.wc_pg, SUNDAY, "08:00", self.emp3)
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 7), minutes=120)
        old = self._line(wo, self.emp3, self._utc(MONDAY, 7), self._utc(MONDAY, 9))
        wo.button_finish()
        self.assertFalse(old.exists())
        lines = self._split_lines(wo)
        self.assertEqual(self._S(lines), 7200)
        self.assertEqual(self._U(lines), 7200)
        self.assertEqual(
            self._per_employee(lines), {self.emp1: 3600, self.emp2: 3600}
        )
        self.assertEqual(min(lines.mapped("date_start")), self._utc(MONDAY, 7))

    def test_no_roster_untouched(self):
        """Център без наряд: редовете остават, както са отчетени."""
        self._roster(self.wc_2x12, MONDAY, "08:00", self.crew12)  # друг център
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 8))
        old = self._line(wo, self.emp3, self._utc(MONDAY, 8), self._utc(MONDAY, 9))
        wo.button_finish()
        self.assertEqual(self._split_lines(wo), old)
        self.assertEqual(old.employee_id, self.emp3)
        self.assertFalse(wo.crew_split_signature)
        self.assertEqual(wo._crew_split_time(), {wo.id: "no_crew"})

    # --- Р9, Р23: отпуск ---------------------------------------------------

    def _finish_as_mrp_user(self, wo):
        wo.with_user(self.mrp_user).button_finish()
        self.assertEqual(wo.state, "done")
        return self._per_employee(self._split_lines(wo))

    def _wo_two_hours(self):
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 8), minutes=120)
        self._line(wo, self.emp3, self._utc(MONDAY, 8), self._utc(MONDAY, 10))
        return wo

    def test_leave_excludes_as_mrp_user(self):
        """Одобрен отпуск изключва; търсенето е под sudo — операторът е без
        HR права и не вижда чуждия отпуск (Ф2)."""
        self.assertFalse(self.mrp_user.has_group("hr_holidays.group_hr_holidays_user"))
        leave = self._leave(self.emp2, self._leave_type(), MONDAY)
        self.assertEqual(leave.state, "validate")
        wo = self._wo_two_hours()
        self.assertEqual(self._finish_as_mrp_user(wo), {self.emp1: 7200})

    def test_partial_leave_excludes_whole_block(self):
        """Р23: 2 часа отпуск (14–16, след работата) изключват от целия блок."""
        leave = self._leave(self.emp2, self._leave_type(), MONDAY, 14.0, 16.0)
        self.assertEqual(leave.state, "validate")
        self.assertLess(leave.date_to - leave.date_from, timedelta(hours=3))
        wo = self._wo_two_hours()
        self.assertEqual(self._finish_as_mrp_user(wo), {self.emp1: 7200})

    def test_business_trip_does_not_exclude(self):
        """Р23: командировка (`time_type = other`) НЕ изключва."""
        leave = self._leave(self.emp2, self._leave_type("other"), MONDAY)
        self.assertEqual(leave.state, "validate")
        wo = self._wo_two_hours()
        self.assertEqual(
            self._finish_as_mrp_user(wo), {self.emp1: 3600, self.emp2: 3600}
        )

    def test_unapproved_leave_does_not_exclude(self):
        """Р9: само одобреният (`validate`) отпуск изключва."""
        leave = self._leave(self.emp2, self._leave_type(validation="hr"), MONDAY)
        self.assertEqual(leave.state, "confirm")
        wo = self._wo_two_hours()
        self.assertEqual(
            self._finish_as_mrp_user(wo), {self.emp1: 3600, self.emp2: 3600}
        )

    def test_leave_other_day_does_not_exclude(self):
        leave = self._leave(self.emp2, self._leave_type(), TUESDAY)
        self.assertEqual(leave.state, "validate")
        wo = self._wo_two_hours()
        self.assertEqual(
            self._finish_as_mrp_user(wo), {self.emp1: 3600, self.emp2: 3600}
        )

    def test_whole_crew_on_leave_untouched(self):
        """Целият наряд в отпуск → екипът е празен → редовете остават."""
        leave_type = self._leave_type()
        self._leave(self.emp1, leave_type, MONDAY)
        self._leave(self.emp2, leave_type, MONDAY)
        wo = self._wo_two_hours()
        self.assertEqual(self._finish_as_mrp_user(wo), {self.emp3: 7200})

    # --- Р21: без реално време ---------------------------------------------

    @freeze_time(FROZEN_NOW)
    def test_r21_planned_time_split(self):
        """Без реални редове се дели `duration_expected` (60 мин) без
        повторно × time_efficiency, в [край − 60 мин, край]."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 10), minutes=60)
        self.wc_pg.time_efficiency = 50.0
        self.assertEqual(wo.duration_expected, 60.0)
        wo.button_finish()
        self.assertEqual(wo.date_finished, self._utc(MONDAY, 11))
        lines = self._split_lines(wo).sorted("date_start")
        self.assertEqual(
            [(t.employee_id, t.date_start, t.date_end) for t in lines],
            [
                (self.emp1, self._utc(MONDAY, 10), self._utc(MONDAY, 10, 30)),
                (self.emp2, self._utc(MONDAY, 10, 30), self._utc(MONDAY, 11)),
            ],
        )
        self.assertAlmostEqual(wo.duration, 60.0, places=2)
        self.assertTrue(wo.crew_time_original[0]["virtual"])

    def test_planned_time_ends_at_the_context_moment(self):
        """Теолино №173: одобрено във вторник, отчетът изпратен в понеделник
        (crew_split_end_at) ⇒ минутите — при наряда от понеделник."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        self._roster(self.wc_pg, TUESDAY, "08:00", self.emp3)
        wo = self._make_wo(self.wc_pg, self._utc(TUESDAY, 10), minutes=60)
        wo.with_context(crew_split_end_at=self._utc(MONDAY, 11)).button_finish()
        lines = self._split_lines(wo).sorted("date_start")
        self.assertEqual(lines.employee_id, self.crew12)
        self.assertEqual(lines[0].date_start, self._utc(MONDAY, 10))
        self.assertEqual(lines[-1].date_end, self._utc(MONDAY, 11))

    @freeze_time(FROZEN_NOW)
    def test_action_mark_as_done_path(self):
        """EE action_mark_as_done: планираните редове са създадени от M4 —
        стандартният ред на свързания служител (emp3) не се добавя."""
        self.emp3.user_id = self.mrp_user
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 10), minutes=60)
        wo.with_user(self.mrp_user).action_mark_as_done()
        self.assertEqual(wo.state, "done")
        self.assertEqual(
            self._per_employee(wo.time_ids), {self.emp1: 1800, self.emp2: 1800}
        )
        self.assertEqual(
            set(wo.time_ids.mapped("user_id").ids), {self.mrp_user.id},
            "user_id е на приключилия, служителят — от наряда",
        )

    @freeze_time(FROZEN_NOW)
    def test_button_mark_done_path(self):
        """МО → button_mark_done → button_finish на поръчките → разделяне."""
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.product.product_tmpl_id.id,
                "product_qty": 1.0,
                "operation_ids": [
                    Command.create(
                        {
                            "name": "Crew cut",
                            "workcenter_id": self.wc_pg.id,
                            "time_mode": "manual",
                            "time_cycle_manual": 60.0,
                        }
                    )
                ],
            }
        )
        mo = self.env["mrp.production"].create(
            {"product_id": self.product.id, "product_qty": 1.0, "bom_id": bom.id}
        )
        mo.action_confirm()
        wo = mo.workorder_ids
        self.assertEqual(len(wo), 1)
        mo.qty_producing = 1.0
        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        self.assertEqual(wo.state, "done")
        lines = self._split_lines(wo)
        self.assertEqual(self._per_employee(lines), {self.emp1: 1800, self.emp2: 1800})
        self.assertEqual(self._S(lines), round(wo.duration_expected * 60))

    # --- M5.8: подпис; M5.7: одит; M5.9: гардове -------------------------------

    def test_signature_skips_and_original_kept(self):
        roster = self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 8), minutes=120)
        # втора, неприключена операция — МО-то остава отворено и там, където
        # модул приключва МО с последната операция (Теолино, teolino_shop_station)
        self._make_wo(self.wc_pg, self._utc(MONDAY, 13), minutes=30, mo=wo.production_id)
        self._line(wo, self.emp3, self._utc(MONDAY, 8), self._utc(MONDAY, 10))
        wo.button_finish()
        first = self._split_lines(wo)
        signature = wo.crew_split_signature
        original = wo.crew_time_original
        # Втори пуск без промяна — нищо.
        self.assertEqual(wo._crew_split_time(), {wo.id: "unchanged"})
        self.assertEqual(self._split_lines(wo), first, "редовете не се пресъздават")
        # Промяна в наряда → ново разделяне; одитът остава от първото.
        roster.employee_ids = [Command.set(self.emp2.ids)]
        self.assertEqual(wo._crew_split_time(recompute=True), {wo.id: "split"})
        lines = self._split_lines(wo)
        self.assertEqual(self._per_employee(lines), {self.emp2: 7200})
        self.assertNotEqual(wo.crew_split_signature, signature)
        self.assertEqual(wo.crew_time_original, original)
        self.assertEqual(
            [r["employee_id"] for r in wo.crew_time_original], [self.emp3.id]
        )

    def test_recompute_guard_mo_done(self):
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 8))
        old = self._line(wo, self.emp3, self._utc(MONDAY, 8), self._utc(MONDAY, 9))
        wo.production_id.state = "done"
        self.assertEqual(wo._crew_split_time(recompute=True), {wo.id: "mo_done"})
        self.assertTrue(old.exists())
        # Без гардовете (пътят при приключване) се дели.
        self.assertEqual(wo._crew_split_time(), {wo.id: "split"})

    def test_recompute_guard_posted(self):
        Productivity = self.env["mrp.workcenter.productivity"]
        if "account_move_line_id" not in Productivity._fields:
            self.skipTest("mrp_account не е инсталиран")
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._make_wo(self.wc_pg, self._utc(MONDAY, 8))
        old = self._line(wo, self.emp3, self._utc(MONDAY, 8), self._utc(MONDAY, 9))
        journal = self.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", self.company.id)], limit=1
        )
        account = self.env["account.account"].search(
            [("company_ids", "in", self.company.ids)], limit=1
        )
        if not (journal and account):
            self.skipTest("няма дневник/сметка в базата")
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": journal.id,
                "line_ids": [
                    Command.create({"account_id": account.id, "debit": 1.0}),
                    Command.create({"account_id": account.id, "credit": 1.0}),
                ],
            }
        )
        old.account_move_line_id = move.line_ids[:1]
        self.assertEqual(wo._crew_split_time(recompute=True), {wo.id: "posted"})
        self.assertTrue(old.exists())


def _union_secs_int(spans):
    total, last = 0, None
    for start, end in sorted(spans):
        if last is None or start > last:
            total += end - start
            last = end
        elif end > last:
            total += end - last
            last = end
    return total
