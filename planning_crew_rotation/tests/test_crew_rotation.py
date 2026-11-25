# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Бригадите на главния график пълнят смените в Planning (Росен 14.10.2026).

Ротация 2-2-4 (8 дни: 2 дневни, 2 нощни, 4 почивни), бригади A/B/C/D с
отмествания 0/2/4/6, по един човек в бригада: всеки ден точно една дневна и
една нощна смяна.
"""
from datetime import date, datetime, timedelta

from freezegun import freeze_time

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

ANCHOR = date(2026, 11, 1)


def _with_contract(env, vals):
    """В 18 служителят няма сам версия на договора (в 19 има) — тестовете му дават
    текущ договор, защото назначенията и нощният труд стоят в договора."""
    employees = env["hr.employee"].create(vals)
    extra = {}
    if "l10n_bg_contract_date" in env["hr.contract"]._fields:
        # БГ локализацията: датата на сключване не е след началото (по подразбиране е днес)
        extra["l10n_bg_contract_date"] = date(2026, 1, 1)
    env["hr.contract"].create([dict({
        "name": "Crew test – %s" % employee.name, "employee_id": employee.id,
        "wage": 1000.0, "date_start": date(2026, 1, 1), "state": "open",
    }, **extra) for employee in employees])
    return employees


@tagged("post_install", "-at_install")
class TestCrewRotation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, lang="en_US", tz="Europe/Sofia"))
        env = cls.env
        env.user.tz = "Europe/Sofia"
        Template = env["planning.slot.template"]
        cls.day = Template.create({"start_time": 7.0, "end_time": 19.0, "duration_days": 1})
        cls.night = Template.create({"start_time": 19.0, "end_time": 7.0, "duration_days": 2})
        cls.calendar = env["resource.calendar"].create(
            {"name": "Continuous 2x12 (test)", "tz": "Europe/Sofia"})
        cls.rotation = env["planning.crew.rotation"].create({
            "name": "Extrusion (test)",
            "calendar_id": cls.calendar.id,
            "day_template_id": cls.day.id,
            "night_template_id": cls.night.id,
            "anchor_date": ANCHOR,
            "preset": "2-2-4",
        })
        cls.rotation.action_load_preset()
        cls.crews = cls.rotation.crew_ids.sorted("offset_days")
        cls.employees = _with_contract(env, [
            {"name": "Crew member %s" % code, "tz": "Europe/Sofia"} for code in "ABCD"])
        for employee, crew in zip(cls.employees, cls.crews):
            env["planning.crew.membership"].create({
                "contract_id": employee.contract_id.id,
                "crew_id": crew.id,
                "date_from": ANCHOR,
            })
        cls.substitute = _with_contract(env, 
            {"name": "Substitute", "tz": "Europe/Sofia"})
        cls.leave_type = env["hr.leave.type"].create({
            "name": "Paid leave (crew test)",
            "requires_allocation": "no",
            "leave_validation_type": "no_validation",
        })

    def _slots(self, day=None):
        domain = [("crew_rotation_id", "=", self.rotation.id)]
        if day:
            domain.append(("crew_date", "=", day))
        return self.env["planning.slot"].search(domain)

    def test_preset_covers_and_approves(self):
        self.assertEqual(self.rotation.cycle_length, 8)
        self.assertEqual(self.crews.mapped("offset_days"), [0, 2, 4, 6])
        self.assertFalse(self.rotation._coverage_issues())
        self.assertFalse(self.rotation._labour_issues())
        self.rotation.action_approve()
        self.assertEqual(self.rotation.state, "approved")

    def test_broken_coverage_is_refused(self):
        self.crews[1].offset_days = 0
        self.assertTrue(self.rotation._coverage_issues())
        with self.assertRaises(ValidationError):
            self.rotation.action_approve()

    def test_more_than_56_hours_is_refused(self):
        rotation = self.rotation.copy({"name": "Six days (test)", "preset": False})
        rotation.line_ids.filtered(lambda l: l.position < 6).template_id = self.day
        issues = rotation._labour_issues()
        self.assertTrue(any("seven days" in issue for issue in issues), issues)

    def test_generate_one_day_and_one_night_shift_every_day(self):
        self.rotation.action_approve()
        counts = self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=7))
        self.assertEqual(counts["created"], 16)
        for offset in range(8):
            slots = self._slots(ANCHOR + timedelta(days=offset))
            self.assertEqual(sorted(slots.template_id.ids), sorted((self.day | self.night).ids))
        # бригада A е дневна на 1 и 2, нощна на 3 и 4 ноември
        a_slots = self._slots().filtered(lambda s: s.crew_id == self.crews[0])
        self.assertEqual(sorted(a_slots.mapped("crew_date")),
                         [ANCHOR, ANCHOR + timedelta(days=1),
                          ANCHOR + timedelta(days=2), ANCHOR + timedelta(days=3)])
        night = a_slots.filtered(lambda s: s.crew_date == ANCHOR + timedelta(days=2))
        # 19:00 → 07:00 по София (EET, UTC+2)
        self.assertEqual(night.start_datetime, datetime(2026, 11, 3, 17, 0))
        self.assertEqual(night.end_datetime, datetime(2026, 11, 4, 5, 0))
        self.assertEqual(night.resource_id, self.employees[0].resource_id)

    def test_generate_again_changes_nothing(self):
        self.rotation.action_approve()
        self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=7))
        counts = self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=7))
        self.assertEqual((counts["created"], counts["updated"], counts["deleted"],
                          counts["kept"]), (0, 0, 0, 16))

    def test_dry_run_writes_nothing(self):
        self.rotation.action_approve()
        counts = self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=7), dry_run=True)
        self.assertEqual(counts["created"], 16)
        self.assertFalse(self._slots())

    def test_shift_changed_by_hand_is_kept(self):
        self.rotation.action_approve()
        self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=1))
        slot = self._slots(ANCHOR).filtered(lambda s: s.crew_id == self.crews[0])
        slot.resource_id = self.substitute.resource_id
        self.assertTrue(slot.crew_manual)
        counts = self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=1))
        self.assertEqual(counts["conflicts"], 1)
        self.assertEqual(slot.resource_id, self.substitute.resource_id)

    def test_published_shift_is_kept(self):
        self.rotation.action_approve()
        self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=1))
        slot = self._slots(ANCHOR).filtered(lambda s: s.crew_id == self.crews[0])
        slot.state = "published"
        self.crews[0].membership_ids.date_from = ANCHOR + timedelta(days=1)
        counts = self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=1))
        self.assertTrue(slot.exists())
        self.assertEqual(counts["conflicts"], 1)

    def test_leave_flags_reload_and_substitute_takes_the_shift(self):
        self.rotation.action_approve()
        # 3 ноември (вторник): бригада A е нощна, B — дневна
        leave_day = ANCHOR + timedelta(days=2)
        self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=7))
        self.employees[0].crew_substitute_ids = self.substitute
        self.env["hr.leave"].create({
            "employee_id": self.employees[0].id,
            "holiday_status_id": self.leave_type.id,
            "request_date_from": leave_day,
            "request_date_to": leave_day,
        })
        self.assertTrue(self.rotation.reload_needed)
        counts = self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=7))
        self.assertFalse(self.rotation.reload_needed)
        self.assertEqual(counts["substituted"], 1)
        night = self._slots(leave_day).filtered(lambda s: s.crew_id == self.crews[0])
        self.assertEqual(night.resource_id, self.substitute.resource_id)
        self.assertEqual(night.crew_substitute_for_id, self.employees[0])

    def test_leave_without_substitute_leaves_an_open_shift(self):
        self.rotation.action_approve()
        leave_day = ANCHOR + timedelta(days=2)
        self.env["hr.leave"].create({
            "employee_id": self.employees[0].id,
            "holiday_status_id": self.leave_type.id,
            "request_date_from": leave_day,
            "request_date_to": leave_day,
        })
        counts = self.rotation._crew_generate(leave_day, leave_day)
        self.assertEqual(counts["open"], 1)
        night = self._slots(leave_day).filtered(lambda s: s.crew_id == self.crews[0])
        self.assertFalse(night.resource_id)

    def test_dst_night_lasts_thirteen_hours(self):
        """25.10.2026 часовникът се връща с час: нощната от 24.10 е 19:00 →
        07:00 местно, 13 реални часа."""
        start, end = self.rotation._shift_interval(self.night, date(2026, 10, 24))
        self.assertEqual(start, datetime(2026, 10, 24, 16, 0))
        self.assertEqual(end, datetime(2026, 10, 25, 5, 0))
        self.assertEqual(end - start, timedelta(hours=13))

    def test_membership_cannot_overlap(self):
        with self.assertRaises(ValidationError):
            self.env["planning.crew.membership"].create({
                "contract_id": self.employees[0].contract_id.id,
                "crew_id": self.crews[1].id,
                "date_from": ANCHOR + timedelta(days=10),
            })


@tagged("post_install", "-at_install")
class TestEmployeeCrew(TransactionCase):
    """Бригадата като поле в картона на служителя (Росен 14.10.2026)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, lang="en_US"))
        env = cls.env
        cls.today = date.today()
        cls.rotation = env["planning.crew.rotation"].create({
            "name": "Recycling (employee test)", "anchor_date": cls.today.replace(day=1)})
        cls.crew_k, cls.crew_l = env["planning.crew"].create([
            {"rotation_id": cls.rotation.id, "code": "K", "offset_days": 0},
            {"rotation_id": cls.rotation.id, "code": "L", "offset_days": 2},
        ])
        cls.employee = _with_contract(env, {"name": "Recycler"})
        env["planning.crew.membership"].create({
            "contract_id": cls.employee.contract_id.id,
            "crew_id": cls.crew_k.id,
            "date_from": cls.today - timedelta(days=30),
        })

    def test_crew_of_today_is_stored_and_searchable(self):
        self.assertEqual(self.employee.crew_id, self.crew_k)
        Employee = self.env["hr.employee"]
        self.assertIn(self.employee, Employee.search([("crew_id", "=", self.crew_k.id)]))
        groups = Employee._read_group([("id", "=", self.employee.id)], ["crew_id"], ["__count"])
        self.assertEqual(groups, [(self.crew_k, 1)])

    def test_changing_the_crew_closes_the_old_membership(self):
        self.employee.crew_id = self.crew_l
        history = self.employee.crew_membership_all_ids.sorted("date_from")
        self.assertEqual(history.mapped("crew_id"), self.crew_k | self.crew_l)
        self.assertEqual(history[0].date_to, self.today - timedelta(days=1))
        self.assertEqual(history[1].date_from, self.today)
        self.assertFalse(history[1].date_to)
        self.assertEqual(self.employee.crew_id, self.crew_l)

    def test_clearing_the_crew_ends_the_membership(self):
        self.employee.crew_id = False
        self.assertEqual(self.employee.crew_membership_all_ids.date_to,
                         self.today - timedelta(days=1))
        self.assertFalse(self.employee.crew_id)

    def test_without_a_contract_the_crew_is_refused(self):
        """В 18 назначението стои в договора: без текущ договор — ясен отказ."""
        loner = self.env["hr.employee"].create({"name": "Without contract"})
        with self.assertRaises(UserError):
            loner.crew_id = self.crew_k

    def test_import_with_the_cycle_start(self):
        """Импорт с `crew_date`: назначението тръгва от началото на цикъла."""
        newcomer = _with_contract(self.env, {"name": "Newcomer"})
        start = self.today.replace(day=1)
        newcomer.with_context(crew_date=start).crew_id = self.crew_l
        self.assertEqual(newcomer.crew_membership_all_ids.date_from, start)
        self.assertEqual(newcomer.crew_id, self.crew_l)

    def test_cron_moves_the_crew_on_the_day(self):
        tomorrow = self.today + timedelta(days=1)
        self.employee.crew_membership_all_ids.date_to = self.today
        self.env["planning.crew.membership"].create({
            "contract_id": self.employee.contract_id.id,
            "crew_id": self.crew_l.id,
            "date_from": tomorrow,
        })
        self.assertEqual(self.employee.crew_id, self.crew_k)
        with freeze_time(tomorrow):
            self.env["hr.employee"]._cron_crew_refresh()
        self.assertEqual(self.employee.crew_id, self.crew_l)


