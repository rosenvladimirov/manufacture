# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from collections import defaultdict
from datetime import datetime, timedelta

from pytz import timezone, utc

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL, float_compare
from odoo.tools.sql import column_exists, create_column

# Полетата, чиято промяна мести поръчката в друг ден/смяна/център (M2).
# В 19 _plan_workorder пише workcenter_id и leave_id, а датите са
# изчисляеми от leave_id.
CREW_TRIGGER_FIELDS = {"workcenter_id", "date_start", "date_finished", "leave_id"}
# Гардът срещу рекурсия: собственият запис на екипа не прилага наряда отново.
CREW_APPLYING = "crew_roster_applying"
# Колоните, които при инсталация се създават празни (виж _auto_init).
CREW_LAZY_COLUMNS = (
    ("crew_date", "date"),
    ("crew_shift_key", "varchar"),
    ("minutes_per_person", "numeric"),
)


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    crew_date = fields.Date(
        compute="_compute_crew_slot",
        store=True,
        index=True,
        string="Crew Day",
        help="Local day of the shift in which the work order starts, in the "
        "time zone of the work center's working schedule. A night shift "
        "belongs to the day on which it starts.",
    )
    crew_shift_key = fields.Char(
        compute="_compute_crew_slot",
        store=True,
        index=True,
        string="Crew Shift",
        help="Start time of the shift of the work center in which the work "
        "order starts, e.g. 08:00.",
    )
    roster_id = fields.Many2one(
        "mrp.workcenter.roster",
        compute="_compute_roster_id",
        string="Crew Roster",
        help="The crew roster of the work center for the day and shift of the "
        "work order.",
    )
    deadline = fields.Datetime(
        related="production_id.date_deadline",
        string="Deadline",
    )
    is_late = fields.Boolean(
        compute="_compute_is_late",
        search="_search_is_late",
        string="Late",
        help="The work order is open and its planned end is after the "
        "deadline of the manufacturing order, or the deadline has passed.",
    )
    minutes_per_person = fields.Float(
        compute="_compute_minutes_per_person",
        store=True,
        digits=(16, 2),
        aggregator="sum",
        string="Minutes per Person",
        help="Expected duration divided by the number of people in the crew "
        "(0 when the crew is empty).",
    )
    is_overloaded = fields.Boolean(
        compute="_compute_overload",
        string="Overloaded",
        help="Somebody in the crew has more planned work on the day than the "
        "hours of their shifts.",
    )
    overload_message = fields.Text(
        compute="_compute_overload",
        string="Overload",
    )
    crew_names = fields.Char(
        compute="_compute_crew_names",
        string="Crew Members",
        help="The names of the people in the crew of the work order.",
    )
    crew_partner_id = fields.Many2one(
        "res.partner",
        compute="_compute_crew_partner_id",
        string="Replanning Customer",
        help="The customer of the manufacturing order (from the sales order), "
        "used to order and filter the replanning.",
    )

    # ------------------------------------------------------------------
    # Инсталация: колоните празни, попълват се само незавършените
    # ------------------------------------------------------------------

    def _auto_init(self):
        """Колоните на изчисляемите полета се създават празни ПРЕДИ super():
        така ORM-ът не ги изчислява за всички поръчки (и приключените).
        Незавършените се попълват от post_init_hook / миграцията.
        """
        cr = self.env.cr
        for column, column_type in CREW_LAZY_COLUMNS:
            if not column_exists(cr, self._table, column):
                create_column(cr, self._table, column, column_type)
        return super()._auto_init()

    @api.model
    def _crew_init_open_workorders(self):
        """Изчислява полетата на наряда само за незавършените поръчки."""
        workorders = self.with_context(active_test=False).search(
            [("state", "not in", ("done", "cancel"))]
        )
        for column, _column_type in CREW_LAZY_COLUMNS:
            self.env.add_to_compute(self._fields[column], workorders)
        workorders.flush_recordset()
        return workorders

    # ------------------------------------------------------------------
    # Изчисляеми
    # ------------------------------------------------------------------

    def _crew_closed_slots(self):
        """Записаните (ден, смяна) на приключените/отказаните поръчки.

        Те запазват старата стойност (TECH_DESIGN §2): четем я от базата,
        защото в изчислението кешът вече е за новата стойност.
        """
        closed = self.filtered(
            lambda wo: wo._origin.id and wo.state in ("done", "cancel")
        )
        if not closed:
            return {}
        self.env.cr.execute(
            SQL(
                "SELECT id, crew_date, crew_shift_key FROM mrp_workorder "
                "WHERE id IN %s",
                tuple(closed._origin.ids),
            )
        )
        return {row[0]: (row[1], row[2]) for row in self.env.cr.fetchall()}

    @api.depends("date_start", "workcenter_id", "workcenter_id.resource_calendar_id")
    def _compute_crew_slot(self):
        closed = self._crew_closed_slots()
        cache = {}
        for wo in self:
            if wo._origin.id in closed:
                wo.crew_date, wo.crew_shift_key = closed[wo._origin.id]
                continue
            if not (wo.date_start and wo.workcenter_id):
                wo.crew_date = False
                wo.crew_shift_key = False
                continue
            day, key = wo.workcenter_id._crew_slot(wo.date_start, cache)
            wo.crew_date = day
            wo.crew_shift_key = key or False

    @api.depends("workcenter_id", "crew_date", "crew_shift_key")
    def _compute_roster_id(self):
        planned = self.filtered(lambda wo: wo.workcenter_id and wo.crew_date)
        rosters = {}
        if planned:
            found = self.env["mrp.workcenter.roster"].search(
                [
                    ("workcenter_id", "in", planned.workcenter_id.ids),
                    ("date", "in", list(set(planned.mapped("crew_date")))),
                ]
            )
            rosters = {(r.workcenter_id.id, r.date, r.shift_key): r for r in found}
        for wo in self:
            wo.roster_id = rosters.get(
                (wo.workcenter_id.id, wo.crew_date, wo.crew_shift_key), False
            )

    @api.depends("state", "date_finished", "production_id.date_deadline")
    def _compute_is_late(self):
        now = fields.Datetime.now()
        for wo in self:
            deadline = wo.production_id.date_deadline
            wo.is_late = bool(
                wo.state not in ("done", "cancel")
                and deadline
                and (
                    (wo.date_finished and wo.date_finished > deadline)
                    or deadline < now
                )
            )

    def _search_is_late(self, operator, value):
        """`is_late` сравнява две полета (край и срок) — домейн не може,
        затова е SQL подзаявка (№10)."""
        # В 18 операторът идва като `=`/`!=` с булева стойност (в 19 —
        # нормализиран до `in`); свеждаме до „искаме закъснели или не“.
        if operator in ("=", "!="):
            values = {bool(value)} if operator == "=" else {not value}
        elif operator in ("in", "not in"):
            values = {bool(v) for v in value}
            if operator == "not in":
                values = {True, False} - values
        else:
            raise UserError(self.env._("Unsupported search on Late: %s", operator))
        want_true, want_false = True in values, False in values
        if want_true and want_false:
            return [(1, "=", 1)]
        if not (want_true or want_false):
            return [(0, "=", 1)]
        self.env["mrp.workorder"].flush_model(["state", "date_finished", "production_id"])
        self.env["mrp.production"].flush_model(["date_deadline"])
        late = SQL(
            "(SELECT wo.id FROM mrp_workorder wo "
            "JOIN mrp_production mo ON mo.id = wo.production_id "
            "WHERE wo.state NOT IN ('done', 'cancel') "
            "AND mo.date_deadline IS NOT NULL "
            "AND (wo.date_finished > mo.date_deadline OR mo.date_deadline < %s))",
            fields.Datetime.now(),
        )
        return [("id", "in" if want_true else "not in", late)]

    @api.depends("duration_expected", "employee_assigned_ids")
    def _compute_minutes_per_person(self):
        for wo in self:
            crew = len(wo.employee_assigned_ids)
            wo.minutes_per_person = wo.duration_expected / crew if crew else 0.0

    @api.depends("employee_assigned_ids")
    def _compute_crew_names(self):
        """Имената на екипа за popover-а на Ганта: там m2m идва само като id-та."""
        for wo in self:
            wo.crew_names = ", ".join(wo.employee_assigned_ids.mapped("name")) or False

    @api.depends(
        "state", "crew_date", "crew_shift_key", "employee_assigned_ids", "minutes_per_person"
    )
    def _compute_overload(self):
        """M11: за всеки човек от екипа — сборът от минутите на човек по
        отворените поръчки на всички центрове за деня срещу капацитета му."""
        todo = self.filtered(
            lambda wo: wo.state not in ("done", "cancel")
            and wo.crew_date
            and wo.employee_assigned_ids
        )
        (self - todo).update({"is_overloaded": False, "overload_message": False})
        if not todo:
            return
        load, capacity = self._crew_load_and_capacity(
            todo.employee_assigned_ids, set(todo.mapped("crew_date"))
        )
        for wo in todo:
            messages = []
            for employee in wo.employee_assigned_ids:
                key = (employee.id, wo.crew_date)
                minutes = load.get(key, 0.0)
                hours = capacity.get(key, 0.0)
                if float_compare(minutes, hours * 60.0, precision_digits=2) > 0:
                    messages.append(
                        self.env._(
                            "%(employee)s: %(load).2f h planned, capacity %(capacity).2f h",
                            employee=employee.name,
                            load=minutes / 60.0,
                            capacity=hours,
                        )
                    )
            wo.is_overloaded = bool(messages)
            wo.overload_message = "\n".join(messages) or False

    # ------------------------------------------------------------------
    # M11 — натоварване и капацитет на човек (в часове)
    # ------------------------------------------------------------------

    @api.model
    def _crew_load_and_capacity(self, employees, days):
        """Натоварване (минути) и капацитет (часове) за всеки (служител, ден).

        Натоварването е сборът от `minutes_per_person` по ОТВОРЕНИТЕ поръчки
        на всички центрове с този `crew_date`.

        Капацитетът (Р27):
        - сборът от часовете на смените от нарядите за деня, в които е
          човекът (смяната е блок от календара на центъра);
        - без наряд за деня — часовете на смените на поръчките му от
          календара на центъра им (всяка смяна веднъж); без календар —
          параметърът `default_capacity_hours`;
        - без наряд и без поръчки — 0.
        Календарът на служителя НЕ се ползва.
        """
        days = list(days)
        load = defaultdict(float)
        capacity = defaultdict(float)
        if not employees or not days:
            return load, capacity
        employee_ids = set(employees.ids)
        shifts = defaultdict(set)
        groups = self.env["mrp.workorder"]._read_group(
            [
                ("state", "not in", ("done", "cancel")),
                ("crew_date", "in", days),
                ("employee_assigned_ids", "in", list(employee_ids)),
            ],
            ["employee_assigned_ids", "crew_date:day", "workcenter_id", "crew_shift_key"],
            ["minutes_per_person:sum"],
        )
        for employee, day, workcenter, shift_key, minutes in groups:
            if employee.id not in employee_ids:
                continue
            day = fields.Date.to_date(day)
            load[(employee.id, day)] += minutes or 0.0
            shifts[(employee.id, day)].add((workcenter, shift_key))

        rosters = self.env["mrp.workcenter.roster"].search(
            [("date", "in", days), ("employee_ids", "in", list(employee_ids))]
        )
        roster_hours = defaultdict(float)
        for roster in rosters:
            for employee in roster.employee_ids:
                if employee.id in employee_ids:
                    roster_hours[(employee.id, roster.date)] += roster.shift_hours

        cache = {}
        for employee_id in employee_ids:
            for day in days:
                key = (employee_id, day)
                if key in roster_hours:
                    capacity[key] = roster_hours[key]
                elif shifts.get(key):
                    capacity[key] = sum(
                        workcenter._crew_calendar_shift_hours(day, shift_key, cache)
                        for workcenter, shift_key in shifts[key]
                        if workcenter
                    )
        return load, capacity

    @api.model
    def _gantt_progress_bar(self, field, res_ids, start, stop):
        """Лентата за натоварване по служител (M11) — в ЧАСОВЕ, като
        стандартната за центъра. EE вдига NotImplementedError за всичко
        освен `workcenter_id`, затова нашето поле се обработва преди super()."""
        if field == "employee_assigned_ids":
            return dict(
                self._crew_gantt_progress_bar_employees(res_ids, start, stop),
                warning=self.env._(
                    "This employee has no shift in this period. Work hours:"
                ),
            )
        return super()._gantt_progress_bar(field, res_ids, start, stop)

    @api.model
    def _crew_gantt_progress_bar_employees(self, res_ids, start, stop):
        self.env["mrp.workorder"].check_access("read")
        start, stop = utc.localize(start), utc.localize(stop)
        # Като EE: миналото не се брои.
        today = datetime.now(utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = max(start, today)
        employees = self.env["hr.employee"].browse(
            [res_id for res_id in res_ids if res_id]
        ).exists()
        tz = timezone(
            self.env.user.tz or self.env.company.resource_calendar_id.tz or "UTC"
        )
        day_from = start.astimezone(tz).date()
        day_to = (stop.astimezone(tz) - timedelta(microseconds=1)).date()
        days = []
        day = day_from
        while day <= day_to:
            days.append(day)
            day += timedelta(days=1)
        load, capacity = self._crew_load_and_capacity(employees, days)
        return {
            employee.id: {
                "value": sum(load.get((employee.id, d), 0.0) for d in days) / 60.0,
                "max_value": sum(capacity.get((employee.id, d), 0.0) for d in days),
            }
            for employee in employees
        }

    # ------------------------------------------------------------------
    # M2 — прилагане на наряда към екипа
    # ------------------------------------------------------------------

    def _crew_apply(self, force=False):
        """Екипът (`employee_assigned_ids`) = нарядът на (център, ден, смяна).

        - Р25: център без нито един наряд за деня → екипът НЕ се пипа
          (смените му са отворени);
        - има наряд за деня, но не и за смяната → празен екип;
        - приключени/отказани не се пипат, освен при `force`;
        - записът е под контекста CREW_APPLYING (защита от рекурсия) и само
          когато екипът наистина се сменя.
        """
        workorders = self if force else self.filtered(
            lambda wo: wo.state not in ("done", "cancel")
        )
        workorders = workorders.filtered(lambda wo: wo.workcenter_id and wo.crew_date)
        if not workorders:
            return
        rosters = (
            self.env["mrp.workcenter.roster"]
            .sudo()
            .search(
                [
                    ("workcenter_id", "in", workorders.workcenter_id.ids),
                    ("date", "in", list(set(workorders.mapped("crew_date")))),
                ]
            )
        )
        by_day = defaultdict(dict)
        for roster in rosters:
            by_day[(roster.workcenter_id.id, roster.date)][roster.shift_key] = (
                roster.employee_ids.ids
            )
        targets = defaultdict(lambda: self.env["mrp.workorder"])
        for wo in workorders:
            shifts = by_day.get((wo.workcenter_id.id, wo.crew_date))
            if not shifts:
                # Р25: центърът няма наряд за деня — смените са отворени.
                continue
            crew = tuple(sorted(shifts.get(wo.crew_shift_key) or []))
            if crew != tuple(sorted(wo.employee_assigned_ids.ids)):
                targets[crew] |= wo
        for crew, group in targets.items():
            group.with_context(**{CREW_APPLYING: True}).write(
                {"employee_assigned_ids": [Command.set(list(crew))]}
            )

    @api.model_create_multi
    def create(self, vals_list):
        workorders = super().create(vals_list)
        if not self.env.context.get(CREW_APPLYING):
            workorders._crew_apply()
        return workorders

    def write(self, vals):
        # M10 отпада от 1.5.0 (Р12 изменено): гардът на влаченето е M16 в
        # mrp_workorder_lanes.py — друг център е позволен при свободна писта.
        res = super().write(vals)
        if not self.env.context.get(CREW_APPLYING) and CREW_TRIGGER_FIELDS.intersection(
            vals
        ):
            self._crew_apply()
        return res

    def button_start(self, *args, **kwargs):
        """Р5 (M3): EE добавя стартиращия в екипа; връщаме екипа към наряда.

        Редът с времето и `employee_ids` остават — отчитането не се блокира.
        При център без наряд за деня (Р25) стартиращият остава в екипа.
        """
        res = super().button_start(*args, **kwargs)
        self._crew_apply()
        return res

    # ------------------------------------------------------------------
    # M12 — клиентът; M6 — помощни и точка за разширение (§5)
    # ------------------------------------------------------------------

    def _compute_crew_partner_id(self):
        for wo in self:
            wo.crew_partner_id = wo._crew_partner()

    def _crew_partner(self):
        """M12: клиентът на МО — под sudo (MRP User без Продажби не чете
        sale.order). Меки зависимости, проверка през `_fields`:
        1. `production_config_id.sale_order_id.partner_id`;
        2. `sale_line_id.order_id.partner_id` (sale_mrp);
        3. веригата на произхода `reference_ids.sale_ids`.
        Без клиент — празен запис (накрая при подредба по клиент, И7)."""
        self.ensure_one()
        Partner = self.env["res.partner"]
        production = self.sudo().production_id
        if not production:
            return Partner
        partner = Partner.sudo()
        if "production_config_id" in production._fields:
            config = production.production_config_id
            if config and "sale_order_id" in config._fields:
                partner = config.sale_order_id.partner_id
        if not partner and "sale_line_id" in production._fields:
            partner = production.sale_line_id.order_id.partner_id
        if not partner and "reference_ids" in production._fields:
            references = production.reference_ids
            if "sale_ids" in references._fields:
                partner = references.sale_ids[:1].partner_id
        return Partner.browse(partner.ids[:1])

    def _crew_started_successor(self):
        """M6.3: има ли наследник (пряк или по веригата) в progress/done —
        тогава поръчката не се мести."""
        self.ensure_one()
        seen = set()
        stack = list(self.needed_by_workorder_ids)
        while stack:
            workorder = stack.pop()
            if workorder.id in seen:
                continue
            seen.add(workorder.id)
            if workorder.state in ("progress", "done"):
                return True
            stack.extend(workorder.needed_by_workorder_ids)
        return False

    def _crew_dependency_gap(self, predecessor):
        """Точка за разширение (18.0.1.12.0, Росен 08.11 — вариант „б“): отстъпът
        между края на предшественика и началото на тази поръчка, когато
        избутването минава по зависимост. По подразбиране — няма."""
        self.ensure_one()
        return timedelta(0)

    def _crew_earliest_after(self, predecessor):
        """Кога тази поръчка може да почне след `predecessor` — или False.

        Пред `date_finished` стои СЪСТОЯНИЕТО: полето е факт само при
        приключена поръчка, иначе е прогноза. Затова не са основа за
        планиране:
        · предшественик без дата (непланиран) — не се знае кога свършва;
        · незавършен предшественик с дата в МИНАЛОТО — прогнозата е
          остаряла (Любо, 16.11: „неприключена операция с минала дата се
          брои за приключена“).
        False значи „не нареждай след този“; викащият отказва поръчката и я
        описва в отчета.

        Решението за втория случай е на Росен: ако трябва да се нарежда по
        „сега + оставащото“ вместо отказ, смяната е САМО тук.
        """
        self.ensure_one()
        if not predecessor.date_finished:
            return False
        if (predecessor.state != "done"
                and predecessor.date_finished <= fields.Datetime.now()):
            return False
        return predecessor.date_finished + self._crew_dependency_gap(predecessor)

    def _crew_replan_earliest(self, params=None):
        """Точка за разширение (TECH_DESIGN §5): най-ранното начало на
        поръчката при препланиране освен „сега“ и предшествениците
        (напр. меки ребра между модули). По подразбиране — няма (False)."""
        self.ensure_one()
        return False
