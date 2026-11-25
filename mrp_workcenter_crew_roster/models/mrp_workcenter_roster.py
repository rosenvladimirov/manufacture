# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import timedelta

from pytz import utc

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.sql import table_exists

from .mrp_workcenter import crew_hours_to_key

# Полетата на наряда, чиято промяна сменя екипа на поръчките (M2).
CREW_ROSTER_FIELDS = {"employee_ids", "date", "shift_key", "workcenter_id"}
# Най-дългият период „от–до“ за едно въвеждане (№146 на Теолино).
CREW_PERIOD_MAX_DAYS = 92


class MrpWorkcenterRoster(models.Model):
    """Нарядът: кои хора работят на център в дадена смяна на даден ден.

    Смяната не е модел — тя е блок от работния календар на центъра,
    разпознат по часа на началото си (`shift_key`, напр. „08:00“).
    """

    _name = "mrp.workcenter.roster"
    # В 18 няма hr.mixin (дошъл в 19): записът в m2m към hr.employee не иска
    # право за четене на служителите, затова наследяване не е нужно.
    _description = "Work Center Crew Roster"
    _order = "date desc, workcenter_id, shift_key"
    _check_company_auto = True

    workcenter_id = fields.Many2one(
        "mrp.workcenter",
        string="Work Center",
        required=True,
        index=True,
        check_company=True,
        ondelete="cascade",
        default=lambda self: self._default_workcenter_id(),
    )
    company_id = fields.Many2one(
        related="workcenter_id.company_id",
        store=True,
        index=True,
        precompute=True,
    )
    date = fields.Date(
        required=True,
        index=True,
        default=fields.Date.context_today,
        help="Local day (in the time zone of the work center's working "
        "schedule) on which the shift starts.",
    )
    shift_key = fields.Selection(
        selection="_selection_shift_key",
        string="Shift",
        required=True,
        index=True,
        help="Start time of the shift in the working schedule of the work "
        "center, e.g. 08:00. The shift is a continuous block of working "
        "hours; the lunch break does not split it.",
    )
    calendar_id = fields.Many2one(
        related="workcenter_id.resource_calendar_id",
        string="Working Schedule",
    )
    shift_start = fields.Datetime(
        compute="_compute_shift_bounds",
        store=True,
        string="Shift Start",
    )
    shift_stop = fields.Datetime(
        compute="_compute_shift_bounds",
        store=True,
        string="Shift End",
    )
    shift_hours = fields.Float(
        compute="_compute_shift_bounds",
        store=True,
        string="Shift Hours",
        help="Working hours of the shift without the breaks.",
    )
    shift_missing = fields.Boolean(
        compute="_compute_shift_bounds",
        store=True,
        string="Shift Missing",
        help="The working schedule of the work center no longer has a shift "
        "starting at this time on this day.",
    )
    employee_ids = fields.Many2many(
        "hr.employee",
        "mrp_workcenter_roster_employee_rel",
        "roster_id",
        "employee_id",
        string="Crew",
        check_company=True,
    )
    crew_size = fields.Integer(
        compute="_compute_crew_size",
        store=True,
        string="Crew Size",
    )
    note = fields.Text()
    # Само за въвеждане (№146 на Теолино, ADR-0071 — удобството на наряда на
    # монтажа): „До“ разгръща реда в един наряд на всеки работен ден на
    # центъра със същата смяна. Всичко след това си остава по ден и смяна;
    # колоната е винаги празна в базата — стойността се изразходва при запис.
    date_to = fields.Date(
        string="Until",
        help="Fill to book the same crew for a period: a crew roster is made "
        "for every working day of the work center with the same shift, up to "
        "this date. Days that already have a crew roster for the shift are "
        "left as they are.",
    )
    # Изборът на хора — позволените в центъра (стандартното поле на Odoo);
    # център без позволени хора не ограничава избора.
    allowed_employee_ids = fields.Many2many(
        related="workcenter_id.employee_ids",
        string="Allowed Employees",
    )

    _sql_constraints = [
        (
            "unique_shift",
            "unique(workcenter_id, date, shift_key)",
            "There is already a crew roster for this work center, day and shift.",
        ),
    ]

    # ------------------------------------------------------------------
    # Подразбиращи се стойности и избор
    # ------------------------------------------------------------------

    @api.model
    def _default_workcenter_id(self):
        """Центърът идва от контекста `crew_workcenter_id` (Р12, №5)."""
        return self.env.context.get("crew_workcenter_id") or False

    @api.model
    def _selection_shift_key(self):
        """Изборът на смяна: всички часове на начало на работни редове в
        календарите на центровете плюс вече ползваните ключове.

        Това е надмножество на началата на блоковете (всяко начало на блок е
        начало на някой ред); точната проверка е в _check_shift_key.
        """
        keys = set()
        calendars = (
            self.env["mrp.workcenter"]
            .sudo()
            .with_context(active_test=False)
            .search([])
            .resource_calendar_id
        )
        if calendars:
            attendances = (
                self.env["resource.calendar.attendance"]
                .sudo()
                .search(
                    [
                        ("calendar_id", "in", calendars.ids),
                        ("display_type", "=", False),
                        ("day_period", "!=", "lunch"),
                    ]
                )
            )
            keys.update(crew_hours_to_key(att.hour_from) for att in attendances)
        if table_exists(self.env.cr, self._table):
            # Ключовете на съществуващите наряди остават валидни дори ако
            # календарът е редактиран (shift_missing ги показва).
            self.env.cr.execute(
                "SELECT DISTINCT shift_key FROM mrp_workcenter_roster "
                "WHERE shift_key IS NOT NULL"
            )
            keys.update(row[0] for row in self.env.cr.fetchall())
        return [(key, key) for key in sorted(keys)]

    # ------------------------------------------------------------------
    # Изчисляеми
    # ------------------------------------------------------------------

    @api.depends(
        "workcenter_id",
        "date",
        "shift_key",
        "workcenter_id.resource_calendar_id",
        "workcenter_id.resource_calendar_id.tz",
        "workcenter_id.resource_calendar_id.attendance_ids",
        "workcenter_id.resource_calendar_id.attendance_ids.hour_from",
        "workcenter_id.resource_calendar_id.attendance_ids.hour_to",
        "workcenter_id.resource_calendar_id.attendance_ids.day_period",
        "workcenter_id.resource_calendar_id.attendance_ids.dayofweek",
        "workcenter_id.resource_calendar_id.attendance_ids.week_type",
    )
    def _compute_shift_bounds(self):
        for roster in self:
            block = roster._crew_block()
            if block:
                roster.shift_start = block["start"].astimezone(utc).replace(
                    tzinfo=None
                )
                roster.shift_stop = block["stop"].astimezone(utc).replace(
                    tzinfo=None
                )
                roster.shift_hours = block["hours"]
                roster.shift_missing = False
            else:
                roster.shift_start = False
                roster.shift_stop = False
                roster.shift_hours = 0.0
                roster.shift_missing = bool(
                    roster.workcenter_id and roster.date and roster.shift_key
                )

    @api.depends("employee_ids")
    def _compute_crew_size(self):
        for roster in self:
            roster.crew_size = len(roster.employee_ids)

    @api.depends("workcenter_id", "date", "shift_start", "shift_stop", "shift_key")
    def _compute_display_name(self):
        for roster in self:
            parts = [roster.workcenter_id.display_name or ""]
            if roster.date:
                parts.append(fields.Date.to_string(roster.date))
            block = roster._crew_block() if roster.shift_key else None
            if block:
                parts.append(
                    "%s–%s"
                    % (block["start"].strftime("%H:%M"), block["stop"].strftime("%H:%M"))
                )
            elif roster.shift_key:
                parts.append(roster.shift_key)
            roster.display_name = " · ".join(p for p in parts if p)

    def _crew_block(self):
        """Блокът от календара на центъра, който отговаря на наряда, или None."""
        self.ensure_one()
        if not (self.workcenter_id and self.date and self.shift_key):
            return None
        for block in self.workcenter_id._crew_shift_blocks_for_date(self.date):
            if block["key"] == self.shift_key:
                return block
        return None

    # ------------------------------------------------------------------
    # Onchange и ограничения
    # ------------------------------------------------------------------

    @api.onchange("workcenter_id", "date")
    def _onchange_crew_shift(self):
        """Ако денят на центъра има точно една смяна — попълва я сама."""
        if not (self.workcenter_id and self.date):
            return
        keys = [
            b["key"]
            for b in self.workcenter_id._crew_shift_blocks_for_date(self.date)
        ]
        if len(keys) == 1:
            self.shift_key = keys[0]
        elif self.shift_key not in keys:
            self.shift_key = False

    @api.constrains("employee_ids")
    def _check_employee_ids(self):
        for roster in self:
            if not roster.employee_ids:
                raise ValidationError(
                    self.env._(
                        "The crew roster %(roster)s must have at least one employee.",
                        roster=roster.display_name,
                    )
                )

    @api.constrains("shift_key", "date", "workcenter_id")
    def _check_shift_key(self):
        for roster in self:
            wc = roster.workcenter_id
            if not wc._crew_shift_supported():
                raise ValidationError(
                    self.env._(
                        "Shifts cannot be derived from the working schedule of "
                        "the work center %(wc)s: it is missing, flexible or "
                        "duration based.",
                        wc=wc.display_name,
                    )
                )
            if not roster._crew_block():
                raise ValidationError(
                    self.env._(
                        "The working schedule of the work center %(wc)s has no "
                        "shift starting at %(key)s on %(date)s.",
                        wc=wc.display_name,
                        key=roster.shift_key,
                        date=fields.Date.to_string(roster.date),
                    )
                )

    # ------------------------------------------------------------------
    # M2 — промяна на наряда стига до работните поръчки
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        until = [vals.pop("date_to", False) for vals in vals_list]
        rosters = super().create(vals_list)
        self._crew_apply_to_workorders(rosters._crew_day_keys())
        for roster, date_to in zip(rosters, until):
            roster._crew_extend_to(date_to)
        return rosters

    def write(self, vals):
        date_to = vals.pop("date_to", False)
        relevant = CREW_ROSTER_FIELDS.intersection(vals)
        old_keys = self._crew_day_keys() if relevant else set()
        res = super().write(vals) if vals else True
        if relevant:
            self._crew_apply_to_workorders(old_keys | self._crew_day_keys())
        for roster in self:
            roster._crew_extend_to(date_to)
        return res

    def _crew_extend_to(self, date_to):
        """Същият център, смяна и хора за всеки следващ работен ден до
        `date_to` (№146 на Теолино).

        Работен ден = календарът на центъра има смяна със същия ключ в него,
        без отпуските и празниците. Ден, в който центърът вече има наряд за
        смяната, не се пипа — разгръщането допълва, не презаписва (като
        „Копирай от вчера“).
        """
        self.ensure_one()
        date_to = fields.Date.to_date(date_to)
        if not date_to or date_to <= self.date:
            return self.browse()
        if (date_to - self.date).days > CREW_PERIOD_MAX_DAYS:
            raise UserError(
                self.env._("A crew roster period can be at most three months long.")
            )
        taken = set(
            self.search(
                [
                    ("workcenter_id", "=", self.workcenter_id.id),
                    ("shift_key", "=", self.shift_key),
                    ("date", ">", self.date),
                    ("date", "<=", date_to),
                ]
            ).mapped("date")
        )
        vals_list = []
        day = self.date + timedelta(days=1)
        while day <= date_to:
            # Празникът не маха блока, а изважда часовете му — смяна с 0
            # работни часа не е работен ден.
            if day not in taken and any(
                block["key"] == self.shift_key and block["hours"] > 0
                for block in self.workcenter_id._crew_shift_blocks_for_date(
                    day, compute_leaves=True
                )
            ):
                vals_list.append(
                    {
                        "workcenter_id": self.workcenter_id.id,
                        "date": day,
                        "shift_key": self.shift_key,
                        "employee_ids": [Command.set(self.employee_ids.ids)],
                    }
                )
            day += timedelta(days=1)
        return self.create(vals_list) if vals_list else self.browse()

    def unlink(self):
        keys = self._crew_day_keys()
        res = super().unlink()
        self._crew_apply_to_workorders(keys)
        return res

    def _crew_day_keys(self):
        """(център, ден) на нарядите — по деня, не по смяната: нов наряд
        за една смяна прави центъра „под наряд“ за целия ден (Р25)."""
        return {(r.workcenter_id.id, r.date) for r in self if r.workcenter_id and r.date}

    @api.model
    def _crew_apply_to_workorders(self, keys):
        """Прилага нарядите към отворените поръчки на дадените (център, ден)."""
        if not keys:
            return
        workorders = self.env["mrp.workorder"].search(
            [
                ("workcenter_id", "in", list({k[0] for k in keys})),
                ("crew_date", "in", list({k[1] for k in keys})),
                ("state", "not in", ("done", "cancel")),
            ]
        )
        workorders.filtered(
            lambda wo: (wo.workcenter_id.id, wo.crew_date) in keys
        )._crew_apply()

    # ------------------------------------------------------------------
    # M8 — „Копирай от вчера“
    # ------------------------------------------------------------------

    @api.model
    def action_copy_previous(self, workcenter, day):
        """За всяка смяна на деня без наряд копира хората от последния наряд
        със същия `shift_key` преди деня. Попълнените наряди не се пипат.

        Връща създадените наряди.
        """
        workcenter.ensure_one()
        created = self.browse()
        for block in workcenter._crew_shift_blocks_for_date(day):
            key = block["key"]
            domain = [("workcenter_id", "=", workcenter.id), ("shift_key", "=", key)]
            if self.search_count(domain + [("date", "=", day)], limit=1):
                continue
            previous = self.search(
                domain + [("date", "<", day), ("employee_ids", "!=", False)],
                order="date desc",
                limit=1,
            )
            if not previous:
                continue
            created |= self.create(
                {
                    "workcenter_id": workcenter.id,
                    "date": day,
                    "shift_key": key,
                    "employee_ids": [Command.set(previous.employee_ids.ids)],
                }
            )
        return created

    def action_copy_from_yesterday(self):
        """Бутонът в списъка: центърът е от контекста, денят — днес
        (или `crew_date` от контекста).

        НЕ е `@api.model` (19.0.1.6.1): бутонът в хедъра на списъка минава
        през `call_button` → `call_kw`, който подава избраните ids (или [])
        като първи аргумент. Избраните наряди не се ползват — `self` е само
        носител на средата.
        """
        wc_id = self.env.context.get("crew_workcenter_id")
        if not wc_id:
            raise UserError(
                self.env._("Select a work center first (Plan Work Center).")
            )
        workcenter = self.env["mrp.workcenter"].browse(wc_id)
        day = fields.Date.to_date(
            self.env.context.get("crew_date")
        ) or fields.Date.context_today(self)
        created = self.action_copy_previous(workcenter, day)
        if not created:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "warning",
                    "message": self.env._(
                        "Nothing to copy: every shift of the day already has a "
                        "crew roster or there is no earlier roster."
                    ),
                },
            }
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    # ------------------------------------------------------------------
    # M7 — „Преизчисли“ за избрания център
    # ------------------------------------------------------------------

    def action_crew_recompute(self):
        """Бутонът в списъка: центърът е от контекста `crew_workcenter_id`,
        денят на разделянето — `crew_date` от контекста или днес.

        НЕ е `@api.model` (19.0.1.6.1), както `action_copy_from_yesterday`:
        бутонът подава ids; Гантът го вика с празен списък ids (`[[]]`).
        Избраните наряди не се ползват.
        """
        wc_id = self.env.context.get("crew_workcenter_id")
        if not wc_id:
            raise UserError(
                self.env._("Select a work center first (Plan Work Center).")
            )
        workcenter = self.env["mrp.workcenter"].browse(wc_id)
        day = fields.Date.to_date(self.env.context.get("crew_date"))
        return workcenter._crew_recompute(day)._crew_action_open()

    def action_crew_recompute_roster(self):
        """Бутонът във формата: центърът и денят са на наряда."""
        self.ensure_one()
        return self.workcenter_id._crew_recompute(self.date)._crew_action_open()
