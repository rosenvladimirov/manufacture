# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
import heapq
from datetime import date, datetime, timedelta

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.misc import format_datetime

from .mrp_workcenter_lanes import CREW_LANE_DEFER

# Кои поръчки двигателят мести (M6.3): незапочнати, без отчетено време,
# в МО, която още се произвежда.
CREW_REPLAN_WO_STATES = ("pending", "waiting", "ready")
CREW_REPLAN_MO_STATES = ("confirmed", "progress", "to_close")
# Подразбиращият се период на препланирането (дни след date_from).
CREW_REPLAN_PERIOD_DAYS = 14
# Контекстът на собствените записи на двигателя (M6.7).
CREW_ENGINE = "crew_engine"


class MrpWorkcenterReplanBatch(models.Model):
    """Партида на препланирането (TECH_DESIGN §2, Т6): входните данни,
    снимката на плана преди промяната (редовете и `production_snapshot`) и
    отчетът. Снимката носи всичко нужно за отмяната (фаза 2)."""

    _name = "mrp.workcenter.replan.batch"
    _description = "Work Center Replan Batch"
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(required=True, readonly=True)
    user_id = fields.Many2one(
        "res.users",
        string="Responsible",
        required=True,
        readonly=True,
        default=lambda self: self.env.user,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        index=True,
        default=lambda self: self.env.company,
    )
    source = fields.Selection(
        [
            ("wizard", "Rearrange Plan"),
            ("recompute", "Recompute"),
            ("drop", "Drop Here"),
            ("train", "Train"),
            # Р32 (07.10): запис извън нашия Гант, който избутва пистата.
            ("write", "Direct Edit"),
        ],
        required=True,
        readonly=True,
    )
    params = fields.Json(
        string="Input Data",
        readonly=True,
        help="The input data of the replanning.",
    )
    workcenter_ids = fields.Many2many(
        "mrp.workcenter",
        "mrp_workcenter_replan_batch_workcenter_rel",
        "batch_id",
        "workcenter_id",
        string="Work Centers",
        readonly=True,
    )
    state = fields.Selection(
        [
            ("applied", "Applied"),
            ("undone", "Undone"),
            ("partial", "Partially Undone"),
        ],
        required=True,
        readonly=True,
        default="applied",
    )
    production_snapshot = fields.Json(
        string="Manufacturing Orders Before",
        readonly=True,
        help="The dates of the affected manufacturing orders before the "
        "replanning.",
    )
    report_html = fields.Html(string="Report", readonly=True, sanitize=True)
    line_ids = fields.One2many(
        "mrp.workcenter.replan.batch.line",
        "batch_id",
        string="Work Orders",
        readonly=True,
    )
    crew_can_undo = fields.Boolean(
        string="Can Undo",
        compute="_compute_crew_can_undo",
        help="The current user can undo this replanning: it is applied, it is "
        "not a move of the train, the user is its author or a manufacturing "
        "manager and it moved at least one work order.",
    )

    @api.depends("state", "source", "user_id", "line_ids.result", "line_ids.workorder_id")
    @api.depends_context("uid")
    def _compute_crew_can_undo(self):
        """Видимостта на бутона „Undo“ (фаза 2, §9.13.3). Проверките на
        `action_undo` остават — полето само крие бутона."""
        user = self.env.user
        manager = user.has_group("mrp.group_mrp_manager")
        for batch in self:
            batch.crew_can_undo = (
                batch.state == "applied"
                and batch.source != "train"
                and (manager or batch.user_id == user)
                and any(
                    line.workorder_id and line.result != "unchanged"
                    for line in batch.line_ids
                )
            )

    # ------------------------------------------------------------------
    # Входни данни
    # ------------------------------------------------------------------

    @api.model
    def _crew_default_params(self):
        """Подразбиращите се входни данни (като в съветника, №10)."""
        today = fields.Date.context_today(self)
        return {
            "workcenter_ids": [],
            "date_from": today,
            "date_to": today + timedelta(days=CREW_REPLAN_PERIOD_DAYS),
            "scope": "not_started",
            "priority_key": "deadline",
            # Редът на клиентите при подредба по клиент (id-та подред).
            "partner_ids": [],
            # Филтър по клиент (по id, Ф8); празен — без филтър.
            "partner_filter_ids": [],
            "respect_roster": True,
            "use_alternatives": False,
            # Вътрешен флаг на „Преизчисли“ (M7): само остарелите.
            "only_stale": False,
        }

    @api.model
    def _crew_normalize_params(self, params):
        """Допълва входните данни с подразбиращите се; датите стават date."""
        result = self._crew_default_params()
        result.update({k: v for k, v in (params or {}).items() if v is not None})
        for key in ("date_from", "date_to"):
            result[key] = fields.Date.to_date(result[key])
        if result["date_to"] < result["date_from"]:
            raise UserError(
                self.env._("The end of the period is before its start.")
            )
        return result

    @staticmethod
    def _crew_params_json(params):
        """Входните данни във вид за Json полето (датите — като текст)."""
        return {
            key: fields.Date.to_string(value) if isinstance(value, date) else value
            for key, value in params.items()
        }

    # ------------------------------------------------------------------
    # M6 — двигателят
    # ------------------------------------------------------------------

    @api.model
    def _crew_run(self, params, source):
        """M6: препланира незапочнатите поръчки на центровете по входните
        данни и връща партидата със снимката и отчета.

        1. без FOR UPDATE NOWAIT (№12) — едновременните пускове ги решава
           serialization failure, който Odoo повтаря;
        2. граници T0 = 00:00 местно (tz на календара) на `date_from`;
           now_eff = max(now, T0);
        3–4. кандидатите и редът им (ключ, после Kahn по зависимостите);
        5. снимка; 6. leave-овете на кандидатите се трият;
        7. всяка поръчка в savepoint; 8. датите на МО с force_date;
        9. нарядът се прилага, отчетът се записва.
        """
        params = self._crew_normalize_params(params)
        workcenters = (
            self.env["mrp.workcenter"].browse(params["workcenter_ids"]).exists()
        )
        if not workcenters:
            raise UserError(self.env._("Select at least one work center to replan."))
        now = fields.Datetime.now()
        context = {
            "params": params,
            "now": now,
            "scope_workcenters": workcenters,
            "bounds": {},
            "extra": {},
        }
        candidates = self._crew_candidates(workcenters, params, context)
        ordered = self._crew_order(candidates, params)

        # 5. Снимка: редовете (старият план) и датите на МО.
        productions = ordered.production_id
        batch = self.create(
            {
                "name": "%s %s"
                % (
                    dict(self._fields["source"]._description_selection(self.env))[
                        source
                    ],
                    format_datetime(self.env, now),
                ),
                "source": source,
                "params": self._crew_params_json(params),
                "workcenter_ids": [Command.set(workcenters.ids)],
                "company_id": (workcenters.company_id[:1] or self.env.company).id,
                "production_snapshot": {
                    str(mo.id): {
                        "name": mo.name,
                        "date_start": fields.Datetime.to_string(mo.date_start),
                        "date_finished": fields.Datetime.to_string(mo.date_finished),
                        "is_planned": mo.is_planned,
                    }
                    for mo in productions
                },
            }
        )
        lines = self.env["mrp.workcenter.replan.batch.line"].create(
            [
                {
                    "batch_id": batch.id,
                    "sequence": sequence,
                    "workorder_id": wo.id,
                    "production_id": wo.production_id.id,
                    "old_workcenter_id": wo.workcenter_id.id,
                    "old_date_start": wo.date_start,
                    "old_date_finished": wo.date_finished,
                    "old_duration_expected": wo.duration_expected,
                    "old_lane": wo.crew_lane,
                }
                for sequence, wo in enumerate(ordered, start=1)
            ]
        )

        # 6. Leave-овете на всички кандидати се трият — така кандидатите не
        # си пречат взаимно със стария план. Датите се чистят изрично (като
        # button_unplan на ядрото): иначе при rollback на savepoint в т. 7
        # неуспялата поръчка остава с остаряла date_start без leave.
        ordered.leave_id.unlink()
        ordered.with_context(**{CREW_ENGINE: True, CREW_LANE_DEFER: True}).write(
            {"date_start": False, "date_finished": False}
        )

        # 7. Поръчка по поръчка, всяка в savepoint.
        results = {}
        for wo, line in zip(ordered, lines):
            results[wo.id] = batch._crew_plan_one(wo, context)
            result, message = results[wo.id]
            line.sudo().write(
                {
                    "result": result,
                    "message": message or False,
                    "new_workcenter_id": wo.workcenter_id.id,
                    "new_date_start": wo.date_start,
                    "new_date_finished": wo.date_finished,
                    "new_duration_expected": wo.duration_expected,
                    "new_lane": wo.crew_lane,
                    "reason": False,
                }
            )

        # 8. Датите на МО = min/max на планираните поръчки, с force_date
        # (иначе смяната на date_start прави unplan на МО).
        mo_notes = batch._crew_update_productions(productions, results)

        # 8б. 18.0.1.12.0 (Росен 08.11, вариант „б“): наследниците на ДРУГИ центрове
        # (извън препланираните) се избутват след препланираните — монтажът
        # след цеха; през M17 на наследника (своята писта, веригата и неговите
        # зависими), отстъпът е `_crew_dependency_gap`. Отказ — бележка в отчета.
        mo_notes += batch._crew_push_foreign_successors(ordered.exists(), workcenters)

        # 9. Нарядът към засегнатите поръчки; отчетът.
        ordered.exists()._crew_apply()
        batch.sudo().report_html = batch._crew_report_html(mo_notes)
        if ordered:
            self.env["mrp.workcenter.lane.lock"]._crew_lane_notify(
                workcenters,
                "changed",
                {
                    "workcenter_ids": workcenters.ids,
                    "workorder_ids": ordered.exists().ids,
                    "source": "engine",
                },
            )
        return batch

    def _crew_push_foreign_successors(self, moved, workcenters):
        """Наследниците на `moved` на центрове извън `workcenters`, които сега
        почват преди края на предшественика (+ отстъпа) — избутват се (M17).
        Започнатите и отказите остават бележки (конфликтът мига, Р33)."""
        notes = []
        done = set()
        for workorder in moved.sorted(lambda wo: (wo.date_finished or wo.create_date, wo.id)):
            if not workorder.date_finished:
                continue
            for successor in workorder.needed_by_workorder_ids:
                if (successor.id in done or successor.workcenter_id in workcenters
                        or successor.state not in CREW_REPLAN_WO_STATES
                        or successor._crew_is_started()):
                    continue
                ready = workorder.date_finished + successor._crew_dependency_gap(workorder)
                if not successor.date_start or successor.date_start >= ready:
                    continue
                done.add(successor.id)
                try:
                    with self.env.cr.savepoint():
                        result = successor.crew_drop(
                            successor.workcenter_id.id, successor.crew_lane or 1, date_start=ready
                        )
                        self._crew_adopt_batch(self.browse(result.get("batch_id")))
                except UserError as err:
                    notes.append(self.env._(
                        "%(wo)s was not moved after %(pred)s: %(reason)s",
                        wo=successor.display_name, pred=workorder.display_name, reason=str(err),
                    ))
        return notes

    def _crew_adopt_batch(self, other):
        """Ходовете на друга партида (M17 на избутания наследник) стават редове
        на тази — „Undo“ на пренареждането връща и тях (Клаудио, №199: монтажите
        оставаха на новото място). Снимката на МО се допълва; другата се трие."""
        self.ensure_one()
        other = other.exists()
        if not other or other == self:
            return
        last = max(self.line_ids.mapped("sequence") or [0])
        for offset, line in enumerate(other.line_ids.sorted("sequence"), start=1):
            line.sudo().write({"batch_id": self.id, "sequence": last + offset})
        snapshot = dict(self.production_snapshot or {})
        for mo_id, dates in (other.production_snapshot or {}).items():
            snapshot.setdefault(mo_id, dates)
        self.sudo().write({
            "production_snapshot": snapshot,
            "workcenter_ids": [Command.link(wc.id) for wc in other.workcenter_ids],
        })
        other.sudo().unlink()

    @api.model
    def _crew_bounds(self, workcenter, context):
        """(T0, край на периода, now_eff) за центъра — UTC без tz.

        T0 е 00:00 местно на `date_from`, краят — 00:00 местно на деня след
        `date_to` (по tz на календара на центъра)."""
        bounds = context["bounds"]
        if workcenter.id not in bounds:
            params = context["params"]
            start, stop = workcenter._crew_period_bounds(
                params["date_from"], params["date_to"]
            )
            bounds[workcenter.id] = (start, stop, max(context["now"], start))
        return bounds[workcenter.id]

    @api.model
    def _crew_candidates(self, workcenters, params, context):
        """M6.3: поръчките, които двигателят мести."""
        workorders = self.env["mrp.workorder"].search(
            [
                ("workcenter_id", "in", workcenters.ids),
                ("state", "in", CREW_REPLAN_WO_STATES),
                ("production_id.state", "in", CREW_REPLAN_MO_STATES),
                ("time_ids", "=", False),
            ]
        )
        if params["scope"] == "late":
            workorders = workorders.filtered("is_late")
        # Периодът почва по-късно от сега (Гантът е превъртян напред):
        # планираните между сега и началото му не се пипат — човек
        # пренарежда само периода (находка 1, 1.6.0). Остарелите (начало
        # преди сега) и непланираните остават кандидати.
        workorders = workorders.filtered(
            lambda wo: not (wo.leave_id and wo.date_start)
            or wo.date_start < context["now"]
            or wo.date_start >= self._crew_bounds(wo.workcenter_id, context)[0]
        )
        if params["only_stale"]:
            # „Преизчисли“ (SPEC §6.4): само започващите преди днес или
            # непланираните.
            workorders = workorders.filtered(
                lambda wo: not (wo.leave_id and wo.date_start)
                or wo.date_start < self._crew_bounds(wo.workcenter_id, context)[0]
            )
        if params["partner_filter_ids"]:
            allowed = set(params["partner_filter_ids"])
            workorders = workorders.filtered(
                lambda wo: wo._crew_partner().id in allowed
            )
        return workorders.filtered(lambda wo: not wo._crew_started_successor())

    @api.model
    def _crew_sort_key(self, workorder, params):
        """M6.4: ключът по `priority_key`, после срокът на МО (празните
        отзад), приоритетът на МО (по-високият напред), id."""
        production = workorder.production_id
        deadline = production.date_deadline
        priority = -int(production.priority or 0)
        key = params["priority_key"]
        if key == "mo_priority":
            primary = (priority,)
        elif key == "partner":
            partner = workorder._crew_partner()
            order = params["partner_ids"] or []
            if not partner:
                # Без клиент — накрая (И7).
                primary = (2, len(order), "")
            elif partner.id in order:
                primary = (0, order.index(partner.id), "")
            else:
                primary = (1, len(order), partner.display_name or "")
        elif key == "create_date":
            primary = (production.create_date or datetime.max,)
        else:
            primary = (not deadline, deadline or datetime.max)
        return primary + (not deadline, deadline or datetime.max, priority, workorder.id)

    @api.model
    def _crew_order(self, workorders, params):
        """M6.4: подредба по ключа и топологична корекция с Kahn върху
        `blocked_by_workorder_ids` в рамките на кандидатите — предшественикът
        винаги е преди наследника; иначе редът е по ключа."""
        keys = {wo.id: self._crew_sort_key(wo, params) for wo in workorders}
        by_id = {wo.id: wo for wo in workorders}
        predecessors = {
            wo.id: {p.id for p in wo.blocked_by_workorder_ids if p.id in by_id}
            for wo in workorders
        }
        successors = {wo_id: set() for wo_id in by_id}
        for wo_id, preds in predecessors.items():
            for pred_id in preds:
                successors[pred_id].add(wo_id)
        indegree = {wo_id: len(preds) for wo_id, preds in predecessors.items()}
        heap = [(keys[wo_id], wo_id) for wo_id, degree in indegree.items() if not degree]
        heapq.heapify(heap)
        ordered = []
        while heap:
            _key, wo_id = heapq.heappop(heap)
            ordered.append(wo_id)
            for succ_id in successors[wo_id]:
                indegree[succ_id] -= 1
                if not indegree[succ_id]:
                    heapq.heappush(heap, (keys[succ_id], succ_id))
        # Цикъл не може да има (ограничение на ядрото), но за всеки случай
        # останалите отиват накрая по ключа.
        rest = sorted(set(by_id) - set(ordered), key=lambda wo_id: keys[wo_id])
        return self.env["mrp.workorder"].browse(ordered + rest)

    def _crew_extra_slots(self, workcenter, context):
        """M6.7: заетите интервали на центъра освен другите поръчки —
        (затворените смени при `respect_roster`, Р25; речник писта →
        заетостта на поръчките в progress с изтекъл край, §9.3 M6)."""
        extra = context["extra"]
        if workcenter.id not in extra:
            params = context["params"]
            closed = []
            if params["respect_roster"]:
                closed = workcenter._crew_closed_shift_slots(
                    params["date_from"], params["date_to"]
                )
            extra[workcenter.id] = (
                closed,
                workcenter._crew_progress_slots(context["now"], by_lane=True),
            )
        return extra[workcenter.id]

    def _crew_plan_one(self, workorder, context):
        """M6.7 за една поръчка, в savepoint. Връща (резултат, съобщение).

        При ValidationError/UserError (Ф4) savepoint-ът се връща: поръчката
        остава НЕПЛАНИРАНА (leave-ът ѝ е изтрит в т. 6), резултатът е
        `failed`. Старите дати не се възстановяват — старият слот може вече
        да е зает."""
        self.ensure_one()
        params = context["params"]
        try:
            with self.env.cr.savepoint():
                end = self._crew_plan_write(workorder, context)
        except (ValidationError, UserError) as error:
            return "failed", str(error.args[0] if error.args else error)
        if end > self._crew_bounds(workorder.workcenter_id, context)[1]:
            return "outside_period", self.env._(
                "Planned after the end of the period %(date)s.",
                date=fields.Date.to_string(params["date_to"]),
            )
        line = self.line_ids.filtered(lambda line: line.workorder_id == workorder)
        if (
            line.old_workcenter_id == workorder.workcenter_id
            and line.old_date_start == workorder.date_start
            and line.old_date_finished == workorder.date_finished
            and line.old_lane == workorder.crew_lane
        ):
            return "unchanged", False
        return "moved", False

    def _crew_plan_write(self, workorder, context):
        """Търсенето на слот и записът на две стъпки. Връща новия край."""
        params = context["params"]
        # 18.0.1.12.4: предшественикът дава начало през `_crew_earliest_after`
        # (състоянието + отстъпа), а не през голото `date_finished`. Който не
        # дава основа, спира планирането — Ф4 го връща като `failed` с бележка,
        # вместо поръчката да легне пред непланиран или незавършен цех.
        starts = [workorder._crew_replan_earliest(params) or datetime.min]
        blocking = self.env["mrp.workorder"]
        for pred in workorder.blocked_by_workorder_ids:
            if pred.state == "cancel":
                continue
            after = workorder._crew_earliest_after(pred)
            if after:
                starts.append(after)
            else:
                blocking |= pred
        if blocking:
            raise UserError(
                self.env._(
                    "The preceding operations are not finished and their dates"
                    " cannot be used: %(blocking)s.",
                    blocking=", ".join(
                        "%s (%s, %s)"
                        % (
                            pred.display_name,
                            pred.state,
                            format_datetime(self.env, pred.date_finished)
                            if pred.date_finished
                            else self.env._("not planned"),
                        )
                        for pred in blocking
                    ),
                )
            )
        earliest = max(starts)
        workcenters = workorder.workcenter_id
        if params["use_alternatives"]:
            workcenters |= (
                workorder.workcenter_id.alternative_workcenter_ids
                & context["scope_workcenters"]
            )
        best = None
        errors = []
        for workcenter in workcenters:
            if not workcenter.resource_calendar_id:
                errors.append(
                    self.env._(
                        "There is no working schedule on the work center %(wc)s.",
                        wc=workcenter.display_name,
                    )
                )
                continue
            if workcenter == workorder.workcenter_id:
                duration = workorder.duration_expected
            else:
                duration = workorder._get_duration_expected(
                    alternative_workcenter=workcenter
                )
            start = max(self._crew_bounds(workcenter, context)[2], earliest)
            closed, by_lane = self._crew_extra_slots(workcenter, context)
            # §9.3 M6: най-рано свободната писта; започната с изтекъл край
            # блокира само своята писта.
            lane, date_from, date_to = workorder._crew_with_share(
                workcenter
            )._crew_first_slot_lanes(
                start, duration, extra_leaves_slots=closed, extra_by_lane=by_lane
            )
            if not lane:
                errors.append(date_to)
                continue
            if best is None or date_to < best[2]:
                best = (workcenter, date_from, date_to, duration, lane)
        if best is None:
            raise UserError(
                "\n".join(errors)
                or self.env._("Impossible to plan the work order %(wo)s.",
                              wo=workorder.display_name)
            )
        workcenter, date_from, date_to, duration, lane = best
        engine = workorder.with_context(**{CREW_ENGINE: True, CREW_LANE_DEFER: True})
        # (а) центърът — докато поръчката е без leave (ядрото тогава не
        # преизчислява датите).
        if workcenter != workorder.workcenter_id:
            engine.write({"workcenter_id": workcenter.id})
        # (б) leave, продължителност и писта с bypass_duration_calculation;
        # M15 се пуска за поръчката в savepoint-а ѝ (§9.3 M6).
        leave = (
            self.env["resource.calendar.leaves"]
            .with_context(**{CREW_LANE_DEFER: True})
            .create(
            {
                "name": workorder.display_name,
                "calendar_id": workcenter.resource_calendar_id.id,
                "date_from": date_from,
                "date_to": date_to,
                "resource_id": workcenter.resource_id.id,
                "time_type": "other",
            }
            )
        )
        engine.with_context(bypass_duration_calculation=True).write(
            {"leave_id": leave.id, "duration_expected": duration, "crew_lane": lane}
        )
        workorder._crew_check_lane_overlap()
        return workorder.date_finished

    def _crew_update_productions(self, productions, results):
        """M6.8: датите на МО = min/max на планираните ѝ поръчки
        (`force_date=True`). Връща бележките за отчета (Ф10)."""
        notes = []
        snapshot = self.production_snapshot or {}
        for production in productions:
            planned = production.workorder_ids.filtered(
                lambda wo: wo.state not in ("done", "cancel") and wo.leave_id
            )
            failed = production.workorder_ids.filtered(
                lambda wo: results.get(wo.id, ("",))[0] == "failed"
            )
            if planned:
                production.with_context(force_date=True).write(
                    {
                        "date_start": min(planned.mapped("date_start")),
                        "date_finished": max(planned.mapped("date_finished")),
                    }
                )
            if failed:
                notes.append(
                    self.env._(
                        "%(mo)s: the work order(s) %(wo)s could not be planned; "
                        "the end of the manufacturing order is computed, not "
                        "planned.",
                        mo=production.display_name,
                        wo=", ".join(failed.mapped("name")),
                    )
                )
            old = snapshot.get(str(production.id), {})
            if old.get("date_start") != fields.Datetime.to_string(
                production.date_start
            ):
                notes.append(
                    self.env._(
                        "%(mo)s: the start changed; the dates of the component "
                        "moves follow it.",
                        mo=production.display_name,
                    )
                )
        return notes

    # ------------------------------------------------------------------
    # Отчет
    # ------------------------------------------------------------------

    def _crew_report_html(self, mo_notes=None, split_results=None):
        """Отчетът: поръчките (стар → нов план, резултат), бележките за МО
        и — при „Преизчисли“ — разделянето на приключените (M7.3)."""
        self.ensure_one()
        result_labels = dict(
            self.env["mrp.workcenter.replan.batch.line"]
            ._fields["result"]
            ._description_selection(self.env)
        )

        def when(value):
            return format_datetime(self.env, value) if value else "—"

        rows = Markup("").join(
            Markup(
                "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                "<td>%s</td><td>%s</td></tr>"
            )
            % (
                line.workorder_id.display_name or "",
                line.old_workcenter_id.display_name or "",
                when(line.old_date_start),
                line.new_workcenter_id.display_name or "",
                when(line.new_date_start),
                when(line.new_date_finished),
                Markup("%s%s")
                % (
                    result_labels.get(line.result, line.result or ""),
                    Markup(": %s") % line.message if line.message else "",
                ),
            )
            for line in self.line_ids
        )
        html = Markup("<p>%s</p>") % self.env._(
            "%(count)s work order(s) considered.", count=len(self.line_ids)
        )
        if self.line_ids:
            html += Markup(
                "<table class='table table-sm'><thead><tr><th>%s</th><th>%s</th>"
                "<th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr>"
                "</thead><tbody>%s</tbody></table>"
            ) % (
                self.env._("Work Order"),
                self.env._("Old Work Center"),
                self.env._("Old Start"),
                self.env._("New Work Center"),
                self.env._("New Start"),
                self.env._("New End"),
                self.env._("Result"),
                rows,
            )
        if mo_notes:
            html += Markup("<h5>%s</h5><ul>%s</ul>") % (
                self.env._("Manufacturing Orders"),
                Markup("").join(Markup("<li>%s</li>") % note for note in mo_notes),
            )
        if split_results is not None:
            html += self._crew_split_report_html(split_results)
        return html

    def _crew_split_report_html(self, split_results):
        """M7.3: резултатът от разделянето на приключените поръчки."""
        labels = {
            "split": self.env._("Split among the crew"),
            "unchanged": self.env._("Unchanged"),
            "no_crew": self.env._("No crew roster for the shift"),
            "no_time": self.env._("No time to split"),
            "no_shift": self.env._("No shift in the working schedule"),
            "mo_done": self.env._("Skipped: the manufacturing order is done"),
            "posted": self.env._("Skipped: the time is already posted"),
        }
        workorders = self.env["mrp.workorder"].browse(list(split_results))
        items = Markup("").join(
            Markup("<li>%s: %s</li>")
            % (wo.display_name, labels.get(split_results[wo.id], split_results[wo.id]))
            for wo in workorders
        )
        return Markup("<h5>%s</h5>%s") % (
            self.env._("Finished Work Orders of the Day"),
            Markup("<ul>%s</ul>") % items
            if items
            else Markup("<p>%s</p>") % self.env._("None."),
        )

    def _crew_add_split_report(self, split_results):
        """Добавя разделянето (M7.3) към отчета на партидата."""
        self.ensure_one()
        self.sudo().report_html = (
            Markup(self.report_html or "") + self._crew_split_report_html(split_results)
        )

    # ------------------------------------------------------------------
    # Партиди `drop` (M17), `train` (M18) и `write` (Р32, 1.5.3) — ходове,
    # записани от плана
    # ------------------------------------------------------------------

    @api.model
    def _crew_record_moves(self, source, moves, workcenters, snapshot=None):
        """Партидата на вече записаните ходове: старото е от плана (`moves`),
        новото — от поръчката. `snapshot` = {МО: (начало, край)} преди
        записа (иначе — текущите дати на МО)."""
        snapshot = snapshot or {}
        workorders = self.env["mrp.workorder"].union(*[m["workorder"] for m in moves])
        productions = workorders.production_id
        now = fields.Datetime.now()

        def mo_dates(production):
            start, stop = snapshot.get(
                production.id, (production.date_start, production.date_finished)
            )
            return {
                "name": production.name,
                "date_start": fields.Datetime.to_string(start),
                "date_finished": fields.Datetime.to_string(stop),
                "is_planned": production.is_planned,
            }

        batch = self.create(
            {
                "name": "%s %s"
                % (
                    dict(self._fields["source"]._description_selection(self.env))[
                        source
                    ],
                    format_datetime(self.env, now),
                ),
                "source": source,
                "params": {},
                "workcenter_ids": [Command.set(workcenters.ids)],
                "company_id": (workcenters.company_id[:1] or self.env.company).id,
                "production_snapshot": {
                    str(mo.id): mo_dates(mo) for mo in productions
                },
            }
        )
        self.env["mrp.workcenter.replan.batch.line"].create(
            [
                {
                    "batch_id": batch.id,
                    "sequence": sequence,
                    "workorder_id": move["workorder"].id,
                    "production_id": move["workorder"].production_id.id,
                    "old_workcenter_id": move["old_workcenter"].id,
                    "old_date_start": move["old_date_start"],
                    "old_date_finished": move["old_date_finished"],
                    "old_duration_expected": move.get(
                        "old_duration", move["workorder"].duration_expected
                    ),
                    "old_lane": move["old_lane"],
                    "new_workcenter_id": move["workorder"].workcenter_id.id,
                    "new_date_start": move["workorder"].date_start,
                    "new_date_finished": move["workorder"].date_finished,
                    "new_duration_expected": move["workorder"].duration_expected,
                    "new_lane": move["workorder"].crew_lane,
                    "result": "moved",
                    "reason": move["reason"],
                }
                for sequence, move in enumerate(moves, start=1)
            ]
        )
        return batch

    def _crew_finish_moves(self, workorders, notes=None):
        """След записа на ходовете: датите на МО (`force_date`), нарядът
        (денят може да се смени, 17.11) и отчетът."""
        self.ensure_one()
        mo_notes = self._crew_update_productions(workorders.production_id, {})
        workorders.exists()._crew_apply()
        self.sudo().report_html = self._crew_report_html(list(notes or []) + mo_notes)

    # ------------------------------------------------------------------
    # Отмяна (M6, отмяна; С7 — изтеглена в 6б.1 за пускането)
    # ------------------------------------------------------------------

    def action_undo(self):
        """Връща плана от снимката: центъра, датите, продължителността и
        пистата на поръчките и датите на МО.

        - само авторът или мениджърът; партида `train` не се отменя;
        - ред, чиято поръчка е започната или е местена след партидата
          (полетата на плана ≠ новите), се пропуска (Ф7);
        - ред `unchanged` не се пипа и не е пропуск (партидата не го е
          местила);
        - МО получава датите от снимката само ако всичките ѝ поръчки от
          партидата са на мястото си; иначе — min/max на планираните (M6.8);
        - отменимите се вдигат от пистите (leave-ът се трие), после се
          връщат по възходящо старо начало (Ф4), всяка в savepoint с M15;
          неуспялата се връща на новото място и редът е пропуснат.
        """
        self.ensure_one()
        if self.state != "applied":
            raise UserError(self.env._("This replanning is already undone."))
        if self.source == "train":
            raise UserError(self.env._("The moves of the train cannot be undone."))
        if self.user_id != self.env.user and not self.env.user.has_group(
            "mrp.group_mrp_manager"
        ):
            raise AccessError(
                self.env._(
                    "Only the author of the replanning or a manufacturing "
                    "manager can undo it."
                )
            )
        lines = self.line_ids.filtered("workorder_id")
        skipped = {}
        restorable = self.env["mrp.workcenter.replan.batch.line"]
        # МО, чиито поръчки НЕ са на мястото си от партидата: те не получават
        # датите от снимката, а min/max на планираните си поръчки (M6.8).
        drifted = self.env["mrp.production"]
        for line in lines:
            reason = line._crew_undo_conflict()
            if line.result == "unchanged":
                # Партидата не я е местила — няма какво да се връща и не е
                # пропуск (находка 2, 1.6.0); местена след това → МО по M6.8.
                if reason:
                    drifted |= line.workorder_id.production_id
            elif reason:
                skipped[line.id] = reason
            else:
                restorable |= line
        workorders = restorable.workorder_id
        lifting = workorders.with_context(**{CREW_ENGINE: True, CREW_LANE_DEFER: True})
        workorders.leave_id.unlink()
        lifting.write({"date_start": False, "date_finished": False})
        for line in restorable.sorted(
            lambda line: (line.old_date_start or datetime.max, line.sequence, line.id)
        ):
            try:
                with self.env.cr.savepoint():
                    line._crew_undo_write(old=True)
            except (UserError, ValidationError) as error:
                skipped[line.id] = str(error.args[0] if error.args else error)
                try:
                    with self.env.cr.savepoint():
                        line._crew_undo_write(old=False)
                except (UserError, ValidationError):
                    pass
        # Находка 3 (1.6.0): МО с пропусната поръчка — по M6.8, не от снимката
        # (иначе началото ѝ е там, където поръчката вече не е).
        drifted |= lines.filtered(lambda line: line.id in skipped).workorder_id.production_id
        drifted = drifted.exists()
        self._crew_update_productions(drifted, {})
        for mo_id, old in (self.production_snapshot or {}).items():
            production = self.env["mrp.production"].browse(int(mo_id)).exists()
            if production in drifted:
                continue
            if production and old.get("date_start") and old.get("date_finished"):
                production.with_context(force_date=True).write(
                    {
                        "date_start": fields.Datetime.to_datetime(old["date_start"]),
                        "date_finished": fields.Datetime.to_datetime(
                            old["date_finished"]
                        ),
                    }
                )
        workorders.exists()._crew_apply()
        for line in lines:
            if line.id in skipped:
                line.sudo().write({"result": "skipped", "message": skipped[line.id]})
        self.sudo().write({"state": "partial" if skipped else "undone"})
        self.env["mrp.workcenter.lane.lock"]._crew_lane_notify(
            self.workcenter_ids,
            "changed",
            {
                "workcenter_ids": self.workcenter_ids.ids,
                "workorder_ids": workorders.exists().ids,
                "source": "undo",
            },
        )
        return True

    def action_undo_report(self):
        """Бутонът „Undo“ във формата на партидата: отменя и отваря отчета
        наново. Отчетът е диалог (Recompute, съветникът, Гантът), а `True`
        от бутон в диалог го затваря (`act_window_close`) — така човек вижда
        новото състояние, а `onClose` на Ганта минава към новия диалог."""
        self.ensure_one()
        self.action_undo()
        return self._crew_action_open()

    def action_open_report(self):
        """Публичният двойник на `_crew_action_open` — за Ганта (RPC не вика
        методи с `_`)."""
        self.ensure_one()
        return self._crew_action_open()

    def _crew_action_open(self):
        """Отваря партидата (отчета).

        `views` е изрично: Гантът взима действието през `call_kw`
        (`action_crew_recompute`, `action_open_report`), а там — за разлика от
        `call_button` — `clean_action` не го попълва от `view_mode`; без него
        `doAction` пада в `_preprocessAction` (`action.views.map`).
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
        }


class MrpWorkcenterReplanBatchLine(models.Model):
    """Ред на партидата: една поръчка — старият и новият план, резултатът."""

    _name = "mrp.workcenter.replan.batch.line"
    _description = "Work Center Replan Batch Line"
    _order = "batch_id, sequence, id"

    batch_id = fields.Many2one(
        "mrp.workcenter.replan.batch",
        string="Batch",
        required=True,
        index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        related="batch_id.company_id", store=True, index=True, precompute=True
    )
    sequence = fields.Integer(help="Order in which the work order was planned.")
    workorder_id = fields.Many2one(
        "mrp.workorder", string="Work Order", index=True, ondelete="set null"
    )
    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order", ondelete="set null"
    )
    old_workcenter_id = fields.Many2one(
        "mrp.workcenter", string="Old Work Center", ondelete="set null"
    )
    old_date_start = fields.Datetime(string="Old Start")
    old_date_finished = fields.Datetime(string="Old End")
    old_duration_expected = fields.Float(string="Old Expected Duration")
    new_workcenter_id = fields.Many2one(
        "mrp.workcenter", string="New Work Center", ondelete="set null"
    )
    new_date_start = fields.Datetime(string="New Start")
    new_date_finished = fields.Datetime(string="New End")
    new_duration_expected = fields.Float(string="New Expected Duration")
    result = fields.Selection(
        [
            ("moved", "Moved"),
            ("unchanged", "Unchanged"),
            ("failed", "Failed"),
            ("outside_period", "Outside the Period"),
            ("skipped", "Skipped"),
        ]
    )
    message = fields.Text()
    old_lane = fields.Integer(string="Old Lane", aggregator=None)
    new_lane = fields.Integer(string="New Lane", aggregator=None)
    reason = fields.Selection(
        [
            ("drop", "Dropped"),
            ("chain", "Pushed by the Chain"),
            ("dependency", "Pushed as a Dependency"),
            ("train", "Moved by the Train"),
            ("write", "Edited Directly"),
        ],
        help="Why the work order moved: dropped by hand, pushed by the work "
        "order before it in the lane, pushed as a dependent operation, moved "
        "by the train of time, or edited directly outside the work center "
        "planning.",
    )

    def _crew_undo_conflict(self):
        """Причината редът да НЕ се отмени, или False (Ф7: по полетата на
        плана, не по `write_date`)."""
        self.ensure_one()
        wo = self.workorder_id
        if wo.state not in CREW_REPLAN_WO_STATES or wo.time_ids:
            return self.env._("The work order has started.")
        if self.result == "failed":
            return (
                self.env._("The work order was planned after the replanning.")
                if wo.leave_id
                else False
            )
        if (
            wo.workcenter_id != self.new_workcenter_id
            or wo.date_start != self.new_date_start
            or wo.date_finished != self.new_date_finished
            or (self.new_lane and wo.crew_lane != self.new_lane)
        ):
            return self.env._("The work order was moved after the replanning.")
        return False

    def _crew_undo_write(self, old=True):
        """Слага поръчката на старото (или новото) място: центърът, leave с
        датите, продължителността и пистата; после M15."""
        self.ensure_one()
        wo = self.workorder_id
        prefix = "old_" if old else "new_"
        workcenter = self[prefix + "workcenter_id"] or wo.workcenter_id
        start = self[prefix + "date_start"]
        stop = self[prefix + "date_finished"]
        duration = self[prefix + "duration_expected"] or wo.duration_expected
        lane = self[prefix + "lane"] or 1
        engine = wo.with_context(**{CREW_ENGINE: True, CREW_LANE_DEFER: True})
        if workcenter != wo.workcenter_id:
            engine.write({"workcenter_id": workcenter.id})
        if start and stop:
            leave = (
                self.env["resource.calendar.leaves"]
                .with_context(**{CREW_LANE_DEFER: True})
                .create(
                    {
                        "name": wo.display_name,
                        "calendar_id": workcenter.resource_calendar_id.id,
                        "date_from": start,
                        "date_to": stop,
                        "resource_id": workcenter.resource_id.id,
                        "time_type": "other",
                    }
                )
            )
            engine.with_context(bypass_duration_calculation=True).write(
                {"leave_id": leave.id, "duration_expected": duration, "crew_lane": lane}
            )
        else:
            engine.write({"duration_expected": duration, "crew_lane": lane})
        wo._crew_check_lane_overlap()
