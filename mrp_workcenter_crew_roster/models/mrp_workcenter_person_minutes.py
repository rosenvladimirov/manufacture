# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Делът на бригадата в продължителността (№145 на Теолино, ADR-0070).

Любо, 12.10: „В рецептите са човеко минути (и това е првилно да е)“;
„Повече хора на рязане или лепене не скъсяват времето, но повече хора на
асемблиране я скъсяват“; асемблирането е „може би 3/4 от целия труд“.

Делът е на ОПЕРАЦИЯТА (`mrp.routing.workcenter.crew_share`, 0–100 %), а
работната поръчка го носи (`mrp.workorder.crew_share`) — алтернативните
центрове правят едно и също, операцията се мести между тях:

    прозорец = duration_expected × (1 − дял) + duration_expected × дял ÷ бригадата

където бригадата е нарядът на центъра, на който се планира, за деня и
смяната на началото. Без наряд (или с един човек) — пълното време; при
дял > 0 без наряд лентата казва „без бригада“. Дял 0 (по подразбиране) —
както досега: Полигруп не се засяга.

`duration_expected` остава човеко-минути: натоварването, капацитетът,
себестойността по плана и деленето на реалното време не се пипат. Реалната
машинна част на себестойността при дял > 0 е costs_hour × СБОРА от минутите
в time_ids, не × обединението на интервалите (вариант б, Клаудио 12.10).

