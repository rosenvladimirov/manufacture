# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Бригадните подграфици на главния сменен график (Росен 14.10.2026).

Главният график на фирмата (напр. 2 смени по 12 ч, 7 дни в седмицата) се
разбива на РОТАЦИЯ: цикъл от L дни, всеки ден е смяна (шаблон на Planning) или
почивка. Бригадата е същият цикъл, изместен с `offset_days`; смяната на
бригадата в ден d е позиция `(d − котва + отместване) mod L`. Сборът от
бригадите покрива главния график точно — всеки ден по една смяна от всеки
шаблон (`_check_coverage`).

Моделът е индустриалният (SAP Period Work Schedule, Kronos Rotation
Schedule, Oracle Shift Generation): цикъл + котва + бригада = отместване.
Календарът на Odoo (`resource.calendar`) не се пипа — в него цикълът е най-
много две седмици, а промяна в ядрото засяга отпуските и ТРЗ на всички.
"""
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from . import crew_law

# Образците (Росен 14.10.2026, проучването в
# claude.ai/specs/poligroup-crew-rotation/PLAN.md): D — дневна, N — нощна,
# R — почивка; отместванията на четирите бригади. DuPont е изключен — една
# седмица от 72 ч е над тавана от 56 ч (чл. 142, ал. 6 КТ).
_PITMAN = "DDRRDDDRRDDRRR"
CREW_PRESETS = {
    "2-2-4": ("DDNNRRRR", (0, 2, 4, 6)),
    "4-on-4-off": ("DDDDRRRRNNNNRRRR", (0, 4, 8, 12)),
    "panama": (_PITMAN * 2 + _PITMAN.replace("D", "N") * 2, (0, 7, 28, 35)),
}
CREW_PRESET_SELECTION = [
    ("2-2-4", "2-2-4 (8 days: 2 day, 2 night, 4 off)"),
    ("4-on-4-off", "4-on-4-off (16 days)"),
    ("panama", "Panama 2-2-3 (56 days)"),
]
# Таваните от КТ, които цикълът не бива да нарушава мълчаливо.
CREW_MAX_SHIFT_HOURS = 12.0       # чл. 142, ал. 6 (смяна при сумирано отчитане)
CREW_MAX_WEEK_HOURS = 56.0        # чл. 142, ал. 6 (седмица при сумирано отчитане)
CREW_MIN_DAILY_REST_HOURS = 12.0  # чл. 152 (междудневна почивка при сумирано отчитане)


def template_hours(template):
    """Продължителността на шаблона в часове: нощната 19→07 е с
    `duration_days = 2` (`planning_template.py`)."""
    return (template.duration_days - 1) * 24.0 + template.end_time - template.start_time


class PlanningCrewRotation(models.Model):
    _name = "planning.crew.rotation"
    _description = "Crew Rotation"
    _inherit = ["mail.thread"]
    _order = "sequence, id"

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company)
    department_id = fields.Many2one("hr.department", tracking=True)
    calendar_id = fields.Many2one(
        "resource.calendar", string="Company Shift Schedule",
        help="The approved shift schedule of the company that the crews split "
             "between them, e.g. two shifts of 12 hours, seven days a week.")
    day_template_id = fields.Many2one(
        "planning.slot.template", string="Day Shift",
        help="The day shift of the company schedule, used by the presets.")
    night_template_id = fields.Many2one(
        "planning.slot.template", string="Night Shift",
        help="The night shift of the company schedule, used by the presets.")
    anchor_date = fields.Date(
        string="Cycle Start", required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
        help="Day 0 of the cycle — by default the first day of the month.")
    summing_period_months = fields.Selection(
        # чл. 142, ал. 3–4 КТ: 1–4 месеца, до 12 само с колективен трудов договор
        [("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("12", "12 (collective agreement)")],
        string="Summed Accounting Period (Months)", required=True, default="3",
        tracking=True,
        help="Period of the summed accounting of working time (Art. 142 of the "
             "Labour Code): 1 to 4 months, up to 12 with a collective agreement.")
    preset = fields.Selection(
        CREW_PRESET_SELECTION, string="Preset",
        help="Fills the cycle and four crews from a known pattern.")
    line_ids = fields.One2many(
        "planning.crew.rotation.line", "rotation_id", string="Cycle", copy=True)
    cycle_length = fields.Integer(compute="_compute_cycle_length", store=True)
    crew_ids = fields.One2many(
        "planning.crew", "rotation_id", string="Crews", copy=True)
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved")],
        default="draft", required=True, tracking=True, copy=False)
    approved_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    approved_date = fields.Datetime(readonly=True, copy=False)
    reload_needed = fields.Boolean(
        string="Reload Needed", tracking=True, copy=False,
        help="An approved leave touches generated shifts of this rotation; "
             "generate the shifts again to re-arrange them with substitutes.")
    coverage_html = fields.Html(compute="_compute_coverage_html", sanitize=False)
    norm_html = fields.Html(
        string="Working Time Norm", compute="_compute_norm_html", sanitize=False,
        help="Scheduled hours of every member for the current summed accounting period "
             "against the norm (Ordinance on working time, Art. 9a–9b); night hours count "
             "×1.143. Hours above the norm are overtime (Art. 9d) — warning only.")
    norm_warning_count = fields.Integer(compute="_compute_norm_html")

    # В 18 няма models.Constraint — ограничението е в _sql_constraints.
    _sql_constraints = [
        ("name_company_unique", "UNIQUE(name, company_id)", "The rotation name must be unique per company."),
    ]

    @api.depends("line_ids")
    def _compute_cycle_length(self):
        for rotation in self:
            rotation.cycle_length = len(rotation.line_ids)

    # ------------------------------------------------------------------
    # Цикълът
    # ------------------------------------------------------------------

    def _cycle(self):
        """Шаблоните по позиции (празно = почивка), подредени по позиция."""
        self.ensure_one()
        lines = self.line_ids.sorted("position")
        return [line.template_id for line in lines]

    def _position(self, crew, day):
        self.ensure_one()
        length = self.cycle_length
        if not length:
            return None
        return ((day - self.anchor_date).days + crew.offset_days) % length

    def _template_on(self, crew, day):
        """Шаблонът на бригадата в ден `day` или празен запис (почивка)."""
        self.ensure_one()
        position = self._position(crew, day)
        if position is None:
            return self.env["planning.slot.template"]
        return self._cycle()[position]

    def _shift_interval(self, template, day):
        """Начало и край на смяната в UTC (без tz) за логическия ден `day`.
        Нощната 19:00 → 07:00 свършва на следващия ден. Началото и краят са
        по МЕСТНИЯ часовник — следващата бригада идва в 07:00 — затова в
        нощта на смяната на часовото време смяната е 13 или 11 ч (критиката
        към плана, 14.10.2026)."""
        self.ensure_one()
        tz = pytz.timezone(self.calendar_id.tz or self.env.user.tz or "Europe/Sofia")
        hours = template_hours(template)
        start_wall = datetime.combine(day, time()) + timedelta(hours=template.start_time)
        start_local = tz.localize(start_wall)
        end_local = tz.localize(start_wall + timedelta(hours=hours))
        start = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        end = end_local.astimezone(pytz.utc).replace(tzinfo=None)
        return start, end

    def _coverage_issues(self):
        """Дните от цикъла, в които бригадите не покриват главния график
        точно: всеки шаблон, който се среща в цикъла, трябва да се пада на
        точно една бригада всеки ден."""
        self.ensure_one()
        cycle = self._cycle()
        length = len(cycle)
        templates = {t for t in cycle if t}
        issues = []
        if not length:
            return [self.env._("The cycle is empty.")]
        if not self.crew_ids:
            return [self.env._("The rotation has no crews.")]
        for position in range(length):
            counts = {t: 0 for t in templates}
            for crew in self.crew_ids:
                template = cycle[(position + crew.offset_days) % length]
                if template:
                    counts[template] += 1
            for template, count in counts.items():
                if count != 1:
                    issues.append(self.env._(
                        "Day %(day)s of the cycle: %(shift)s is worked by %(count)s crews.",
                        day=position + 1, shift=template.display_name, count=count))
        return issues

    def _labour_issues(self):
        """Таваните на КТ върху цикъла на една бригада (всички бригади са
        един и същ цикъл): смяна ≤ 12 ч, междудневна почивка ≥ 12 ч и ≤ 56 ч
        във всеки плъзгащ се прозорец от 7 дни."""
        self.ensure_one()
        cycle = self._cycle()
        length = len(cycle)
        issues = []
        if not length:
            return issues
        for template in {t for t in cycle if t}:
            if template_hours(template) > CREW_MAX_SHIFT_HOURS:
                issues.append(self.env._(
                    "The shift %(shift)s lasts %(hours)s hours — above %(max)s.",
                    shift=template.display_name, hours=template_hours(template),
                    max=CREW_MAX_SHIFT_HOURS))
        # две обиколки, за да се видят преходите през края на цикъла
        spans = []
        for day in range(2 * length):
            template = cycle[day % length]
            if template:
                start = day * 24.0 + template.start_time
                spans.append((day, start, start + template_hours(template)))
        for (day1, _s1, end1), (_day2, start2, _e2) in zip(spans, spans[1:]):
            if day1 < length and start2 - end1 < CREW_MIN_DAILY_REST_HOURS:
                issues.append(self.env._(
                    "Day %(day)s of the cycle: only %(rest)s hours of rest before the next shift.",
                    day=day1 + 1, rest=round(start2 - end1, 1)))
        for first in range(length):
            window = sum(
                template_hours(cycle[(first + i) % length])
                for i in range(7) if cycle[(first + i) % length])
            if window > CREW_MAX_WEEK_HOURS:
                issues.append(self.env._(
                    "Days %(from)s–%(to)s of the cycle: %(hours)s hours in seven days — above %(max)s.",
                    **{"from": first + 1, "to": first + 7, "hours": window,
                       "max": CREW_MAX_WEEK_HOURS}))
        return issues

    @api.depends("line_ids.template_id", "line_ids.position", "crew_ids.offset_days",
                 "crew_ids.code", "anchor_date")
    def _compute_coverage_html(self):
        for rotation in self:
            cycle = rotation._cycle()
            if not cycle or not rotation.crew_ids:
                rotation.coverage_html = False
                continue
            head = "".join("<th>%s</th>" % (p + 1) for p in range(len(cycle)))
            rows = []
            for crew in rotation.crew_ids.sorted("offset_days"):
                cells = []
                for position in range(len(cycle)):
                    template = cycle[(position + crew.offset_days) % len(cycle)]
                    mark = (template.name or "") if template else "—"
                    cells.append("<td>%s</td>" % mark)
                rows.append("<tr><th>%s</th>%s</tr>" % (crew.code, "".join(cells)))
            rotation.coverage_html = (
                '<table class="table table-sm table-bordered text-center o_crew_coverage">'
                "<thead><tr><th/>%s</tr></thead><tbody>%s</tbody></table>"
                % (head, "".join(rows)))

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------

    def action_load_preset(self):
        """Цикълът и четирите бригади от образеца. Бригадите вече имат
        кодове (напр. А/Б/В/Г) — пазят се, сменя се само отместването."""
        for rotation in self:
            rotation._check_editable()
            if not rotation.preset:
                raise UserError(self.env._("Choose a preset first."))
            if not (rotation.day_template_id and rotation.night_template_id):
                raise UserError(self.env._(
                    "Set the day and the night shift of the company schedule first."))
            pattern, offsets = CREW_PRESETS[rotation.preset]
            by_letter = {"D": rotation.day_template_id, "N": rotation.night_template_id}
            rotation.line_ids.unlink()
            rotation.line_ids = [
                fields.Command.create({
                    "position": position,
                    "template_id": by_letter.get(letter, self.env["planning.slot.template"]).id,
                })
                for position, letter in enumerate(pattern)
            ]
            crews = rotation.crew_ids.sorted(lambda c: (c.offset_days, c.id))
            default_codes = ["A", "B", "C", "D"]
            for index, offset in enumerate(offsets):
                if index < len(crews):
                    crews[index].offset_days = offset
                else:
                    rotation.crew_ids = [fields.Command.create({
                        "code": default_codes[index], "offset_days": offset})]
        return True

    def _check_editable(self):
        for rotation in self:
            if rotation.state == "approved":
                raise UserError(self.env._(
                    "The rotation %(name)s is approved; reset it to draft to change "
                    "the cycle.", name=rotation.display_name))

    def action_check(self):
        self.ensure_one()
        issues = self._coverage_issues() + self._labour_issues()
        if issues:
            raise ValidationError("\n".join(issues))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": self.env._("The crews cover the company schedule and the "
                                      "cycle keeps the Labour Code limits."),
            },
        }

    def action_approve(self):
        for rotation in self:
            issues = rotation._coverage_issues() + rotation._labour_issues()
            if issues:
                raise ValidationError("\n".join(issues))
            rotation.write({
                "state": "approved",
                "approved_by_id": self.env.uid,
                "approved_date": fields.Datetime.now(),
            })
        return True

    def action_reset_draft(self):
        self.write({"state": "draft", "approved_by_id": False, "approved_date": False})
        return True

    def action_open_generate(self):
        self.ensure_one()
        if self.state != "approved":
            raise UserError(self.env._("Approve the rotation before generating shifts."))
        today = fields.Date.context_today(self)
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Generate Shifts"),
            "res_model": "planning.crew.rotation.generate",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_rotation_id": self.id,
                "default_date_from": today,
                "default_date_to": today + timedelta(days=27),
            },
        }

    # ------------------------------------------------------------------
    # Генераторът (Росен 14.10.2026: само ръчно)
    # ------------------------------------------------------------------

    def _crew_generate(self, date_from, date_to, dry_run=False):
        """Желаните смени за периода спрямо генерираните досега.

        - ключът е (назначение, ден): на ден всеки служител има най-много
          една смяна от ротацията;
        - чернова, генерирана и неточена на ръка → обновява се или се трие;
        - публикувана или поправена на ръка → не се пипа, излиза в
          конфликтите;
        - служител в утвърден отпуск → първият свободен заместник от картона
          му; без заместник — отворена смяна.
        Връща броячите."""
        self.ensure_one()
        if date_to < date_from:
            raise UserError(self.env._("The end date is before the start date."))
        Slot = self.env["planning.slot"]
        # назначенията, заместниците и отпуските са в ЧР — началникът на
        # планирането ги чете, без да има права там
        Membership = self.env["planning.crew.membership"].sudo()
        memberships = Membership.search([
            ("rotation_id", "=", self.id),
            ("date_from", "<=", date_to),
            "|", ("date_to", "=", False), ("date_to", ">=", date_from),
        ])
        days = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
        period_start = self._shift_interval_bounds(date_from, date_to)

        employees = memberships.employee_id | memberships.employee_id.crew_substitute_ids
        # Отпускът се мери в ДНИ на смяната, не в часове: часовете на отпуска
        # идват от календара на служителя (напр. 8–17) и нощната смяна не би
        # се засякла с тях.
        leaves = self.env["hr.leave"].sudo().search([
            ("employee_id", "in", employees.ids),
            ("state", "=", "validate"),
            ("request_date_from", "<=", date_to),
            ("request_date_to", ">=", date_from),
        ])
        leaves_by_employee = {}
        for leave in leaves:
            leaves_by_employee.setdefault(leave.employee_id.id, []).append(
                (leave.request_date_from, leave.request_date_to))

        def absent(employee, day):
            return any(s <= day <= e for s, e in leaves_by_employee.get(employee.id, ()))

        existing = Slot.search([
            ("crew_rotation_id", "=", self.id),
            ("crew_generated", "=", True),
            ("crew_date", ">=", date_from),
            ("crew_date", "<=", date_to),
        ])
        by_key = {(slot.crew_membership_id.id, slot.crew_date): slot for slot in existing}
        # Заетостта на заместниците: смени извън ротацията + желаните в тази обиколка.
        busy = {}
        other = Slot.search([
            ("resource_id", "in", employees.resource_id.ids),
            ("start_datetime", "<", period_start[1]),
            ("end_datetime", ">", period_start[0]),
            ("id", "not in", existing.ids),
        ])
        for slot in other:
            busy.setdefault(slot.resource_id.id, []).append((slot.start_datetime, slot.end_datetime))

        def free(employee, start, end):
            return not any(
                s < end and e > start for s, e in busy.get(employee.resource_id.id, ()))

        tz_name = self.calendar_id.tz or self.env.user.tz or "Europe/Sofia"

        def is_night(start, end):
            # нощен работник при ≥ 3 ч нощен труд в смяната (чл. 140а КТ)
            return crew_law.night_hours(*crew_law.local_bounds(start, end, tz_name)) \
                >= crew_law.NIGHT_WORKER_MIN_HOURS

        def fits(sub, start, end, day):
            """Заместникът: без забрана за нощен труд и с почивките (Росен 15.10.2026:
            неподходящ заместник се прескача; липсващият медицински преглед само
            предупреждава)."""
            if is_night(start, end) and set(sub._crew_night_issues(day)) - {"no_medical"}:
                return False
            return not crew_law.schedule_issues(busy.get(sub.resource_id.id, []), start, end)

        desired = {}
        for day in days:
            for membership in memberships:
                if membership.date_from > day or (membership.date_to and membership.date_to < day):
                    continue
                template = self._template_on(membership.crew_id, day)
                if not template:
                    continue
                start, end = self._shift_interval(template, day)
                employee = membership.employee_id
                worker = employee
                substitute_for = self.env["hr.employee"]
                if absent(employee, day):
                    substitute_for = employee
                    worker = next(
                        (sub for sub in employee.crew_substitute_ids
                         if not absent(sub, day) and free(sub, start, end)
                         and fits(sub, start, end, day)),
                        self.env["hr.employee"])
                if worker:
                    busy.setdefault(worker.resource_id.id, []).append((start, end))
                desired[(membership.id, day)] = {
                    "resource_id": worker.resource_id.id or False,
                    "start_datetime": start,
                    "end_datetime": end,
                    "template_id": template.id,
                    "role_id": membership.crew_id.role_id.id or False,
                    "company_id": self.company_id.id,
                    "crew_rotation_id": self.id,
                    "crew_id": membership.crew_id.id,
                    "crew_membership_id": membership.id,
                    "crew_date": day,
                    "crew_generated": True,
                    "crew_substitute_for_id": substitute_for.id or False,
                }

        # Предупрежденията на закона — върху цялата картина на човека
        warned = 0
        for vals in desired.values():
            issues = []
            res_id = vals["resource_id"]
            if res_id:
                start, end = vals["start_datetime"], vals["end_datetime"]
                issues = crew_law.schedule_issues(busy.get(res_id, []), start, end)
                if is_night(start, end):
                    emp = self.env["resource.resource"].browse(res_id).sudo().employee_id[:1]
                    if emp:
                        issues += emp._crew_night_issues(vals["crew_date"])
            vals["crew_warning_codes"] = ",".join(sorted(set(issues))) or False
            warned += bool(issues)

        counts = {"created": 0, "updated": 0, "deleted": 0, "kept": 0,
                  "conflicts": 0, "open": 0, "substituted": 0, "warnings": warned}
        to_create = []
        compared = ("resource_id", "start_datetime", "end_datetime", "template_id",
                    "crew_substitute_for_id", "crew_warning_codes")
        for key, vals in desired.items():
            if not vals["resource_id"]:
                counts["open"] += 1
            if vals["crew_substitute_for_id"]:
                counts["substituted"] += 1
            slot = by_key.pop(key, None)
            if not slot:
                to_create.append(vals)
                continue
            current = {
                "resource_id": slot.resource_id.id or False,
                "start_datetime": slot.start_datetime,
                "end_datetime": slot.end_datetime,
                "template_id": slot.template_id.id,
                "crew_substitute_for_id": slot.crew_substitute_for_id.id or False,
                "crew_warning_codes": slot.crew_warning_codes or False,
            }
            if all(current[f] == vals[f] for f in compared):
                counts["kept"] += 1
            elif slot.crew_manual or slot.state == "published":
                counts["conflicts"] += 1
            else:
                counts["updated"] += 1
                if not dry_run:
                    slot.with_context(crew_rotation_sync=True).write(
                        {f: vals[f] for f in compared + ("role_id",)})
        for slot in by_key.values():
            if slot.crew_manual or slot.state == "published":
                counts["conflicts"] += 1
            else:
                counts["deleted"] += 1
                if not dry_run:
                    slot.with_context(crew_rotation_sync=True).unlink()
        counts["created"] = len(to_create)
        if not dry_run:
            Slot.with_context(crew_rotation_sync=True).create(to_create)
            if self.reload_needed:
                self.reload_needed = False
        return counts

    @api.model
    def _crew_issue_labels(self):
        _ = self.env._
        return {
            "overlap": _("overlaps another shift"),
            "rest": _("less than 12 h rest between shifts (Labour Code, Art. 152)"),
            "weekly_rest": _("less than 24 h weekly rest (Labour Code, Art. 153)"),
            "week_hours": _("more than 56 h in 7 days (Labour Code, Art. 142)"),
            "minor": _("night work under 18 is forbidden (Labour Code, Art. 140)"),
            "pregnancy": _("night work is forbidden in pregnancy / IVF (Labour Code, Art. 140)"),
            "no_consent": _("night work needs written consent (Labour Code, Art. 140)"),
            "no_medical": _("no medical exam for night work (Labour Code, Art. 140a)"),
        }

    # ------------------------------------------------------------------
    # Норма за периода на сумирано изчисляване (чл. 9а–9г НРВПО) — само предупреждение
    # ------------------------------------------------------------------

    def _crew_period(self, day):
        """Периодът на сумиране, в който е `day`: от месеца на котвата, по N месеца."""
        self.ensure_one()
        months = int(self.summing_period_months or 3)
        base = self.anchor_date.replace(day=1)
        index = ((day.year - base.year) * 12 + day.month - base.month) // months
        first = base + relativedelta(months=index * months)
        return first, first + relativedelta(months=months) - timedelta(days=1)

    def _crew_holidays(self, date_from, date_to):
        """Неработните дни по календара на фирмата (общите отпуски на календара)."""
        calendar = self.company_id.resource_calendar_id
        leaves = self.env["resource.calendar.leaves"].sudo().search([
            ("resource_id", "=", False),
            ("calendar_id", "in", [False, calendar.id]),
            ("company_id", "in", [False, self.company_id.id]),
            ("date_from", "<=", datetime.combine(date_to, time.max)),
            ("date_to", ">=", datetime.combine(date_from, time.min)),
        ])
        days = set()
        for leave in leaves:
            day = leave.date_from.date()
            while day <= leave.date_to.date():
                days.add(day)
                day += timedelta(days=1)
        return days

    def _crew_norm_rows(self, day=None):
        """По човек: норма, часове по графика (нощните ×1,143), разлика.
        Норма = работни дни по календар × дневните часове по договора, минус дните
        отпуск в работни дни (чл. 9б, ал. 1–2). ОПРОСТЯВАНЕ: и болничните се вадят по
        ал. 2 (дни × часове), не по ал. 3 (часовете по графика)."""
        self.ensure_one()
        day = day or fields.Date.context_today(self)
        date_from, date_to = self._crew_period(day)
        holidays = self._crew_holidays(date_from, date_to)
        workdays = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
        workdays = [d for d in workdays if d.weekday() < 5 and d not in holidays]
        memberships = self.env["planning.crew.membership"].sudo().search([
            ("rotation_id", "=", self.id), ("date_from", "<=", date_to),
            "|", ("date_to", "=", False), ("date_to", ">=", date_from)])
        tz_name = self.calendar_id.tz or self.env.user.tz or "Europe/Sofia"
        tz = pytz.timezone(tz_name)
        # смените, ПОЧНАЛИ в местните дни на периода
        utc_from = tz.localize(datetime.combine(date_from, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        utc_to = tz.localize(datetime.combine(date_to + timedelta(days=1), time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        rows = []
        for employee in memberships.employee_id:
            daily = employee.resource_calendar_id.hours_per_day or 8.0
            leaves = self.env["hr.leave"].sudo().search([
                ("employee_id", "=", employee.id), ("state", "=", "validate"),
                ("request_date_from", "<=", date_to), ("request_date_to", ">=", date_from)])
            leave_days = {d for d in workdays for leave in leaves
                          if leave.request_date_from <= d <= leave.request_date_to}
            norm = (len(workdays) - len(leave_days)) * daily
            slots = self.env["planning.slot"].sudo().search([
                ("resource_id", "=", employee.resource_id.id),
                ("start_datetime", ">=", utc_from), ("start_datetime", "<", utc_to),
            ])
            raw = converted = 0.0
            for slot in slots:
                start, end = crew_law.local_bounds(slot.start_datetime, slot.end_datetime, tz_name)
                raw += (end - start).total_seconds() / 3600.0
                converted += crew_law.converted_hours(start, end)
            crew = memberships.filtered(lambda m: m.employee_id == employee)[:1].crew_id
            months = int(self.summing_period_months or 3)
            rows.append({
                "employee": employee.name, "crew": crew.code or "", "norm": norm,
                "raw": raw, "converted": converted, "excess": converted - norm,
                "year": (converted - norm) * 12.0 / months,
            })
        rows.sort(key=lambda r: -r["excess"])
        return (date_from, date_to), rows

    @api.depends("summing_period_months", "anchor_date")
    def _compute_norm_html(self):
        _ = self.env._
        for rotation in self:
            if not rotation.id or not rotation.anchor_date:
                rotation.norm_html = False
                rotation.norm_warning_count = 0
                continue
            (date_from, date_to), rows = rotation._crew_norm_rows()
            over = [r for r in rows if r["excess"] > 0.05]
            rotation.norm_warning_count = len(over)
            body = "".join(
                "<tr class='%s'><td>%s</td><td>%s</td><td>%.1f</td><td>%.1f</td><td>%.1f</td>"
                "<td>%+.1f</td><td>%+.0f</td></tr>" % (
                    "table-danger" if r["year"] > crew_law.MAX_OVERTIME_YEAR_HOURS
                    else ("table-warning" if r["excess"] > 0.05 else ""),
                    r["employee"], r["crew"], r["norm"], r["raw"], r["converted"],
                    r["excess"], r["year"]) for r in rows)
            rotation.norm_html = (
                "<p>%s</p><table class='table table-sm table-bordered'><thead><tr>"
                "<th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th>"
                "</tr></thead><tbody>%s</tbody></table>" % (
                    _("Period %(from)s – %(to)s. Hours above the norm are overtime (Ordinance on "
                      "working time, Art. 9d): at most 150 h a year (Labour Code, Art. 146). "
                      "Warning only.", **{"from": date_from, "to": date_to}),
                    _("Employee"), _("Crew"), _("Norm"), _("Scheduled"),
                    _("Night ×1.143"), _("Above Norm"), _("Per Year"), body))

    def _shift_interval_bounds(self, date_from, date_to):
        """UTC граници, които хващат всички смени на периода (нощната от
        последния ден свършва на следващия)."""
        start = datetime.combine(date_from, time()) - timedelta(days=1)
        end = datetime.combine(date_to, time()) + timedelta(days=2)
        return start, end


class PlanningCrewRotationLine(models.Model):
    _name = "planning.crew.rotation.line"
    _description = "Crew Rotation Day"
    _order = "rotation_id, position"

    rotation_id = fields.Many2one(
        "planning.crew.rotation", required=True, ondelete="cascade", index=True)
    position = fields.Integer(required=True, help="Day of the cycle, starting from 0.")
    day_number = fields.Integer(string="Day", compute="_compute_day_number")
    template_id = fields.Many2one(
        "planning.slot.template", string="Shift",
        help="The shift of this day of the cycle; empty means a day off.")

    # В 18 няма models.Constraint — ограничението е в _sql_constraints.
    _sql_constraints = [
        ("position_unique", "UNIQUE(rotation_id, position)", "A day of the cycle appears only once."),
    ]

    @api.depends("position")
    def _compute_day_number(self):
        for line in self:
            line.day_number = line.position + 1


class PlanningCrew(models.Model):
    _name = "planning.crew"
    _description = "Crew"
    _order = "rotation_id, offset_days, id"

    rotation_id = fields.Many2one(
        "planning.crew.rotation", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="rotation_id.company_id", store=True)
    code = fields.Char(required=True, help="The letter of the crew, e.g. A.")
    name = fields.Char(compute="_compute_name", store=True)
    offset_days = fields.Integer(
        string="Offset (Days)", help="How many days the crew is ahead in the cycle.")
    role_id = fields.Many2one(
        "planning.role", string="Role", help="Role of the generated shifts.")
    color = fields.Integer()
    membership_ids = fields.One2many("planning.crew.membership", "crew_id")
    member_count = fields.Integer(compute="_compute_member_count")

    # В 18 няма models.Constraint — ограничението е в _sql_constraints.
    _sql_constraints = [
        ("code_unique", "UNIQUE(rotation_id, code)", "The crew letter must be unique in the rotation."),
    ]

    @api.depends("code", "rotation_id.name")
    def _compute_name(self):
        for crew in self:
            crew.name = "%s / %s" % (crew.rotation_id.name or "", crew.code or "")

    def _compute_member_count(self):
        today = fields.Date.context_today(self)
        for crew in self:
            crew.member_count = len(crew.membership_ids.filtered(
                lambda m: m.date_from <= today and (not m.date_to or m.date_to >= today)))