@tagged("post_install", "-at_install")
class TestScheduleByCrew(TransactionCase):
    """Менюто „По бригада“ отваря Ганта, групиран по бригада и служител."""

    def test_gantt_groups_by_crew_then_resource(self):
        action = self.env.ref("planning_crew_rotation.planning_action_schedule_by_crew")
        gantt = action.view_ids.filtered(lambda v: v.view_mode == "gantt").view_id
        arch = self.env["planning.slot"].get_view(gantt.id, "gantt")["arch"]
        self.assertIn('default_group_by="crew_id,resource_id"', arch)
        self.assertEqual(
            self.env.ref("planning_crew_rotation.planning_menu_schedule_by_crew").action, action)


@tagged("post_install", "-at_install")
class TestCrewLaw(TransactionCase):
    """Правилата на закона при поставянето на хора (Росен 15.10.2026; LEGAL.md)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, lang="en_US", tz="Europe/Sofia"))
        env = cls.env
        env.user.tz = "Europe/Sofia"
        Template = env["planning.slot.template"]
        cls.day = Template.create({"start_time": 7.0, "end_time": 19.0, "duration_days": 1})
        cls.night = Template.create({"start_time": 19.0, "end_time": 7.0, "duration_days": 2})
        cls.calendar = env["resource.calendar"].create({"name": "2x12 (law test)", "tz": "Europe/Sofia"})
        cls.rotation = env["planning.crew.rotation"].create({
            "name": "Extrusion (law test)", "calendar_id": cls.calendar.id,
            "day_template_id": cls.day.id, "night_template_id": cls.night.id,
            "anchor_date": ANCHOR, "preset": "2-2-4"})
        cls.rotation.action_load_preset()
        cls.rotation.action_approve()
        cls.crew_a = cls.rotation.crew_ids.sorted("offset_days")[0]
        cls.worker = _with_contract(env, {"name": "Night worker", "tz": "Europe/Sofia"})
        env["planning.crew.membership"].create({
            "contract_id": cls.worker.contract_id.id, "crew_id": cls.crew_a.id, "date_from": ANCHOR})
        cls.leave_type = env["hr.leave.type"].create({
            "name": "Leave (law test)", "requires_allocation": "no",
            "leave_validation_type": "no_validation"})
        # 2-2-4: бригада A е нощна на 3 и 4 ноември
        cls.night_day = ANCHOR + timedelta(days=2)

    def _slot(self, day):
        return self.env["planning.slot"].search([
            ("crew_rotation_id", "=", self.rotation.id), ("crew_date", "=", day)])

    def test_night_hours_are_converted(self):
        from ..models import crew_law
        conv = lambda a, b: round(crew_law.converted_hours(a, b), 3)
        d = datetime(2026, 11, 3)
        self.assertEqual(conv(d.replace(hour=19), d.replace(hour=7) + timedelta(days=1)), 13.144)
        self.assertEqual(conv(d.replace(hour=22), d.replace(hour=6) + timedelta(days=1)), 9.144)
        self.assertEqual(conv(d.replace(hour=6), d.replace(hour=14)), 8.0)
        # 14–22: нощни няма; 19–23 = 1 ч нощ (< 4) — без превръщане
        self.assertEqual(conv(d.replace(hour=19), d.replace(hour=23)), 4.0)

    def test_minor_on_night_shift_is_warned(self):
        self.worker.birthday = self.night_day - timedelta(days=17 * 365)
        self.worker.crew_night_medical_date = ANCHOR
        self.rotation._crew_generate(self.night_day, self.night_day)
        self.assertIn("under 18", self._slot(self.night_day).crew_warning or "")

    def test_night_worker_without_medical_is_warned_with_it_not(self):
        self.rotation._crew_generate(self.night_day, self.night_day)
        self.assertIn("medical", self._slot(self.night_day).crew_warning or "")
        self.worker.crew_night_medical_date = ANCHOR
        counts = self.rotation._crew_generate(self.night_day, self.night_day)
        self.assertFalse(self._slot(self.night_day).crew_warning)
        self.assertEqual(counts["warnings"], 0)

    def test_consent_needed(self):
        self.worker.write({"crew_night_medical_date": ANCHOR, "crew_night_consent_needed": True})
        self.rotation._crew_generate(self.night_day, self.night_day)
        self.assertIn("consent", self._slot(self.night_day).crew_warning or "")
        self.worker.crew_night_consent_date = ANCHOR
        self.rotation._crew_generate(self.night_day, self.night_day)
        self.assertFalse(self._slot(self.night_day).crew_warning)

    def test_pregnant_substitute_is_skipped(self):
        pregnant, fit = _with_contract(self.env, [
            {"name": "Pregnant substitute", "tz": "Europe/Sofia"},
            {"name": "Fit substitute", "tz": "Europe/Sofia", }])
        pregnant.write({"crew_pregnancy_from": ANCHOR, "crew_night_medical_date": ANCHOR})
        fit.crew_night_medical_date = ANCHOR
        self.worker.crew_substitute_ids = pregnant | fit
        self.env["hr.leave"].create({
            "employee_id": self.worker.id, "holiday_status_id": self.leave_type.id,
            "request_date_from": self.night_day, "request_date_to": self.night_day})
        self.rotation._crew_generate(self.night_day, self.night_day)
        self.assertEqual(self._slot(self.night_day).resource_id, fit.resource_id)

    def test_short_rest_is_warned(self):
        self.worker.crew_night_medical_date = ANCHOR
        # 1 ноември бригада A е дневна 07–19; ръчна смяна 21:00–23:00 → < 12 ч почивка до 07:00 на 2.11
        self.env["planning.slot"].create({
            "resource_id": self.worker.resource_id.id,
            "start_datetime": datetime(2026, 11, 1, 19, 0), "end_datetime": datetime(2026, 11, 1, 21, 0)})
        self.rotation._crew_generate(ANCHOR + timedelta(days=1), ANCHOR + timedelta(days=1))
        self.assertIn("12 h rest", self._slot(ANCHOR + timedelta(days=1)).crew_warning or "")

    def test_norm_of_the_period(self):
        self.assertEqual(self.rotation.summing_period_months, "3")
        self.rotation.summing_period_months = "1"
        self.rotation._crew_generate(ANCHOR, date(2026, 11, 30))
        (date_from, date_to), rows = self.rotation._crew_norm_rows(date(2026, 11, 15))
        self.assertEqual((date_from, date_to), (date(2026, 11, 1), date(2026, 11, 30)))
        row = rows[0]
        holidays = self.rotation._crew_holidays(date_from, date_to)
        workdays = sum(1 for i in range(30) if (date_from + timedelta(days=i)).weekday() < 5
                       and date_from + timedelta(days=i) not in holidays)
        self.assertEqual(row["norm"], workdays * 8.0)
        # 2-2-4 от 1.11: A работи дни 0–3, 8–11, 16–19, 24–27 → 16 смени по 12 ч (8 нощни)
        self.assertEqual(row["raw"], 16 * 12.0)
        self.assertAlmostEqual(row["converted"], 8 * 12.0 + 8 * (12.0 + 8 * 0.143), places=3)
        self.assertGreater(row["converted"], row["raw"])
        self.assertAlmostEqual(row["excess"], row["converted"] - row["norm"])
        # предупреждението в ротацията е за ДНЕШНИЯ период
        with freeze_time(date(2026, 11, 15)):
            self.rotation.invalidate_recordset(["norm_html", "norm_warning_count"])
            self.assertEqual(self.rotation.norm_warning_count, 1)
            self.assertIn("table-danger", self.rotation.norm_html)