Превръщането е на ЕДНО място — търсенето на слот на центъра (то стои под
„Plan“, пистите, влака, веригата, партидата). Делът стига до него през
контекста `crew_share` (дробта 0–1), който слага поръчката, понеже центърът
сам не знае чия е продължителността. Плюс двете сметки на ядрото между
прозорец и продължителност (влачене и разтягане в Ганта).
"""
from datetime import timedelta

from odoo import api, fields, models
from odoo.addons.resource.models.utils import Intervals, sum_intervals
from odoo.exceptions import ValidationError

# Делът (0–1) на поръчката, чийто слот се търси.
CREW_SHARE = "crew_share"
# Търсенето на слот вика себе си през пистите — превръщането е веднъж.
CREW_SHARE_DONE = "crew_share_done"


def crew_window_factor(share, crew):
    """Колко от човеко-минутите е прозорецът: 1 − дял + дял ÷ бригадата."""
    if not share or crew <= 1:
        return 1.0
    return 1.0 - share + share / crew


class MrpRoutingWorkcenter(models.Model):
    _inherit = "mrp.routing.workcenter"

    crew_share = fields.Float(
        string="Crew Share (%)",
        default=0.0,
        help="The part of the expected duration that the crew of the day "
        "divides: with 100% two people finish in half the time, with 0% the "
        "crew does not shorten it (a machine). The duration stays in "
        "person-minutes for the load and the cost.",
    )

    @api.constrains("crew_share")
    def _check_crew_share(self):
        for operation in self:
            if not 0.0 <= operation.crew_share <= 100.0:
                raise ValidationError(
                    self.env._("The crew share must be between 0% and 100%.")
                )


class MrpWorkcenter(models.Model):
    _inherit = "mrp.workcenter"

    def _crew_size_at(self, moment):
        """Хората в наряда на центъра за смяната, в която попада `moment`
        (UTC без tz); 0 без наряд."""
        self.ensure_one()
        day, key = self._crew_slot(moment)
        if not key:
            return 0
        roster = self.env["mrp.workcenter.roster"].sudo().search(
            [("workcenter_id", "=", self.id), ("date", "=", day), ("shift_key", "=", key)],
            limit=1,
        )
        return len(roster.employee_ids)

    def _get_first_available_slot(
        self,
        start_datetime,
        duration,
        forward=True,
        leaves_to_ignore=False,
        extra_leaves_slots=[],  # noqa: B006 — сигнатурата на ядрото
    ):
        """С пълното време се намира началото; бригадата на това начало дава
        прозореца и той се търси пак. Друго начало (по-късият прозорец влиза
        в по-ранна дупка) ⇒ бригадата се сверява пак — най-много три пъти."""
        share = self.env.context.get(CREW_SHARE) or 0.0
        if len(self) != 1 or not share or self.env.context.get(CREW_SHARE_DONE):
            return super()._get_first_available_slot(
                start_datetime,
                duration,
                forward=forward,
                leaves_to_ignore=leaves_to_ignore,
                extra_leaves_slots=extra_leaves_slots,
            )
        inner = super(MrpWorkcenter, self.with_context(**{CREW_SHARE_DONE: True}))

        def find(minutes):
            return inner._get_first_available_slot(
                start_datetime,
                minutes,
                forward=forward,
                leaves_to_ignore=leaves_to_ignore,
                extra_leaves_slots=extra_leaves_slots,
            )

        date_from, date_to = find(duration)
        crew = self._crew_size_at(date_from) if date_from else 0
        for _attempt in range(3):
            factor = crew_window_factor(share, crew)
            if factor >= 1.0:
                break
            new_from, new_to = find(duration * factor)
            if not new_from:
                break
            date_from, date_to = new_from, new_to
            new_crew = self._crew_size_at(date_from)
            if new_crew == crew:
                break
            crew = new_crew
        return date_from, date_to


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    # Обикновено поле, не stored compute: при инсталация compute се пуска
    # за всички заварени поръчки, преди операциите да имат своята колона
    # (на копие на fulltest 12.10 — „column crew_share does not exist“).
    crew_share = fields.Float(
        string="Crew Share (%)",
        default=0.0,
        help="The part of the expected duration that the crew of the day "
        "divides; taken from the operation.",
    )
    crew_no_crew = fields.Boolean(
        string="No Crew",
        compute="_compute_crew_no_crew",
        help="The crew shortens this work order, but its work center has no "
        "crew for the day: it is planned with its full duration.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Делът идва от операцията при създаване. Промяна на дела в
        операцията не пипа заварените поръчки (вкл. приключените) —
        прехвърлянето е изрично (виж teolino_mrp_crew_montage)."""
        Operation = self.env["mrp.routing.workcenter"]
        for vals in vals_list:
            if "crew_share" not in vals and vals.get("operation_id"):
                vals["crew_share"] = Operation.browse(vals["operation_id"]).crew_share
        return super().create(vals_list)

    def write(self, vals):
        if "operation_id" in vals and "crew_share" not in vals:
            vals = dict(
                vals,
                crew_share=self.env["mrp.routing.workcenter"]
                .browse(vals["operation_id"])
                .crew_share,
            )
        return super().write(vals)

    @api.depends("crew_share", "date_start", "state", "employee_assigned_ids")
    def _compute_crew_no_crew(self):
        for wo in self:
            wo.crew_no_crew = bool(
                wo.crew_share
                and wo.workcenter_id
                and wo.date_start
                and wo.state not in ("done", "cancel")
                and not wo.workcenter_id._crew_size_at(wo.date_start)
            )

    @api.depends("employee_assigned_ids", "crew_no_crew")
    def _compute_crew_names(self):
        """№145: без бригада — казва се, не стои празно."""
        res = super()._compute_crew_names()
        for wo in self.filtered("crew_no_crew"):
            wo.crew_names = self.env._("No crew")
        return res

    def _crew_share_fraction(self):
        self.ensure_one()
        return min(max(self.crew_share or 0.0, 0.0), 100.0) / 100.0

    def _crew_with_share(self, workcenter):
        """Центърът с дела на поръчката в контекста — за търсенето на слот."""
        self.ensure_one()
        return workcenter.with_context(**{CREW_SHARE: self._crew_share_fraction()})

    def _crew_window_factor(self, date_start=False):
        """Прозорец ÷ човеко-минути за началото `date_start` (1 = не се дели)."""
        self.ensure_one()
        share = self._crew_share_fraction()
        workcenter = self.env.context.get("new_workcenter_id") or self.workcenter_id
        start = date_start or self.date_start
        if not (share and workcenter and start):
            return 1.0
        return crew_window_factor(share, workcenter._crew_size_at(start))

    def _plan_workorder(self, replan=False):
        """Стандартното „Plan“ търси слот на всеки кандидат (центърът и
        алтернативите) — с дела в контекста всеки го дели на своята бригада
        и печели най-ранният край."""
        return super(
            MrpWorkorder, self.with_context(**{CREW_SHARE: self._crew_share_fraction()})
        )._plan_workorder(replan=replan)

    def _crew_apply(self, force=False):
        """Сменен брой хора в бригадата ⇒ нов край на поръчката (№145).

        Порасне ли прозорецът, избутването в пистата мести следващите;
        свие ли се — следващите остават на местата си (влакът не тегли
        назад). `duration_expected` не се пипа.
        """
        before = {wo.id: len(wo.employee_assigned_ids) for wo in self}
        res = super()._crew_apply(force=force)
        for wo in self.filtered(
            lambda w: w.crew_share
            and w.date_start
            and w.state in ("pending", "waiting", "ready")
            and len(w.employee_assigned_ids) != before.get(w.id)
        ):
            finish = wo._calculate_date_finished()
            if finish and finish != wo.date_finished:
                wo.with_context(bypass_duration_calculation=True).write(
                    {"date_finished": finish}
                )
        return res

    def _calculate_date_finished(self, date_start=False):
        """Ядрото: краят = началото + duration_expected по календара. Тук —
        прозорецът (duration_expected × коефициента на бригадата)."""
        factor = self._crew_window_factor(date_start)
        workcenter = self.env.context.get("new_workcenter_id") or self.workcenter_id
        if factor >= 1.0:
            if not workcenter.resource_calendar_id:
                return super()._calculate_date_finished(date_start=date_start)
            # Ядрото на 18 (mrp/models/mrp_workorder.py:444-447) подава
            # resource= на plan_hours и така leave-овете на ДРУГИТЕ поръчки в
            # центъра стават неработно време: краят прескача съседа и
            # поръчката се разтяга (1 ч става 2–3 ч). В модула поръчките на
            # центъра не са заетост — пистите и веригата ги местят сами
            # (Р30/Р32, вж. _crew_walk); и ядрото на 19 (:461-464) вече не
            # подава resource. Затова тук се изключват leave-овете на всички
            # поръчки на центъра; останалите (отпуск/поддръжка на ресурса на
            # центъра) се гледат както в ядрото на 18.
            leaves = workcenter._crew_workorder_leaves() | self.leave_id
            domain = [("time_type", "in", ["leave", "other"])]
            if leaves:
                domain.append(("id", "not in", leaves.ids))
            return workcenter.resource_calendar_id.plan_hours(
                self.duration_expected / 60.0,
                date_start or self.date_start,
                compute_leaves=True,
                domain=domain,
                resource=workcenter.resource_id,
            )
        start = date_start or self.date_start
        minutes = self.duration_expected * factor
        if not workcenter.resource_calendar_id:
            return start + timedelta(minutes=minutes)
        return workcenter.resource_calendar_id.plan_hours(
            minutes / 60.0,
            start,
            compute_leaves=True,
            domain=[("time_type", "in", ["leave", "other"])],
        )

    def _calculate_duration_expected(self, date_start=False, date_finished=False):
        """Ядрото: разтегнат прозорец ⇒ duration_expected = прозорецът. Тук —
        прозорецът ÷ коефициента (обратно в човеко-минути)."""
        minutes = super()._calculate_duration_expected(
            date_start=date_start, date_finished=date_finished
        )
        return minutes / self._crew_window_factor(date_start)

    def _cal_cost(self, date=False):
        """Вариант б (ADR-0070, ADR-0069): при дял > 0 costs_hour е на ЧОВЕК,
        както в естимацията ⇒ машинната част е по СБОРА от минутите в
        time_ids. Ядрото брои обединението на интервалите (стенен часовник);
        тук се добавя разликата — EE частта (total_cost на човек) не се пипа."""
        total = super()._cal_cost(date)
        for wo in self.filtered("crew_share"):
            times = [
                t
                for t in wo.time_ids
                if t.date_start and t.date_end and (not date or t.date_end < date)
            ]
            if not times:
                continue
            union = sum_intervals(Intervals([[t.date_start, t.date_end, t] for t in times]))
            summed = sum((t.date_end - t.date_start).total_seconds() for t in times) / 3600.0
            total += (summed - union) * wo.workcenter_id.costs_hour
        return total
