# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import date, datetime, time, timedelta

from pytz import timezone, utc

from odoo import Command
from odoo.tests import TransactionCase

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Понеделник, 05.10.2026 — опорна дата за всички тестове.
MONDAY = date(2026, 10, 5)

# Ключовете, които модулът сам слага в контекста на Ганта. Тестовете гледат
# само тях: други модули (напр. teolino_mrp_shop_planning) добавят свои филтри
# в същия контекст и равенство дума по дума би ги направило зависими от това
# кое още е инсталирано в базата.
CREW_GANTT_CONTEXT_KEYS = (
    "search_default_workcenter_id",
    "crew_workcenter_id",
    "crew_workcenter_ids",
)


class CrewRosterCommon(TransactionCase):
    """Общи данни: календари с различни смени и центрове върху тях."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Roster = cls.env["mrp.workcenter.roster"]
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.ICP.set_param("mrp_workcenter_crew_roster.shift_gap_hours", "1.0")

        # Календарът на Полигруп (И1): всеки ден 08–12, обяд 12–13, 13–17,
        # със стандартните имена на редовете.
        lines = []
        for dow in range(7):
            lines += [
                (dow, 8, 12, "morning", "%s Morning" % DAYS[dow]),
                (dow, 12, 13, "lunch", "%s Lunch" % DAYS[dow]),
                (dow, 13, 17, "afternoon", "%s Afternoon" % DAYS[dow]),
            ]
        cls.cal_pg = cls._make_calendar("Shop floor - 7 days", lines)

        # Две смени по 12 часа (Р28): дневна 08–20 с обяд 12–13,
        # нощна 20–24 + 00–08 на следващия ден.
        lines = []
        for dow in range(7):
            lines += [
                (dow, 0, 8, "morning", "Night tail"),
                (dow, 8, 12, "morning", "Day 1"),
                (dow, 12, 13, "lunch", "Lunch"),
                (dow, 13, 20, "afternoon", "Day 2"),
                (dow, 20, 24, "afternoon", "Night head"),
            ]
        cls.cal_2x12 = cls._make_calendar("Two shifts 2x12", lines)

        cls.wc_pg = cls._make_workcenter("WC Polygroup", cls.cal_pg)
        cls.wc_2x12 = cls._make_workcenter("WC 2x12", cls.cal_2x12)

        cls.emp1 = cls.env["hr.employee"].create({"name": "Crew One"})
        cls.emp2 = cls.env["hr.employee"].create({"name": "Crew Two"})
        cls.emp3 = cls.env["hr.employee"].create({"name": "Crew Three"})

    @classmethod
    def _make_calendar(cls, name, lines, tz="Europe/Sofia", **extra):
        """lines: (ден, от, до, day_period, име[, week_type])."""
        attendances = []
        for line in lines:
            dow, hour_from, hour_to, period, line_name = line[:5]
            vals = {
                "name": line_name,
                "dayofweek": str(dow),
                "hour_from": hour_from,
                "hour_to": hour_to,
                "day_period": period,
            }
            if len(line) > 5:
                vals["week_type"] = line[5]
            attendances.append(Command.create(vals))
        vals = {"name": name, "tz": tz, "attendance_ids": attendances}
        vals.update(extra)
        return cls.env["resource.calendar"].create(vals)

    @classmethod
    def _make_workcenter(cls, name, calendar, company=None):
        # Залепването за влака (13.10.2026) е изключено в заварените
        # сценарии — те държат празнина пред първия вагон, за да проверят
        # други правила; залепването има свои тестове (test_lanes_head_snap).
        vals = {
            "name": name,
            "resource_calendar_id": calendar.id,
            "crew_snap_head": False,
        }
        if company:
            vals["company_id"] = company.id
        return cls.env["mrp.workcenter"].create(vals)

    def _assert_crew_gantt_context(self, context, expected):
        """Ключовете на модула в контекста на Ганта са точно `expected`:
        очакваните — със стойностите си, останалите ключове на модула — ги
        няма. Чуждите ключове (на други модули) не се гледат."""
        self.assertEqual(
            {key: context[key] for key in CREW_GANTT_CONTEXT_KEYS if key in context},
            expected,
        )

    def _assert_same_crew_gantt_action(self, action, other):
        """Двете действия са едно и също без контекста; в контекста —
        еднакви по ключовете на модула (вж. CREW_GANTT_CONTEXT_KEYS)."""
        self.assertEqual(
            {key: value for key, value in action.items() if key != "context"},
            {key: value for key, value in other.items() if key != "context"},
        )
        self._assert_crew_gantt_context(
            action["context"],
            {
                key: other["context"][key]
                for key in CREW_GANTT_CONTEXT_KEYS
                if key in other["context"]
            },
        )

    def _keys(self, workcenter, day):
        return [b["key"] for b in workcenter._crew_shift_blocks_for_date(day)]


class CrewWorkorderCommon(CrewRosterCommon):
    """Работни поръчки върху центровете от CrewRosterCommon (стъпка 3)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tz = timezone("Europe/Sofia")
        cls.WO = cls.env["mrp.workorder"]
        cls.product = cls.env["product.product"].create(
            {"name": "Crew Bag", "type": "consu"}
        )

    @classmethod
    def _utc(cls, day, hour, minute=0):
        """Местен час (Europe/Sofia) → UTC без tz, както се пази в базата."""
        local = cls.tz.localize(datetime.combine(day, time(hour, minute)))
        return local.astimezone(utc).replace(tzinfo=None)

    def _make_mo(self, deadline=None):
        mo = self.env["mrp.production"].create(
            {"product_id": self.product.id, "product_qty": 1.0}
        )
        if deadline:
            mo.date_deadline = deadline
        return mo

    def _make_wo(
        self, workcenter, start, minutes=60.0, mo=None, crew=None, overlap=False, **extra
    ):
        """Поръчка с начало `start` (UTC без tz) и край start + minutes.

        `overlap=True` — заварено застъпване, както в база преди 1.5.0:
        поръчката се създава без проверката на пистите (M15, Р30). За
        тестовете на наряда/натоварването, чиито поръчки по замисъл се
        застъпват в един център."""
        mo = mo or self._make_mo()
        vals = {
            "name": "Crew operation",
            "workcenter_id": workcenter.id,
            "production_id": mo.id,
            "product_uom_id": self.product.uom_id.id,
            "duration_expected": minutes,
            "date_start": start,
            "date_finished": start + timedelta(minutes=minutes),
        }
        if crew is not None:
            vals["employee_assigned_ids"] = [Command.set(crew.ids)]
        vals.update(extra)
        WorkOrder = self.WO.with_context(crew_lane_defer=True) if overlap else self.WO
        return WorkOrder.create(vals).with_env(self.env)

    def _keep_mo_open(self, mo):
        """Още една незапочната операция на МО-то в ДРУГ център, за да не
        се приключи МО-то с последната си операция.

        Стандартът не затваря МО-то при `button_finish`, но модул отгоре
        може (напр. teolino_shop_station `_teolino_close_if_all_done`).
        Тогава гардът M5.9 („приключена МО не се пипа“) пропуска поръчката
        и тестът проверява друго, а не разделянето. Операцията е в
        `wc_2x12`, за да не влиза в препланирането на `wc_pg`."""
        self._make_wo(self.wc_2x12, self._utc(MONDAY, 8), mo=mo)
        return mo

    def _roster(self, workcenter, day, key, employees):
        return self.Roster.create(
            {
                "workcenter_id": workcenter.id,
                "date": day,
                "shift_key": key,
                "employee_ids": [Command.set(employees.ids)],
            }
        )
