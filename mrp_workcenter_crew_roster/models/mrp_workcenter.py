# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import datetime, time, timedelta

from pytz import timezone, utc

from odoo import api, fields, models
from odoo.addons.resource.models.utils import Intervals

SHIFT_GAP_PARAM = "mrp_workcenter_crew_roster.shift_gap_hours"
CAPACITY_PARAM = "mrp_workcenter_crew_roster.default_capacity_hours"
# Колко дни напред се търси следващата смяна, ако моментът е в празнина
# (две седмици покриват и календар с четна/нечетна седмица).
SLOT_LOOKAHEAD_DAYS = 15
# Периодът на „Преизчисли“ (M7) в дни след днес — като съветника.
CREW_RECOMPUTE_PERIOD_DAYS = 14


def crew_hours_to_key(hours):
    """Превръща час като число (8.5) в ключ на смяна „08:30“."""
    minutes = int(round(hours * 60))
    return "%02d:%02d" % divmod(minutes, 60)


class MrpWorkcenter(models.Model):
    _inherit = "mrp.workcenter"

    crew_roster_count = fields.Integer(
        compute="_compute_crew_roster_count",
        string="Crew Rosters",
    )

    # ------------------------------------------------------------------
    # M1 — блокове на смените (TECH_DESIGN §1 Т1, §3 M1; SPEC Р18, Р28)
    # ------------------------------------------------------------------

    def _crew_shift_gap_hours(self):
        """Прагът на празнината (часове), под който два интервала са в един блок."""
        value = (
            self.env["ir.config_parameter"].sudo().get_param(SHIFT_GAP_PARAM, "1.0")
        )
        try:
            return float(value)
        except (TypeError, ValueError):
            return 1.0

    def _crew_calendar_tz(self):
        """Часовата зона на календара на центъра — по нея е „местният ден“."""
        self.ensure_one()
        calendar = self.resource_calendar_id
        return timezone(calendar.tz or self.env.user.tz or "UTC")

    def _crew_shift_supported(self):
        """Гард: от flexible календар смени не се извличат (в 18 няма
        duration_based — той е от 19)."""
        self.ensure_one()
        calendar = self.resource_calendar_id
        return bool(calendar and not calendar.flexible_hours)

    def _crew_raw_attendances(self, dt_from, dt_to, tz):
        """Работните и обедните интервали на календара, подредени по време.

        Връща списък от речници {start, stop, lunch, midnight}: `stop` е
        нормализиран — 23:59:59.999999 (атендънс до 24:00) става 00:00 на
        следващия ден, а `midnight` пази, че редът е свършвал в 24:00.
        """
        calendar = self.resource_calendar_id
        work = calendar._attendance_intervals_batch(dt_from, dt_to, tz=tz)[False]
        lunch = calendar._attendance_intervals_batch(
            dt_from, dt_to, tz=tz, lunch=True
        )[False]
        items = []
        for intervals, is_lunch in ((work, False), (lunch, True)):
            for start, stop, _att in intervals:
                if stop <= start:
                    continue
                midnight = stop.time() == time.max
                if midnight:
                    stop = tz.localize(
                        datetime.combine(stop.date() + timedelta(days=1), time.min)
                    )
                items.append(
                    {
                        "start": start,
                        "stop": stop,
                        "lunch": is_lunch,
                        "midnight": midnight,
                    }
                )
        items.sort(key=lambda i: (i["start"], i["stop"]))
        return items

    def _crew_continues_block(self, block, prev, item, gap_limit):
        """Правилото от Т1: дали `item` продължава блока, чийто последен ред е `prev`.

        Редът на проверките е важен:
        1. 24:00 → 00:00 на следващия ден — нощна смяна, не прекъсва. Само
           веднъж: блокът трябва да е почнал в деня, в който свършва `prev`,
           и не в 00:00 (иначе денонощен календар „168“ би станал един
           безкраен блок — тогава всеки ден е отделен блок „00:00“);
        2. застъпване — същият блок;
        3. обедна пауза (следващият е обяд или идва след обяд) в същия
           местен ден — не прекъсва, каквато и да е дължината ѝ;
        4. допиране (празнина 0) в един ден — ГРАНИЦА между две смени;
        5. празнина ≤ прага — същият блок; над прага — нов блок.
        """
        if (
            prev["midnight"]
            and item["start"].time() == time.min
            and item["start"].date() == prev["stop"].date()
            and not item["lunch"]
            and block["start"].date() == prev["stop"].date() - timedelta(days=1)
            and block["start"].time() != time.min
        ):
            return True
        gap = item["start"] - block["last_stop"]
        if gap < timedelta(0):
            return True
        if (item["lunch"] or prev["lunch"]) and item["start"].date() == prev[
            "stop"
        ].date():
            return True
        if gap == timedelta(0):
            return False
        return gap <= timedelta(hours=gap_limit)

    def _crew_shift_blocks(self, dt_from, dt_to, compute_leaves=False):
        """Блоковете на смените на центъра с начало в [dt_from, dt_to).

        `dt_from`/`dt_to` са datetime с часова зона. Връща списък от речници
        {key, date, start, stop, intervals, hours}: `key` е местният час на
        началото „HH:MM“, `date` — местната дата на началото, `start`/`stop`
        са с часовата зона на календара, `intervals` — работните интервали
        без паузите (и без отпуските на центъра при `compute_leaves`),
        `hours` — сборът им в часове.

        Не ползва _get_valid_work_intervals: той слива интервалите и губи
        границите между смените.
        """
        self.ensure_one()
        if not self._crew_shift_supported():
            return []
        tz = self._crew_calendar_tz()
        # Разширяваме периода с ден от двете страни, за да видим целия
        # нощен блок, почнал предния ден, и продължението след края.
        pad = timedelta(days=1)
        q_from, q_to = dt_from - pad, dt_to + pad
        items = self._crew_raw_attendances(q_from, q_to, tz)
        gap_limit = self._crew_shift_gap_hours()

        raw_blocks = []
        block = None
        prev = None
        for item in items:
            if block is not None and self._crew_continues_block(
                block, prev, item, gap_limit
            ):
                block["items"].append(item)
                block["last_stop"] = max(block["last_stop"], item["stop"])
            else:
                block = {
                    "start": item["start"],
                    "last_stop": item["stop"],
                    "items": [item],
                }
                raw_blocks.append(block)
            prev = item

        leaves = None
        if compute_leaves:
            calendar = self.resource_calendar_id
            leaves = calendar._leave_intervals_batch(
                q_from, q_to, resources=self.resource_id, tz=tz
            )[self.resource_id.id]

        Attendance = self.env["resource.calendar.attendance"]
        result = []
        for raw in raw_blocks:
            work = [i for i in raw["items"] if not i["lunch"]]
            if not work:
                # Само обедна пауза без работа — не е смяна.
                continue
            start = min(i["start"] for i in work)
            stop = max(i["stop"] for i in work)
            if not (dt_from <= start < dt_to):
                continue
            intervals = Intervals(
                [(i["start"], i["stop"], Attendance) for i in work]
            )
            if leaves:
                intervals = intervals - leaves
            spans = [(s, e) for s, e, _r in intervals]
            hours = sum((e - s).total_seconds() for s, e in spans) / 3600.0
            result.append(
                {
                    "key": start.strftime("%H:%M"),
                    "date": start.date(),
                    "start": start,
                    "stop": stop,
                    "intervals": spans,
                    "hours": hours,
                }
            )
        return result

    def _crew_shift_blocks_for_date(self, day, compute_leaves=False):
        """Блоковете, които ПОЧВАТ в местния ден `day` (по tz на календара)."""
        self.ensure_one()
        if not self._crew_shift_supported():
            return []
        tz = self._crew_calendar_tz()
        dt_from = tz.localize(datetime.combine(day, time.min))
        dt_to = tz.localize(datetime.combine(day + timedelta(days=1), time.min))
        return self._crew_shift_blocks(dt_from, dt_to, compute_leaves=compute_leaves)

    # ------------------------------------------------------------------
    # Т3 — в коя смяна попада моментът; M11 — часове на смяната
    # ------------------------------------------------------------------

    def _crew_slot(self, moment, cache=None):
        """(местен ден, ключ на смяната) за момента `moment` (UTC, без tz).

        Взима се блокът, който съдържа момента (обедът е вътре в блока);
        ако моментът е в празнина — следващият блок (Т3). Нощната смяна,
        почнала предния ден, връща деня на началото си.
        Без календар, от който се извличат смени: местният ден на момента
        и празен ключ.
        `cache` е речник за пакетна работа (ключ — център и местен ден).
        """
        self.ensure_one()
        tz = self._crew_calendar_tz()
        local = utc.localize(moment).astimezone(tz)
        day = local.date()
        if not self._crew_shift_supported():
            return day, False
        if cache is None:
            cache = {}
        cache_key = (self.id, day)
        if cache_key not in cache:
            # От предния ден (нощната смяна) до SLOT_LOOKAHEAD_DAYS напред.
            dt_from = tz.localize(datetime.combine(day - timedelta(days=1), time.min))
            dt_to = tz.localize(
                datetime.combine(day + timedelta(days=SLOT_LOOKAHEAD_DAYS), time.min)
            )
            cache[cache_key] = self._crew_shift_blocks(dt_from, dt_to)
        blocks = cache[cache_key]
        for block in blocks:
            if block["start"] <= local < block["stop"]:
                return block["date"], block["key"]
        for block in blocks:
            if block["start"] > local:
                return block["date"], block["key"]
        return day, False

    def _crew_default_capacity_hours(self):
        """Параметърът `default_capacity_hours` — капацитет без календар."""
        value = self.env["ir.config_parameter"].sudo().get_param(CAPACITY_PARAM, "8")
        try:
            return float(value)
        except (TypeError, ValueError):
            return 8.0

    def _crew_calendar_shift_hours(self, day, key=False, cache=None):
        """Часовете на смяната `key` от календара на центъра за деня (M11).

        Без ключ — сборът от часовете на всички смени, които почват в деня.
        Без календар, от който се извличат смени, или при 0 часа —
        параметърът `default_capacity_hours`. Календарът на служителя
        НЕ се ползва (Р27).
        """
        self.ensure_one()
        if not self._crew_shift_supported():
            return self._crew_default_capacity_hours()
        if cache is None:
            cache = {}
        cache_key = (self.id, day)
        if cache_key not in cache:
            cache[cache_key] = self._crew_shift_blocks_for_date(day)
        blocks = cache[cache_key]
        if key:
            blocks = [b for b in blocks if b["key"] == key]
        hours = sum(b["hours"] for b in blocks)
        return hours or self._crew_default_capacity_hours()

    # ------------------------------------------------------------------
    # M6 — помощни за двигателя на препланирането
    # ------------------------------------------------------------------

    def _crew_local_today(self):
        """Днешният местен ден по tz на календара на центъра."""
        self.ensure_one()
        now = utc.localize(fields.Datetime.now())
        return now.astimezone(self._crew_calendar_tz()).date()

    def _crew_period_bounds(self, date_from, date_to):
        """(T0, край) на периода [date_from, date_to] — UTC без tz.

        T0 е 00:00 местно на `date_from`, краят — 00:00 местно на деня след
        `date_to` (tz на календара на центъра)."""
        self.ensure_one()
        tz = self._crew_calendar_tz()

        def to_utc(day):
            local = tz.localize(datetime.combine(day, time.min))
            return local.astimezone(utc).replace(tzinfo=None)

        return to_utc(date_from), to_utc(date_to + timedelta(days=1))

    def _crew_closed_shift_slots(self, date_from, date_to):
        """M6.7: затворените смени в [date_from, date_to] — блоковете без
        наряд, (начало, край) в UTC без tz.

        Р25: докато центърът няма НИТО ЕДИН наряд в периода, смените му са
        отворени — нищо не е затворено."""
        self.ensure_one()
        rosters = (
            self.env["mrp.workcenter.roster"]
            .sudo()
            .search(
                [
                    ("workcenter_id", "=", self.id),
                    ("date", ">=", date_from),
                    ("date", "<=", date_to),
                ]
            )
        )
        if not rosters:
            return []
        open_shifts = {(r.date, r.shift_key) for r in rosters}
        tz = self._crew_calendar_tz()
        blocks = self._crew_shift_blocks(
            tz.localize(datetime.combine(date_from, time.min)),
            tz.localize(datetime.combine(date_to + timedelta(days=1), time.min)),
        )
        return [
            (
                block["start"].astimezone(utc).replace(tzinfo=None),
                block["stop"].astimezone(utc).replace(tzinfo=None),
            )
            for block in blocks
            if (block["date"], block["key"]) not in open_shifts
        ]

    # ------------------------------------------------------------------
    # M7 — „Преизчисли“ (SPEC §6.4)
    # ------------------------------------------------------------------

    def _crew_recompute(self, day=None, respect_roster=False):
        """M7 за центъра; връща партидата.

        1. M6 с `only_stale=True`, от днес, без алтернативи,
           `respect_roster=False` по подразбиране (Р25), source='recompute';
        2. нарядът към отворените поръчки на центъра от днес;
        3. ново разделяне (M5) на приключените поръчки за избрания ден
           (`day`, по подразбиране днес) с гардовете от M5.9.
        """
        self.ensure_one()
        today = self._crew_local_today()
        day = fields.Date.to_date(day) or today
        Batch = self.env["mrp.workcenter.replan.batch"]
        params = dict(
            Batch._crew_default_params(),
            workcenter_ids=self.ids,
            date_from=today,
            date_to=today + timedelta(days=CREW_RECOMPUTE_PERIOD_DAYS),
            use_alternatives=False,
            respect_roster=respect_roster,
            only_stale=True,
        )
        batch = Batch._crew_run(params, "recompute")

        WorkOrder = self.env["mrp.workorder"]
        WorkOrder.search(
            [
                ("workcenter_id", "=", self.id),
                ("state", "not in", ("done", "cancel")),
                ("crew_date", ">=", today),
            ]
        )._crew_apply()

        day_start, day_stop = self._crew_period_bounds(day, day)
        finished = WorkOrder.search(
            [
                ("workcenter_id", "=", self.id),
                ("state", "=", "done"),
                "|",
                ("crew_date", "=", day),
                "&",
                ("date_finished", ">=", day_start),
                ("date_finished", "<", day_stop),
            ]
        )
        batch._crew_add_split_report(finished._crew_split_time(recompute=True))
        return batch

    # ------------------------------------------------------------------
    # Ганта „Планирай център“ (TECH_DESIGN §4)
    # ------------------------------------------------------------------

    def _crew_names_label(self, start, stop):
        """{център: текст за етикета му в Ганта} за периода [start, stop)
        (№146 на Теолино, ADR-0071; Клаудио 12.10).

        Бригадата е за ДЕН, а етикетът — за целия видим период. Затова:
        една и съща бригада във всички дни с наряд ⇒ имената; сменя се ⇒
        „различни бригади“ (по дни се вижда на лентата); без наряд ⇒ нищо.
        """
        start = fields.Datetime.to_datetime(start)
        stop = fields.Datetime.to_datetime(stop)
        if not (self and start and stop and start < stop):
            return {}
        result = {}
        Roster = self.env["mrp.workcenter.roster"]
        for workcenter in self:
            tz = workcenter._crew_calendar_tz()
            day_from = utc.localize(start).astimezone(tz).date()
            day_to = utc.localize(stop - timedelta(seconds=1)).astimezone(tz).date()
            rosters = Roster.search(
                [
                    ("workcenter_id", "=", workcenter.id),
                    ("date", ">=", day_from),
                    ("date", "<=", day_to),
                ]
            )
            crews = {frozenset(r.employee_ids.ids) for r in rosters}
            if len(crews) == 1:
                result[workcenter.id] = ", ".join(
                    rosters[:1].employee_ids.sorted("name").mapped("name")
                )
            elif crews:
                result[workcenter.id] = self.env._("different crews")
        return result

    def _compute_crew_roster_count(self):
        counts = dict(
            self.env["mrp.workcenter.roster"]._read_group(
                [("workcenter_id", "in", self.ids)], ["workcenter_id"], ["__count"]
            )
        )
        for workcenter in self:
            workcenter.crew_roster_count = counts.get(workcenter, 0)

    def action_crew_rosters(self):
        """Нарядите на центъра — от картата му (№146 на Теолино).

        Както „Plan“: `crew_workcenter_id` за бутоните на списъка и филтър,
        който може да се махне; без `default_*`.
        """
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "mrp_workcenter_crew_roster.mrp_workcenter_roster_action"
        )
        action["context"] = {
            "search_default_workcenter_id": self.id,
            "crew_workcenter_id": self.id,
        }
        return action

    def action_crew_plan_gantt(self):
        """Нашият Гант за центъра: smart бутонът „Plan“ и изборът на център.

        Контекстът носи само `search_default_workcenter_id` (филтър, който
        планиращият може да махне) и `crew_workcenter_id` (бутонът
        „Recompute“). Без `default_*` (Ф3): префиксът изтича към всяко
        create на модел с поле `workcenter_id`.
        """
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_action"
        )
        action["context"] = {
            "search_default_workcenter_id": self.id,
            "crew_workcenter_id": self.id,
        }
        action["domain"] = self._crew_short_term_domain()
        action["name"] = self.env._("Plan: %(wc)s", wc=self.display_name)
        action["target"] = "current"
        return action

    @api.model
    def _crew_short_term_domain(self):
        """Краткосрочният план — само поръчките на ПЛАНИРАНИ МО (бутонът
        „Планирай“ в МО или в POC), вкл. започнатите (Росен 14.10.2026)."""
        return [("production_id.is_planned", "=", True)]

    @api.model
    def _crew_long_term_domain(self):
        """Дългосрочният план — всички поръчки без започнатите,
        приключените и отменените (Росен 14.10.2026)."""
        return [("state", "not in", ("progress", "done", "cancel"))]

    @api.model
    def action_crew_plan_long_term(self):
        """„Дългосрочно планиране“ (Росен 14.10.2026): нашият Гант за ВСИЧКИ
        центрове на разрешените фирми, без избора на център. Същото като
        краткосрочния план — писти, стрелка, влак, залепване, „Rearrange
        Plan“ — но изгледът е върху „началото/края в плана“, затова вижда и
        непланираните (на датите на МО-то). `crew_workcenter_ids` носи всички
        центрове (празните също се показват, Р40)."""
        workcenters = self.search([("company_id", "in", self.env.companies.ids + [False])])
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_action"
        )
        view = self.env.ref("mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_longterm_view")
        action["view_id"] = view.id
        action["views"] = [(view.id, "gantt"), (False, "list"), (False, "form")]
        action["domain"] = self._crew_long_term_domain()
        action["context"] = {"crew_workcenter_ids": workcenters.ids}
        action["name"] = action["display_name"] = self.env._("Long-Term Planning")
        action["target"] = "current"
        # Без пътя на краткосрочния план: иначе клиентът взима неговото име и
        # адрес (заглавието ставаше „Планирай център“).
        action.pop("path", None)
        return action
