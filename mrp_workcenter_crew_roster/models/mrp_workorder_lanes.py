# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Пистите в работната поръчка (SPEC Р29–Р38, ADR 0002, TECH_DESIGN §9):
полетата, инвариантът И-П и проверката M15, M14.3–M14.6, M16 (вместо M10),
M17 `crew_drop` + Р33, конфликтът по зависимостите (Р33 изменено, 1.5.5),
M21 и M22."""
import logging

from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools.sql import create_index
from odoo.exceptions import UserError, ValidationError
from odoo.tools import SQL
from odoo.tools.misc import format_datetime

from .mrp_workcenter_lanes import (
    CREW_GAP,
    CREW_LANE_DEFER,
    CREW_LANE_STATES,
    CREW_TRAIN,
    CREW_TRAIN_MO_STATES,
)

_logger = logging.getLogger(__name__)

# Полетата на плана: промяната им пуска M15 (и M14.3 без `crew_lane`).
CREW_LANE_PLAN_FIELDS = {
    "date_start",
    "date_finished",
    "leave_id",
    "workcenter_id",
    "crew_lane",
}
# Флагът на влаченето в нашия Гант (crew_gantt_model.js, `_reschedule`):
# от 1.5.0 значи „запис от влачене или resize“ (M16).
CREW_GANTT_DRAG = "crew_gantt_drag"
# Записът на leave-а идва от запис/създаване/планиране на поръчка — куката
# в resource.calendar.leaves не проверява (поръчката проверява сама).
CREW_LANE_WO_WRITE = "crew_lane_wo_write"
# Р32 (изменено 07.10, 19.0.1.5.3): полетата, чийто запис извън нашия
# Гант избутва незапочнатите в пистата.
CREW_PUSH_FIELDS = {"date_start", "date_finished", "workcenter_id"}
# Външният create/write ще избута и провери сам (M14.3 + M15): вложените
# записи вътре в него (напр. `leave_id` от inverse-а на датите в ядрото) не
# проверяват — иначе отказват застъпването, преди избутването да е станало.
# Стойност: True (create — новите записи) или кортеж от id (write).
CREW_PUSH_PENDING = "crew_push_pending"
# Колко хода най-много смята каскадата на M17 (предпазител).
CREW_DROP_MAX_STEPS = 5000


def _dt(value):
    return fields.Datetime.to_string(value) if value else False


class MrpWorkorderLanes(models.Model):
    _inherit = "mrp.workorder"

    crew_lane = fields.Integer(
        string="Lane",
        required=True,
        default=1,
        copy=False,
        aggregator=None,
        help="The lane of the work center in which the work order runs. Work "
        "orders in the same lane never overlap.",
    )
    crew_planned_finish = fields.Datetime(
        string="Planned End at Start",
        readonly=True,
        copy=False,
        help="The planned end of the work order when it was started; the "
        "stretch is counted from it.",
    )
    crew_stretch_hours = fields.Float(
        string="Stretch (Hours)",
        readonly=True,
        copy=False,
        help="Working hours the started work order runs past its planned end "
        "at start.",
    )
    crew_stretch_alert_level = fields.Integer(
        string="Stretch Alert Level",
        readonly=True,
        copy=False,
        default=0,
    )
    crew_dep_conflict_since = fields.Datetime(
        string="Dependency Conflict Since",
        readonly=True,
        copy=False,
    )
    # 19.0.1.5.2: от кога записът на влака за тази поръчка се отказва
    # (чуждо ограничение) — пази от повторна бележка и казва на проекцията
    # M22, че вагонът стои на мястото си.
    crew_train_refused_since = fields.Datetime(
        string="Train Refused Since",
        readonly=True,
        copy=False,
        help="Since when the train cannot move this work order because its "
        "new dates are refused; it stays in place until the cause is removed.",
    )
    crew_is_overstretched = fields.Boolean(
        string="Overstretched",
        compute="_compute_crew_is_overstretched",
        help="The started work order runs past its planned end for longer "
        "than the maximum stretch of the work center.",
    )
    # 19.0.1.5.5 (Р33 изменено, Росен 07.10): зависимостите не спират
    # местенето и не се избутват — конфликтът се вижда (мига в Ганта).
    crew_dep_conflict = fields.Boolean(
        string="Dependency Conflict",
        compute="_compute_crew_dep_conflict",
        help="The work order starts before a work order it depends on "
        "ends, or ends after a work order that depends on it starts. Both "
        "work orders are highlighted in the planning until the dates are "
        "fixed.",
    )

    # 19.0.1.9.0 (Росен 12.10.2026): докато се дърпа върху машините,
    # картинката се разпъва и свива по скоростта на машината под нея.
    crew_center_durations = fields.Json(
        string="Duration per Work Center",
        compute="_compute_crew_center_durations",
        help="Expected duration in minutes on the work center of the work "
        "order and on each of its alternatives, as the drop computes it.",
    )

    def init(self):
        # В 18 няма models.Index — индексът на пистата се създава тук.
        super().init()
        create_index(
            self.env.cr,
            "mrp_workorder_crew_lane_idx",
            self._table,
            ["workcenter_id", "crew_lane", "date_start"],
        )

    @api.depends("duration_expected", "workcenter_id")
    def _compute_crew_center_durations(self):
        """Минутите на поръчката върху центъра ѝ и върху алтернативите му.

        Същата сметка като пускането на друга машина (`crew_drop`, 1.):
        центърът — `duration_expected`; алтернативата — `_get_duration_expected`
        с нея. Гантът ги ползва само за картинката докато се дърпа; мястото
        и времето ги решава пускането.
        """
        for wo in self:
            durations = {}
            if wo.workcenter_id and wo.state not in ("done", "cancel"):
                durations[str(wo.workcenter_id.id)] = wo.duration_expected
                for alternative in wo.workcenter_id.alternative_workcenter_ids:
                    durations[str(alternative.id)] = wo._get_duration_expected(
                        alternative_workcenter=alternative
                    )
            wo.crew_center_durations = durations

    @api.depends("crew_stretch_hours", "workcenter_id.crew_max_stretch_hours")
    def _compute_crew_is_overstretched(self):
        for wo in self:
            wo.crew_is_overstretched = bool(
                wo.workcenter_id and wo.workcenter_id._crew_is_over(wo.crew_stretch_hours)
            )

    @api.depends(
        "state",
        "date_start",
        "date_finished",
        "blocked_by_workorder_ids.state",
        "blocked_by_workorder_ids.date_finished",
        "needed_by_workorder_ids.state",
        "needed_by_workorder_ids.date_start",
    )
    def _compute_crew_dep_conflict(self):
        """Р33 (изменено 07.10): конфликт по зависимост = поръчката почва
        преди края на свой отворен предшественик или свършва след началото
        на свой отворен наследник. Без съхранение: флагът изчезва, щом
        датите се оправят — от който и да е запис. Сравнението е до цяла
        секунда, като M15 (Н8)."""
        for wo in self:
            wo.crew_dep_conflict = bool(wo._crew_dep_conflicts())

    def _crew_dep_conflicts(self):
        """Отворените зависимости на поръчката, с които датите ѝ са в
        конфликт (Р33 изменено): [(предшественик, наследник)]."""
        self.ensure_one()
        if self.state not in CREW_LANE_STATES or not (
            self.date_start and self.date_finished
        ):
            return []
        start = self.date_start.replace(microsecond=0)
        stop = self.date_finished.replace(microsecond=0)
        pairs = []
        for predecessor in self.blocked_by_workorder_ids:
            if (
                predecessor.state in CREW_LANE_STATES
                and predecessor.date_start
                and predecessor.date_finished
                and predecessor.date_finished.replace(microsecond=0) > start
            ):
                pairs.append((predecessor, self))
        for successor in self.needed_by_workorder_ids:
            if (
                successor.state in CREW_LANE_STATES
                and successor.date_start
                and successor.date_finished
                and successor.date_start.replace(microsecond=0) < stop
            ):
                pairs.append((self, successor))
        return pairs

    def _crew_is_started(self):
        """„Започната“ = в progress или има отчетено време (М13)."""
        self.ensure_one()
        return self.state == "progress" or bool(self.time_ids)

    # ------------------------------------------------------------------
    # M15 — проверката на инварианта И-П (Р30)
    # ------------------------------------------------------------------

    def _crew_lane_flush(self):
        self.env["mrp.workorder"].flush_model(
            ["date_start", "date_finished", "crew_lane", "workcenter_id", "state", "leave_id"]
        )
        self.env["mrp.workcenter.productivity"].flush_model(["workorder_id"])
        self.env["resource.calendar.leaves"].flush_model()
        self.env["mrp.workcenter"].flush_model(
            ["crew_lane_count", "resource_id", "resource_calendar_id"]
        )

    @staticmethod
    def _crew_started_sql(alias):
        return SQL(
            "(%s.state = 'progress' OR EXISTS (SELECT 1 FROM "
            "mrp_workcenter_productivity p WHERE p.workorder_id = %s.id))",
            SQL.identifier(alias),
            SQL.identifier(alias),
        )

    def _crew_check_lane_overlap(self):
        """M15: в една писта отворените поръчки не се застъпват (Р30).

        1. flush; 2. печатът на центровете (UPDATE подред по id) —
        сериализира едновременните записи по един център (К15);
        3. обхватът 1 ≤ писта ≤ брой писти (С15); 4. двойките в SQL — без
        двойката „и двете започнати“ (В3), допирането е позволено;
        5. незапочнатите срещу leave `other` без поръчка на ресурса или
        календара на центъра (К2). Проверява се само `self` срещу другите:
        заварено застъпване не спира несвързан запис.
        """
        workorders = self.exists()
        if not workorders:
            return
        self._crew_lane_flush()
        cr = self.env.cr
        self._crew_lane_stamp(workorders.workcenter_id.ids)

        for wo in workorders:
            if wo.state not in CREW_LANE_STATES or not wo.workcenter_id:
                continue
            count = wo.workcenter_id.crew_lane_count or 1
            if not 1 <= wo.crew_lane <= count:
                raise ValidationError(
                    self.env._(
                        "Work order %(wo)s is in lane %(lane)s, but %(wc)s has "
                        "%(count)s lane(s).",
                        wo=wo.display_name,
                        lane=wo.crew_lane,
                        wc=wo.workcenter_id.display_name,
                        count=count,
                    )
                )

        cr.execute(
            SQL(
                """
                SELECT a.id, b.id
                  FROM mrp_workorder a
                  JOIN mrp_workorder b
                    ON b.workcenter_id = a.workcenter_id
                   AND b.crew_lane = a.crew_lane
                   AND b.id != a.id
                 WHERE a.id = ANY(%(ids)s)
                   AND a.state IN %(states)s
                   AND b.state IN %(states)s
                   AND DATE_TRUNC('second', b.date_start) < DATE_TRUNC('second', a.date_finished)
                   AND DATE_TRUNC('second', a.date_start) < DATE_TRUNC('second', b.date_finished)
                   AND NOT (%(a_started)s AND %(b_started)s)
                 ORDER BY a.id, b.date_start, b.id
                 LIMIT 1
                """,
                ids=workorders.ids,
                states=CREW_LANE_STATES,
                a_started=self._crew_started_sql("a"),
                b_started=self._crew_started_sql("b"),
            )
        )
        row = cr.fetchone()
        if row:
            wo, other = self.browse(row[0]), self.browse(row[1])
            raise ValidationError(
                self._crew_overlap_message(
                    wo, other.display_name, other.date_start, other.date_finished
                )
            )

        cr.execute(
            SQL(
                """
                SELECT a.id, l.id
                  FROM mrp_workorder a
                  JOIN mrp_workcenter w ON w.id = a.workcenter_id
                  JOIN resource_calendar_leaves l
                    ON l.time_type = 'other'
                   AND (l.resource_id = w.resource_id OR l.resource_id IS NULL)
                   AND (l.calendar_id = w.resource_calendar_id OR l.calendar_id IS NULL)
                   AND DATE_TRUNC('second', l.date_from) < DATE_TRUNC('second', a.date_finished)
                   AND DATE_TRUNC('second', a.date_start) < DATE_TRUNC('second', l.date_to)
                 WHERE a.id = ANY(%(ids)s)
                   AND a.state IN ('pending', 'waiting', 'ready')
                   AND NOT %(a_started)s
                   AND NOT EXISTS (
                       SELECT 1 FROM mrp_workorder o WHERE o.leave_id = l.id)
                 ORDER BY a.id, l.date_from
                 LIMIT 1
                """,
                ids=workorders.ids,
                a_started=self._crew_started_sql("a"),
            )
        )
        row = cr.fetchone()
        if row:
            wo = self.browse(row[0])
            leave = self.env["resource.calendar.leaves"].sudo().browse(row[1])
            raise ValidationError(
                self._crew_overlap_message(
                    wo, leave.name or leave.display_name, leave.date_from, leave.date_to
                )
            )

    @api.model
    def _crew_lane_stamp(self, workcenter_ids):
        """Печатът на M15 (К15): UPDATE на реда на всеки център, подред по
        id. Втората от две едновременни транзакции, които пипат заетостта
        на един център (поръчка или свободен leave `other`), чака реда и
        при REPEATABLE READ пада със serialization failure → повторение
        със свеж снимък (находка 1 на проверката от 07.10: write skew
        между leave и поръчка)."""
        for workcenter_id in sorted(set(workcenter_ids)):
            self.env.cr.execute(
                SQL(
                    "UPDATE mrp_workcenter SET crew_lane_stamp = "
                    "COALESCE(crew_lane_stamp, 0) + 1 WHERE id = %s",
                    workcenter_id,
                )
            )
        self.env["mrp.workcenter"].invalidate_model(["crew_lane_stamp"])

    def _crew_overlap_message(self, workorder, other, start, stop):
        return self.env._(
            "Work order %(wo)s would overlap %(other)s in lane %(lane)s of "
            "%(wc)s (%(start)s – %(stop)s). Two work orders in the same lane "
            "never overlap.",
            wo=workorder.display_name,
            other=other,
            lane=workorder.crew_lane,
            wc=workorder.workcenter_id.display_name,
            start=format_datetime(self.env, start),
            stop=format_datetime(self.env, stop),
        )

    def _crew_lane_others(self, lane, start=None, stop=None):
        """Другите отворени поръчки в (центъра, `lane`), които застъпват
        [start, stop) (по подразбиране — датите на поръчката):
        [(id, започната)]."""
        self.ensure_one()
        start = start or self.date_start
        stop = stop or self.date_finished
        if not (self.workcenter_id and start and stop):
            return []
        self._crew_lane_flush()
        self.env.cr.execute(
            SQL(
                """
                SELECT o.id, %(started)s
                  FROM mrp_workorder o
                 WHERE o.workcenter_id = %(wc)s
                   AND o.crew_lane = %(lane)s
                   AND o.id != %(id)s
                   AND o.state IN %(states)s
                   AND DATE_TRUNC('second', o.date_start) < DATE_TRUNC('second', %(stop)s::timestamp)
                   AND DATE_TRUNC('second', %(start)s::timestamp) < DATE_TRUNC('second', o.date_finished)
                 ORDER BY o.date_start, o.id
                """,
                started=self._crew_started_sql("o"),
                wc=self.workcenter_id.id,
                lane=lane,
                id=self.id,
                states=CREW_LANE_STATES,
                start=start,
                stop=stop,
            )
        )
        return self.env.cr.fetchall()

    def _crew_lane_busy(self, lane, strict=False):
        """Заета ли е пистата за поръчката: по инварианта (започната срещу
        започната е позволено) или строго — без нито едно застъпване."""
        self.ensure_one()
        others = self._crew_lane_others(lane)
        if strict or not self._crew_is_started():
            return bool(others)
        return any(not started for _id, started in others)

    # ------------------------------------------------------------------
    # M14.3 — изборът на писта
    # ------------------------------------------------------------------

    def _crew_lane_has_started(self, lane):
        """Има ли в пистата друга ЗАПОЧНАТА поръчка, която застъпва тази."""
        self.ensure_one()
        return any(started for _id, started in self._crew_lane_others(lane))

    def _crew_lane_resolve_started(self, lane, count):
        """M14.4 (В3) за започната поръчка: стартът не се отказва, а
        незапочнатите се избутват (влакът в пистата след това). Редът:
        текущата писта без застъпване → най-малката без застъпване →
        текущата без ЗАПОЧНАТИ → най-малката без започнати → остава в своята
        (всички писти са заети от започнати, „Lane overflow“). Находка 4 на
        проверката от 07.10: писта само с незапочнати НЕ е заета."""
        self.ensure_one()
        lanes = [lane] if 1 <= lane <= count else []
        lanes += [candidate for candidate in range(1, count + 1) if candidate != lane]
        free = next(
            (candidate for candidate in lanes if not self._crew_lane_busy(candidate, True)),
            None,
        )
        if free is None:
            free = next(
                (candidate for candidate in lanes if not self._crew_lane_has_started(candidate)),
                None,
            )
        return free or min(max(lane, 1), count)

    def _crew_lane_resolve(self, strict=False):
        """M14.3: текущата писта е свободна и в обхвата → остава; иначе
        най-малката свободна; няма свободна → M15 гърми. Започнатите се
        пипат само при `strict` (M14.4, `_crew_lane_resolve_started`)."""
        for wo in self:
            if wo.state not in CREW_LANE_STATES or not (
                wo.workcenter_id and wo.date_start and wo.date_finished
            ):
                continue
            if not strict and wo._crew_is_started():
                continue
            count = wo.workcenter_id.crew_lane_count or 1
            lane = wo.crew_lane
            if count == 1 and lane == 1:
                continue
            if strict and wo._crew_is_started():
                new_lane = wo._crew_lane_resolve_started(lane, count)
                if new_lane != lane:
                    wo.with_context(**{CREW_LANE_DEFER: True}).write({"crew_lane": new_lane})
                continue
            if 1 <= lane <= count and not wo._crew_lane_busy(lane, strict):
                continue
            free = next(
                (
                    candidate
                    for candidate in range(1, count + 1)
                    if candidate != lane and not wo._crew_lane_busy(candidate, strict)
                ),
                None,
            )
            new_lane = free or min(max(lane, 1), count)
            if new_lane != lane:
                wo.with_context(**{CREW_LANE_DEFER: True}).write({"crew_lane": new_lane})

    # ------------------------------------------------------------------
    # create / write / планиране / старт
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        push = self._crew_push_wanted(set().union(*vals_list) if vals_list else set())
        context = {CREW_LANE_WO_WRITE: True}
        if push:
            context[CREW_PUSH_PENDING] = True
        workorders = super(MrpWorkorderLanes, self.with_context(**context)).create(
            vals_list
        )
        workorders = workorders.with_env(self.env)
        if not self.env.context.get(CREW_LANE_DEFER):
            self.browse(
                [wo.id for wo, vals in zip(workorders, vals_list) if "crew_lane" not in vals]
            )._crew_lane_resolve()
            if push:
                workorders._crew_push_after_write({})
            workorders._crew_check_lane_overlap()
        return workorders

    def write(self, vals):
        context = self.env.context
        if context.get(CREW_GANTT_DRAG):
            self._crew_check_drag(vals)
        reopen = False
        if "state" in vals:
            new_state = vals["state"]
            reopen = any(
                (wo.state in ("done", "cancel", "progress") and new_state in ("pending", "waiting", "ready"))
                or (wo.state in ("done", "cancel") and new_state == "progress")
                for wo in self
            )
        push = self._crew_push_wanted(vals)
        old = self._crew_push_snapshot() if push else {}
        inner = {CREW_LANE_WO_WRITE: True}
        if push:
            inner[CREW_PUSH_PENDING] = tuple(self.ids)
        res = super(MrpWorkorderLanes, self.with_context(**inner)).write(vals)
        if "date_finished" in vals and not context.get(CREW_TRAIN):
            self._crew_manual_finish()
        pending = context.get(CREW_PUSH_PENDING)
        nested = pending is True or bool(pending and set(self.ids) <= set(pending))
        if not context.get(CREW_LANE_DEFER) and not nested and (
            CREW_LANE_PLAN_FIELDS.intersection(vals) or reopen
        ):
            if "crew_lane" not in vals and CREW_LANE_PLAN_FIELDS.intersection(vals):
                self._crew_lane_resolve()
            if push:
                self._crew_push_after_write(old)
            self._crew_check_lane_overlap()
        return res

    # ------------------------------------------------------------------
    # Р32 (изменено 07.10, 19.0.1.5.3) — избутването при запис извън Ганта
    # ------------------------------------------------------------------

    def _crew_push_wanted(self, fields_written):
        """Избутва ли този запис/създаване незапочнатите в пистата: нови
        дати или център, и НЕ сме в собствен път на модула — двигателят
        (M6), влакът, `crew_drop`, стартът, отмяната (всички под
        `crew_lane_defer`), влакът (`crew_train`) и вложеният запис вътре в
        нашия `write`/`create`/„Plan“ (`crew_lane_wo_write` — външният
        запис избутва сам). Така избутването не се вика рекурсивно."""
        context = self.env.context
        return bool(
            CREW_PUSH_FIELDS.intersection(fields_written)
            and not context.get(CREW_LANE_DEFER)
            and not context.get(CREW_TRAIN)
            and not context.get(CREW_LANE_WO_WRITE)
        )

    def _crew_push_snapshot(self):
        """Старото място на поръчките преди записа — за реда на X в
        партидата (отмяната го връща там) и за датите на МО."""
        return {
            wo.id: {
                "workcenter": wo.workcenter_id,
                "lane": wo.crew_lane,
                "date_start": wo.date_start,
                "date_finished": wo.date_finished,
                "duration": wo.duration_expected,
                "mo": (wo.production_id.date_start, wo.production_id.date_finished),
            }
            for wo in self
        }

    def _crew_push_after_write(self, old):
        """Р32 (изменено 07.10): поръчка, записана извън нашия Гант (форма,
        стандартният Гант на EE, импорт, RPC), чиито нови дати опират в
        НЕЗАПОЧНАТИ поръчки в същата писта, ги избутва верижно след себе си —
        веригата на M17 (`_crew_drop_plan` с `placed`), без дублиране.

        - започната в пътя → отказ (UserError на веригата);
        - на друг център (сменен `workcenter_id`) — без избутване, само
          свободна дупка (В1, като M17): заетата писта я отказва M15;
        - избутаните бутат зависимите си само на СЪЩИЯ център; зависимите
          на друг център не се местят и записът не се отказва — конфликтът
          мига в Ганта (`crew_dep_conflict`, Р33 изменено, 19.0.1.5.5);
        - ключалката на пистата (Р38) се спазва;
        - ходовете се пишат под `crew_lane_defer` (без рекурсия), M15
          накрая е на викащия, партида `write` за одит и отмяна;
        - 19.0.1.5.4: избутаните (веригата и зависимите) не започват преди
          `_crew_replan_earliest()`; датите на самия X са на човека — ако са
          преди границата, отказът е на другия модул (не местим тихо). Отказ
          при записа на избутан → ясен отказ с името му.

        `old` = `_crew_push_snapshot()` преди записа; при създаване е
        празен — тогава X в партидата е без старо място (отмяната го
        оставя непланиран)."""
        Lock = self.env["mrp.workcenter.lane.lock"]
        Batch = self.env["mrp.workcenter.replan.batch"]
        now = fields.Datetime.now()
        for wo in self:
            if wo.state not in CREW_LANE_STATES or not (
                wo.workcenter_id and wo.date_start and wo.date_finished
            ):
                continue
            # Незапочната опира в нещо в пистата → веригата (започната в
            # пътя дава ясния отказ на M17); започната — само в незапочнати
            # (две започнати се допускат, В3).
            others = wo._crew_lane_others(wo.crew_lane)
            if wo._crew_is_started():
                others = [item for item in others if not item[1]]
                if not others:
                    continue
            # Росен 13.10.2026: незапочната без застъпване също минава през
            # плана — първият вагон в пистата се залепва за влака.
            before = old.get(wo.id)
            workcenter, lane = wo.workcenter_id, wo.crew_lane
            if before and before["workcenter"] != workcenter:
                # Друг център: само свободна дупка (В1, като M17) — без
                # избутване; заетата писта я отказва M15.
                continue
            if before and (
                before["lane"],
                before["date_start"],
                before["date_finished"],
            ) == (lane, wo.date_start, wo.date_finished):
                # Записът не я е преместил (пакетен запис): тя не бута —
                # застъпването е дошло от друга поръчка и M15 го отказва.
                continue
            plan = wo._crew_drop_plan(
                workcenter,
                lane,
                self.browse(),
                False,
                now,
                placed=(wo.date_start, wo.date_finished),
                before_lane=(before["workcenter"], before["lane"]) if before else None,
            )
            # X се пише наново само ако планът го е залепил за влака.
            pushes = [
                move
                for move in plan["moves"]
                if move["workorder"] != wo
                or (move["date_start"], move["date_finished"])
                != (wo.date_start, wo.date_finished)
            ]
            if not pushes:
                continue
            for wc, wc_lane in {(move["workcenter"], move["lane"]) for move in pushes}:
                Lock._crew_lane_check_lock(wc, wc_lane)
            x_move = plan["moves"][0]
            if before:
                x_move.update(
                    old_workcenter=before["workcenter"],
                    old_lane=before["lane"],
                    old_date_start=before["date_start"],
                    old_date_finished=before["date_finished"],
                    old_duration=before["duration"],
                )
            else:
                x_move.update(old_date_start=False, old_date_finished=False)
            touched = self.env["mrp.workorder"].union(
                *[move["workorder"] for move in plan["moves"]]
            )
            snapshot = {
                mo.id: (mo.date_start, mo.date_finished) for mo in touched.production_id
            }
            if before:
                snapshot[wo.production_id.id] = before["mo"]
            wo._crew_apply_moves_named(workcenter, pushes)
            touched._crew_check_lane_overlap()
            batch = Batch._crew_record_moves(
                "write",
                plan["moves"],
                workcenter | touched.workcenter_id,
                snapshot=snapshot,
            )
            batch._crew_finish_moves(touched, notes=plan["notes"])
            Lock._crew_lane_notify(
                touched.workcenter_id,
                "changed",
                {
                    "workcenter_ids": touched.workcenter_id.ids,
                    "workorder_ids": touched.ids,
                    "source": "write",
                },
            )

    def _crew_manual_finish(self):
        """M14.5: ръчна смяна на края на започната поръчка → новият край е
        планираният (`crew_planned_finish`), нивото на тревогата е 0."""
        for wo in self:
            if (
                wo.state == "progress"
                and wo.date_finished
                and wo.crew_planned_finish
                and wo.crew_planned_finish != wo.date_finished
            ):
                wo.sudo().write(
                    {
                        "crew_planned_finish": wo.date_finished,
                        "crew_stretch_alert_level": 0,
                    }
                )

    def _plan_workorder(self, replan=False):
        """Стандартното „Plan“ (К6): leave-ът се създава преди връзката —
        куката на leave-овете не го проверява; поръчката се проверява в
        `write` (M14.3 + M15)."""
        return super(
            MrpWorkorderLanes, self.with_context(**{CREW_LANE_WO_WRITE: True})
        )._plan_workorder(replan=replan)

    def button_start(self, *args, **kwargs):
        """M14.4: стартът е реалност и не се отказва (В3). Записите на
        стандарта вървят под `crew_lane_defer`, после: планираният край,
        пистата (строго), избутването на незапочнатите в пистата и M15."""
        todo = self.filtered(lambda wo: wo.state not in ("progress", "done", "cancel"))
        res = super(
            MrpWorkorderLanes,
            self.with_context(**{CREW_LANE_DEFER: True, CREW_LANE_WO_WRITE: True}),
        ).button_start(*args, **kwargs)
        todo.filtered(lambda wo: wo.state == "progress")._crew_after_start()
        return res

    def _set_duration(self):
        """M14.4 и по втория път на ядрото до `progress`: ръчно отчетеното
        време (inverse на `duration`, C `mrp_workorder.py:357-374`) слага
        `state = 'progress'` без `button_start`. Без това поръчката няма
        `crew_planned_finish`, пистата не се разрешава и тревогата по Р37
        не тръгва (находка 5 на проверката от 07.10)."""
        todo = self.filtered(lambda wo: wo.state not in ("progress", "done", "cancel"))
        res = super()._set_duration()
        todo.filtered(lambda wo: wo.state == "progress")._crew_after_start()
        return res

    def _crew_after_start(self):
        Lock = self.env["mrp.workcenter.lane.lock"]
        Batch = self.env["mrp.workcenter.replan.batch"].sudo()
        now = fields.Datetime.now()
        for wo in self:
            vals = {
                "crew_planned_finish": wo.date_finished,
                "crew_stretch_alert_level": 0,
            }
            full_end = wo._crew_start_full_end()
            if full_end and (not wo.date_finished or wo.date_finished < full_end):
                vals["date_finished"] = vals["crew_planned_finish"] = full_end
            wo.sudo().with_context(
                **{CREW_LANE_DEFER: True, "bypass_duration_calculation": True}
            ).write(vals)
            wo._crew_lane_resolve(strict=True)
            touched = wo
            workcenter = wo.workcenter_id.sudo()
            if any(not started for _id, started in wo._crew_lane_others(wo.crew_lane)):
                plan = workcenter._crew_train_lane(wo.crew_lane, now)
                workcenter._crew_refusal_notes(plan["refused"], [wo.crew_lane], now)
                if plan["moves"]:
                    batch = Batch._crew_record_moves(
                        "train", plan["moves"], workcenter, snapshot=plan["mo_snapshot"]
                    )
                    moved = batch.line_ids.workorder_id
                    batch._crew_finish_moves(moved)
                    touched |= moved.with_env(self.env)
            touched._crew_check_lane_overlap()
            if any(started for _id, started in wo._crew_lane_others(wo.crew_lane)):
                wo._crew_post_lane_overflow()
            Lock._crew_lane_notify(
                wo.workcenter_id,
                "changed",
                {
                    "workcenter_ids": wo.workcenter_id.ids,
                    "workorder_ids": touched.ids,
                    "source": "start",
                },
            )

    def _crew_start_full_end(self):
        """Краят на започнатата поръчка, ако върви цялата си продължителност
        от реалното начало — по календара на центъра (прекъсванията се
        прескачат, Р34). При късен старт ядрото пише `date_start = сега`, а
        краят остава старият или става „сега“ (К7): дължината се губи и
        разтягането по Р37 се брои от момента на старта (находка 5 на
        проверката от 07.10). Без слот → False (остава краят на ядрото)."""
        self.ensure_one()
        if not (self.workcenter_id and self.date_start and self.duration_expected):
            return False
        date_from, date_to = self._crew_with_share(self.workcenter_id)._crew_walk(
            self.date_start, self.duration_expected
        )
        return date_to if date_from else False

    def _crew_post_lane_overflow(self):
        """Всички писти са заети от започнати: поръчката остава в пистата
        си; бележка „Lane overflow“ в chatter-а на МО до отговорника."""
        self.ensure_one()
        responsible = self.workcenter_id.crew_responsible_id
        body = self.env._(
            "Lane overflow: %(wo)s started on %(wc)s while every lane is busy "
            "with started work orders.",
            wo=self.display_name,
            wc=self.workcenter_id.display_name,
        )
        self.production_id.sudo().message_post(
            body=Markup("<p>%s</p>") % body,
            partner_ids=responsible.partner_id.ids,
            subtype_xmlid="mail.mt_note",
        )

    # ------------------------------------------------------------------
    # M16 — гардът на влаченето (вместо M10)
    # ------------------------------------------------------------------

    def _crew_check_drag(self, vals):
        """M16: под флага на влаченето — ключалката на източника и целта
        (M20.3); започната поръчка не сменя начало, център и писта
        (разтягането на края минава, M14.5, С11). Застъпването го решават
        M14.3 + M15."""
        Lock = self.env["mrp.workcenter.lane.lock"]
        Workcenter = self.env["mrp.workcenter"]
        for wo in self:
            target_wc = Workcenter.browse(vals.get("workcenter_id", wo.workcenter_id.id))
            target_lane = vals.get("crew_lane", wo.crew_lane)
            Lock._crew_lane_check_lock(wo.workcenter_id, wo.crew_lane)
            Lock._crew_lane_check_lock(target_wc, target_lane)
            if not wo._crew_is_started():
                continue
            moved = (
                ("workcenter_id" in vals and target_wc != wo.workcenter_id)
                or ("crew_lane" in vals and target_lane != wo.crew_lane)
                or (
                    "date_start" in vals
                    and fields.Datetime.to_datetime(vals["date_start"]) != wo.date_start
                )
            )
            if moved:
                raise UserError(self.env._("A started work order cannot be moved."))

    # ------------------------------------------------------------------
    # M17 — „пусни тук“ (Р32, Р33)
    # ------------------------------------------------------------------

    def crew_drop(
        self, workcenter_id, lane, after_workorder_id=False, date_start=False, snap=False
    ):
        """M17: пускане на поръчката в писта `lane` на център
        `workcenter_id` — след `after_workorder_id` или от `date_start`.
        Един метод за вмъкване, свободно пускане, друга писта и друга машина.

        19.0.1.6.1 (Р32, Росен 09.10): `snap` — пускане в ПРАЗНО място от
        нашия Гант (без `after`): X не остава на `date_start`, а залепва за
        края на последната поръчка в пистата преди мястото (ходът по
        календара го мести след почивката); без предходна — от сега. Само
        Гантът го праща; вмъкването (`after`, k = 0 с `date_start`) и прекият
        запис не залепват.

        Отказът е `UserError` (пълен rollback). 19.0.1.5.5 (Р33 изменено):
        зависимостите на друг център не искат съгласие и не се местят —
        конфликтът мига в Ганта (`crew_dep_conflict`), затова диалогът и
        токенът отпаднаха. Връща {"status": "done", "batch_id", "moves",
        "notes"}.
        """
        self.ensure_one()
        self.check_access("write")
        workcenter = self.env["mrp.workcenter"].browse(workcenter_id).exists()
        lane = int(lane or 1)
        after = self.browse(after_workorder_id).exists() if after_workorder_id else self.browse()
        date_start = fields.Datetime.to_datetime(date_start) if date_start else False
        self._crew_drop_check(workcenter, lane, after)
        now = fields.Datetime.now()
        plan = self._crew_drop_plan(workcenter, lane, after, date_start, now, snap=snap)
        return self._crew_drop_apply(workcenter, lane, plan)

    def _crew_drop_check(self, workcenter, lane, after):
        """Отказите преди плана (М17)."""
        self.ensure_one()
        if self.state in ("done", "cancel") or self._crew_is_started():
            raise UserError(
                self.env._("A started or finished work order cannot be moved.")
            )
        if not workcenter:
            raise UserError(self.env._("Select a work center."))
        if workcenter.company_id and workcenter.company_id != self.company_id:
            raise UserError(
                self.env._(
                    "The work center %(wc)s belongs to another company.",
                    wc=workcenter.display_name,
                )
            )
        if not workcenter.resource_calendar_id:
            raise UserError(
                self.env._(
                    "There is no working schedule on the work center %(wc)s.",
                    wc=workcenter.display_name,
                )
            )
        if not 1 <= lane <= (workcenter.crew_lane_count or 1):
            raise UserError(
                self.env._(
                    "%(wc)s has no lane %(lane)s.", wc=workcenter.display_name, lane=lane
                )
            )
        if after and (after.workcenter_id != workcenter or after.crew_lane != lane):
            raise UserError(
                self.env._(
                    "The work order %(after)s is not in lane %(lane)s of %(wc)s.",
                    after=after.display_name,
                    lane=lane,
                    wc=workcenter.display_name,
                )
            )
        Lock = self.env["mrp.workcenter.lane.lock"]
        Lock._crew_lane_check_lock(self.workcenter_id, self.crew_lane)
        Lock._crew_lane_check_lock(workcenter, lane)

    def _crew_drop_plan(
        self, workcenter, lane, after, date_start, now, placed=None, snap=False,
        before_lane=None,
    ):
        """План без запис (M17): пистите, които планът пипа, се гледат през
        проекцията на влака към „сега“ (С12); X се слага с хода по
        календара; веригата в пистата бута следващите (започнат → отказ;
        на друг център непразна верига → отказ, В1); Р33 — зависимите на
        СЪЩИЯ център се бутат в своята писта до фиксирана точка (започната
        → отказ).

        19.0.1.5.5 (Р33 изменено, Росен 07.10): зависимост на ДРУГ център
        (наследник или предшественик) не спира местенето и не се мести —
        X не се дърпа след предшественик на друг център, наследник на друг
        център не се избутва. Конфликтът остава видим: бележка в отговора
        и `crew_dep_conflict` (мига в Ганта), докато датите не се оправят.

        19.0.1.5.3 (Р32, изменено 07.10): `placed` = (начало, край) — X
        ВЕЧЕ стои там (запис извън нашия Гант, `_crew_push_after_write`).
        Тогава X не се мести, проекцията на влака не се прилага (записът
        не тегли пистата към сега), веригата тръгва от X, а зависимите се
        бутат само заради избутаните вагони — X е поставен от човека, като в
        стандарта.

        Росен 13.10.2026: накрая първият незапочнат вагон в целевата писта
        и в пистата, от която X е тръгнал (`before_lane` при запис), се
        залепва за влака — „сега“ или краят на неподвижния пред него. Без
        празнина в началото на пистата, за да може влакът да бута вагоните.

        19.0.1.5.4 (Росен, 07.10):
        - границата `_crew_replan_earliest()` (точката за разширение на M6 и
          влака) важи и тук: вагоните на веригата и зависимите по Р33 не
          започват преди нея; при пускане X отива на мястото на стрелката,
          а ако то е преди границата — на границата (с бележка). При запис
          (`placed`) X е на човека — не се мести, отказът е на другия модул;
        - проекцията на влака закотвя (`pinned`) отказаните вагони
          (`crew_train_refused_since`) само ПРЕДИ мястото на вмъкване в
          целевата писта (в другите писти — всички, като M22). Вагоните след
          мястото се избутват като всички други; отказ при записа им дава
          ясен отказ на цялото пускане (`_crew_apply_moves_named`)."""
        self.ensure_one()
        X = self
        positions = {}
        moves = {}
        order = []
        projected = set()
        notes = []
        steps = [0]
        bound_params = {}
        # Мястото на стрелката (по базата): преди него отказаните стоят.
        if placed:
            place = None
        else:
            place = max((after.date_finished if after else date_start) or now, now)

        def bound(wo, wc, cursor):
            # Като M6 и влака: параметрите са нормализираните входни данни
            # на центъра; празната точка не мести.
            if wc.id not in bound_params:
                bound_params[wc.id] = self.env[
                    "mrp.workcenter.replan.batch"
                ]._crew_normalize_params({"workcenter_ids": wc.ids})
            earliest = wo._crew_replan_earliest(bound_params[wc.id])
            return max(cursor, earliest) if earliest else cursor

        def current(wo):
            if wo.id in positions:
                return positions[wo.id]
            return (wo.workcenter_id, wo.crew_lane, wo.date_start, wo.date_finished)

        def set_move(wo, wc, wo_lane, start, stop, reason, started=False):
            steps[0] += 1
            if steps[0] > CREW_DROP_MAX_STEPS:
                raise UserError(self.env._("The plan is too long to compute."))
            if wo.id in moves:
                move = moves[wo.id]
                move.update(
                    workcenter=wc,
                    lane=wo_lane,
                    date_start=start,
                    date_finished=stop,
                    started=started or move["started"],
                )
                if move["reason"] == "train":
                    move["reason"] = reason
            else:
                moves[wo.id] = wc._crew_move(wo, wo_lane, start, stop, reason, started)
                order.append(wo.id)
            positions[wo.id] = (wc, wo_lane, start, stop)

        def project(wc, wo_lane):
            key = (wc.id, wo_lane)
            if placed or key in projected:
                return
            projected.add(key)
            # 19.0.1.5.4: отказаните вагони преди мястото стоят (влакът не
            # ги мести и пускането не пада заради тях); в другите писти —
            # всички отказани, като M22.
            before = place if (wc, wo_lane) == (workcenter, lane) else None
            pinned = wc._crew_train_pinned(wo_lane, before=before)
            train = wc._crew_train_plan(wo_lane, now, exclude_ids=[X.id], pinned=pinned)
            for move in train["moves"]:
                set_move(
                    move["workorder"],
                    wc,
                    wo_lane,
                    move["date_start"],
                    move["date_finished"],
                    "train",
                    move["started"],
                )

        def wagons(wc, wo_lane, exclude_ids=()):
            project(wc, wo_lane)
            items = []
            for wagon in wc._crew_lane_wagons(wo_lane, [X.id, *exclude_ids]):
                pos = current(wagon)
                if pos[0] == wc and pos[1] == wo_lane:
                    items.append((pos[2], wagon.id, wagon, pos))
            items.sort(key=lambda item: (item[0], item[1]))
            return [(item[2], item[3]) for item in items]

        noted = set()

        def conflict_note(predecessor, successor):
            # Р33 изменено (1.5.5): зависимост на друг център — не се мести,
            # а се казва (веднъж на двойка); двете поръчки мигат в Ганта.
            if (predecessor.id, successor.id) in noted:
                return
            noted.add((predecessor.id, successor.id))
            notes.append(
                self.env._(
                    "%(succ)s now starts before %(pred)s ends. They are "
                    "linked on different work centers; neither is moved and "
                    "both are highlighted until the dates are fixed.",
                    succ=successor.display_name,
                    pred=predecessor.display_name,
                )
            )

        def walk(wc, start, minutes, wo):
            # №145: прозорецът е по дела на поръчката и бригадата на wc.
            date_from, date_to = wo._crew_with_share(wc)._crew_walk(start, minutes)
            if not date_from:
                raise UserError(date_to)
            return date_from, date_to

        def chain(wc, wo_lane, start, cursor, exclude_ids=(), foreign=False):
            pushed = []
            for wagon, (_wc, _lane, w_start, w_stop) in wagons(wc, wo_lane, exclude_ids):
                if w_stop <= start:
                    continue
                if w_start >= cursor:
                    break
                if wagon._crew_is_started():
                    raise UserError(
                        self.env._(
                            "The push would move the started work order %(wo)s.",
                            wo=wagon.display_name,
                        )
                    )
                if foreign:
                    raise UserError(
                        self.env._(
                            "No free lane on %(wc)s at this time.", wc=wc.display_name
                        )
                    )
                date_from, date_to = walk(
                    wc, bound(wagon, wc, cursor), wagon.duration_expected, wagon
                )
                # Опира в предходния → секунда след него, краят остава.
                if date_from == cursor:
                    date_from += CREW_GAP
                set_move(wagon, wc, wo_lane, date_from, date_to, "chain")
                pushed.append(wagon)
                cursor = date_to
            return pushed

        def lane_items(wc, wo_lane):
            # Вагоните на пистата по плана, вкл. X, ако планът го е сложил там.
            items = list(wagons(wc, wo_lane))
            pos = current(X)
            if pos[0] == wc and pos[1] == wo_lane and pos[2] and pos[3]:
                items.append((X, pos))
            items.sort(key=lambda item: (item[1][2], item[0].id))
            return items

        def snap_head(wc, wo_lane):
            # Влакът е „сега“, а ако пред вагона има неподвижен (започнат,
            # закотвен отказан, МО извън CREW_TRAIN_MO_STATES или избутан
            # зависим) — краят му. Първият подвижен вагон отива там (по
            # календара и границата `_crew_replan_earliest`, след
            # предшествениците си на същия център). Само назад: вагон в
            # миналото или вече залепен не се пипа. Назад не създава
            # застъпване — краят само се изтегля.
            if not wc.crew_snap_head:
                return
            cursor = now
            after_wagon = False
            head = None
            for wagon, pos in lane_items(wc, wo_lane):
                if (
                    wagon._crew_is_started()
                    or wagon.crew_train_refused_since
                    or wagon.production_id.state not in CREW_TRAIN_MO_STATES
                    or moves.get(wagon.id, {}).get("reason") == "dependency"
                ):
                    if pos[3] and pos[3] > cursor:
                        cursor = pos[3]
                        after_wagon = True
                    continue
                head = (wagon, pos)
                break
            if not head:
                return
            wagon, (_wc, _lane, w_start, _w_stop) = head
            target = bound(wagon, wc, cursor)
            for predecessor in wagon.blocked_by_workorder_ids:
                if predecessor.state == "cancel":
                    continue
                pred_wc, _pred_lane, _pred_start, pred_stop = current(predecessor)
                if pred_wc == wc and pred_stop and pred_stop > target:
                    target = pred_stop
                    after_wagon = True
            date_from, date_to = walk(wc, target, wagon.duration_expected, wagon)
            if after_wagon and date_from == target:
                date_from += CREW_GAP
            if date_from >= w_start:
                return
            reason = moves[wagon.id]["reason"] if wagon.id in moves else "train"
            set_move(wagon, wc, wo_lane, date_from, date_to, reason)

        if placed:
            # Р32 (07.10): X е записан — веригата тръгва от него; зависимите
            # се бутат само заради избутаните (X го е сложил човекът).
            date_from, date_to = placed
            set_move(X, workcenter, lane, date_from, date_to, "write")
            queue = chain(workcenter, lane, date_from, date_to)
        else:
            # 1. Продължителността.
            if workcenter == X.workcenter_id:
                duration = X.duration_expected
            else:
                duration = X._get_duration_expected(alternative_workcenter=workcenter)

            # 2. Началото S: краят на `after`, `date_start` или сега; после
            # S = max(S, сега, краищата на предшествениците); накрая — ако S е
            # вътре във вагон, S е неговият край (находка 4 на проверката от
            # 07.10: изтеглянето до сега/предшественика иначе слага X вътре в
            # започнатата или пред незапочнат вагон, който е бил отпред).
            lane_wagons = wagons(workcenter, lane)
            if after:
                start = current(after)[3]
            elif snap:
                # 19.0.1.6.1 (Р32, Росен 09.10): празно място не оставя дупка —
                # X залепва за края на последната поръчка в пистата преди
                # мястото на пускане (по проекцията); без предходна — сега.
                # Ако веднага след нея е почивка, ходът по календара (3.) го
                # слага в началото на следващото работно време.
                previous = [
                    pos[3]
                    for _wagon, pos in lane_wagons
                    if date_start and pos[2] < date_start and pos[3]
                ]
                start = max([*previous, now])
            elif date_start:
                start = date_start
            else:
                start = now
            if start < now:
                notes.append(
                    self.env._(
                        "%(wo)s cannot start in the past; it starts now.", wo=X.display_name
                    )
                )
                start = now
            foreign_preds = []
            for predecessor in X.blocked_by_workorder_ids:
                if predecessor.state == "cancel":
                    continue
                pred_wc, _pred_lane, _pred_start, pred_stop = current(predecessor)
                if pred_wc != workcenter:
                    # 19.0.1.5.5 (Р33 изменено): предшественик на друг
                    # център не дърпа X — конфликтът мига.
                    foreign_preds.append(predecessor)
                    continue
                if pred_stop and pred_stop > start:
                    start = pred_stop
                    notes.append(
                        self.env._(
                            "%(wo)s starts after its predecessor %(pred)s.",
                            wo=X.display_name,
                            pred=predecessor.display_name,
                        )
                    )
            # 19.0.1.5.4: мястото е преди границата на точката за
            # разширение (напр. краят на фолиото) → X отива на границата.
            earliest = bound(X, workcenter, start)
            if earliest > start:
                start = earliest
                notes.append(
                    self.env._(
                        "%(wo)s cannot start before %(date)s; it starts there.",
                        wo=X.display_name,
                        date=format_datetime(self.env, earliest),
                    )
                )
            changed = True
            while changed:
                changed = False
                for _wagon, (_wc, _lane, w_start, w_stop) in lane_wagons:
                    if w_start < start < w_stop:
                        start = w_stop
                        changed = True
            # 3. X с хода по календара; 4. веригата в (W, L).
            date_from, date_to = walk(workcenter, start, duration, X)
            # Росен 12.10.2026: X, който опира в края на друга поръчка в
            # пистата, почва секунда след нея (CREW_GAP) — „веднага след“,
            # не в същия момент. Краят остава от хода — секундите не се
            # трупат и не преливат през почивка или края на смяната.
            if any(
                w_start < date_from == w_stop
                for _wagon, (_wc, _lane, w_start, w_stop) in lane_wagons
            ):
                date_from += CREW_GAP
            set_move(X, workcenter, lane, date_from, date_to, "drop")
            for predecessor in foreign_preds:
                pred_stop = current(predecessor)[3]
                if (
                    predecessor.state in CREW_LANE_STATES
                    and pred_stop
                    and pred_stop.replace(microsecond=0) > date_from.replace(microsecond=0)
                ):
                    conflict_note(predecessor, X)
            moves[X.id]["duration"] = duration
            moves[X.id]["set_duration"] = True
            queue = [X] + chain(
                workcenter,
                lane,
                date_from,
                date_to,
                foreign=workcenter != X.workcenter_id,
            )

        # 5. Р33: зависимите на същия център — в своята писта, до фиксирана
        # точка; на друг център — не се местят (1.5.5), само бележка.
        while queue:
            moved = queue.pop(0)
            moved_wc, _moved_lane, _moved_start, moved_stop = current(moved)
            for successor in moved.needed_by_workorder_ids:
                if successor.state not in CREW_LANE_STATES or successor == X:
                    continue
                if current(successor)[0] != moved_wc:
                    succ_start = current(successor)[2]
                    if succ_start and succ_start.replace(
                        microsecond=0
                    ) < moved_stop.replace(microsecond=0):
                        conflict_note(moved, successor)
                    continue
                project(successor.workcenter_id, successor.crew_lane)
                succ_wc, succ_lane, succ_start, _succ_stop = current(successor)
                if not succ_start or succ_start >= moved_stop:
                    continue
                if successor._crew_is_started():
                    raise UserError(
                        self.env._(
                            "The push would move the started work order %(wo)s.",
                            wo=successor.display_name,
                        )
                    )
                date_from, date_to = walk(
                    succ_wc,
                    bound(successor, succ_wc, moved_stop),
                    successor.duration_expected,
                    successor,
                )
                set_move(successor, succ_wc, succ_lane, date_from, date_to, "dependency")
                queue.append(successor)
                queue += chain(
                    succ_wc, succ_lane, date_from, date_to, exclude_ids=[successor.id]
                )

        # 6. Росен 13.10.2026: при всяко местене първият незапочнат вагон в
        # пистата се залепва за влака — иначе откъснатият вагон стои пред
        # празнина и влакът не може да бута вагоните. Пистите са целевата и
        # тази, от която X е тръгнал.
        # Създаване с дати (импорт, RPC) не е местене: при запис без старо
        # място (`before_lane`) не се залепва.
        snap_lanes = []
        if not placed:
            snap_lanes.append((workcenter, lane))
            if (X.workcenter_id, X.crew_lane) != (workcenter, lane):
                snap_lanes.append((X.workcenter_id, X.crew_lane))
        elif before_lane:
            snap_lanes.append((workcenter, lane))
            if before_lane != (workcenter, lane):
                snap_lanes.append(before_lane)
        for snap_wc, snap_lane in snap_lanes:
            if snap_wc and snap_lane:
                snap_head(snap_wc, snap_lane)

        return {"moves": [moves[wo_id] for wo_id in order], "notes": notes}

    def _crew_apply_moves_named(self, workcenter, moves):
        """19.0.1.5.4: ходовете на M17 и на Р32 при запис един по един;
        отказ на друг модул при записа на една поръчка (UserError /
        ValidationError, напр. ограничение по датите) → ясен отказ на цялото
        действие, който назовава поръчката и причината. Влакът (M18) не
        минава оттук — той закотвя отказания вагон и продължава."""
        touched = self.env["mrp.workorder"]
        for move in moves:
            try:
                touched |= workcenter._crew_apply_moves([move])
            except (UserError, ValidationError) as error:
                # ValidationError остава ValidationError, другите — UserError
                # (подкласовете като RedirectWarning имат друг конструктор).
                cls = ValidationError if isinstance(error, ValidationError) else UserError
                raise cls(
                    self.env._(
                        "Moving %(wo)s was refused: %(reason)s",
                        wo=move["workorder"].display_name,
                        reason=error.args[0] if error.args else str(error),
                    )
                ) from error
        return touched

    def _crew_drop_apply(self, workcenter, lane, plan):
        """Прилагането на M17 в savepoint под `crew_lane_defer`: ключалката
        на целта; X (на друг център — първо центърът, после датите с
        bypass, К5); останалите ходове; M15; датите на МО; партида `drop`;
        нарядът; шината; ключалките се освобождават."""
        self.ensure_one()
        X = self
        Lock = self.env["mrp.workcenter.lane.lock"]
        Batch = self.env["mrp.workcenter.replan.batch"]
        moves = plan["moves"]
        touched = self.env["mrp.workorder"].union(*[m["workorder"] for m in moves])
        snapshot = {
            mo.id: (mo.date_start, mo.date_finished) for mo in touched.production_id
        }
        source = (X.workcenter_id, X.crew_lane)
        with self.env.cr.savepoint():
            taken = Lock._crew_lane_take(workcenter, lane, X)
            if not taken["ok"]:
                raise UserError(Lock._crew_lane_locked_message(workcenter, lane, taken))
            if workcenter != X.workcenter_id:
                X.with_context(**{CREW_LANE_DEFER: True}).write(
                    {"workcenter_id": workcenter.id, "crew_lane": lane}
                )
                if X.leave_id:
                    X.leave_id.sudo().with_context(**{CREW_LANE_DEFER: True}).write(
                        {"calendar_id": workcenter.resource_calendar_id.id}
                    )
            X._crew_apply_moves_named(workcenter, moves)
            touched._crew_check_lane_overlap()
            batch = Batch._crew_record_moves(
                "drop", moves, workcenter | source[0], snapshot=snapshot
            )
            batch._crew_finish_moves(touched, notes=plan["notes"])
            Lock._crew_lane_notify(
                workcenter | source[0],
                "changed",
                {
                    "workcenter_ids": (workcenter | source[0]).ids,
                    "workorder_ids": touched.ids,
                    "source": "drop",
                },
            )
            Lock._crew_lane_release_own([(workcenter, lane), source], workorder=X)
        return {
            "status": "done",
            "batch_id": batch.id,
            "moves": [
                {
                    "id": move["workorder"].id,
                    "workcenter_id": move["workcenter"].id,
                    "lane": move["lane"],
                    "date_start": _dt(move["date_start"]),
                    "date_finished": _dt(move["date_finished"]),
                    "reason": move["reason"],
                }
                for move in moves
            ],
            "notes": plan["notes"],
        }

    # ------------------------------------------------------------------
    # M14.6, M21, M22 — Гантът
    # ------------------------------------------------------------------

    def _web_gantt_progress_bar_workcenter_id(self, res_ids, start, stop):
        """M14.6: при N писти таванът на лентата на центъра е × N (К9)."""
        result = super()._web_gantt_progress_bar_workcenter_id(res_ids, start, stop)
        workcenters = self.env["mrp.workcenter"].browse(
            [key for key in result if isinstance(key, int)]
        )
        for workcenter in workcenters:
            if workcenter.crew_lane_count > 1:
                result[workcenter.id]["max_value"] *= workcenter.crew_lane_count
        return result

    @api.model
    def get_gantt_data(
        self,
        domain,
        groupby,
        read_specification,
        limit=None,
        offset=0,
        unavailability_fields=None,
        progress_bar_fields=None,
        start_date=None,
        stop_date=None,
        scale=None,
    ):
        """M21: при групиране по `crew_lane` — броят писти на центровете,
        активните ключалки и часовникът на сървъра (С10)."""
        data = super().get_gantt_data(
            domain,
            groupby,
            read_specification,
            limit=limit,
            offset=offset,
            unavailability_fields=unavailability_fields,
            progress_bar_fields=progress_bar_fields,
            start_date=start_date,
            stop_date=stop_date,
            scale=scale,
        )
        if not groupby or "crew_lane" not in groupby:
            return data
        self._crew_add_empty_workcenter_groups(data, groupby)
        workcenter_ids = set()
        for group in data.get("groups", []):
            value = group.get("workcenter_id")
            if value:
                workcenter_ids.add(value[0] if isinstance(value, (list, tuple)) else value)
        for record in data.get("records", []):
            value = record.get("workcenter_id")
            if isinstance(value, dict) and value.get("id"):
                workcenter_ids.add(value["id"])
        if not workcenter_ids:
            workcenter_ids = set(self.search(domain).workcenter_id.ids)
        workcenters = self.env["mrp.workcenter"].browse(sorted(workcenter_ids))
        data["crew_lanes"] = {wc.id: wc.crew_lane_count or 1 for wc in workcenters}
        data["crew_locks"] = self.env["mrp.workcenter.lane.lock"]._crew_active_locks(
            workcenters
        )
        data["server_now"] = fields.Datetime.to_string(fields.Datetime.now())
        # №142: дали потребителят е пуснал неработното време обратно.
        data["crew_show_off_time"] = bool(self.env.user.crew_gantt_show_off_time)
        # №146 на Теолино: кои хора са в бригадата на центъра — в етикета му.
        data["crew_names_label"] = workcenters._crew_names_label(start_date, stop_date)
        return data

    def _crew_add_empty_workcenter_groups(self, data, groupby):
        """Избраните центрове се виждат и без поръчки (Росен 12.10.2026).

        Ядрото разгъва празните групи само при ЕДНО ниво на групиране
        (`_web_read_group_field_expand`), а Гантът е по център и писта —
        затова центърът без поръчки изчезваше. Тук всеки избран център без
        група получава празна група с писта 1; останалите писти Гантът ги
        дорисува по `crew_lanes`, както досега. Избраните са от контекста:
        `crew_workcenter_ids` (изборът на центрове) или `crew_workcenter_id`
        (бутонът „Plan“) — НЕ от `default_workcenter_id` (Ф3: изтича към
        всяко create).
        """
        if groupby[0] != "workcenter_id":
            return
        context = self.env.context
        wanted = context.get("crew_workcenter_ids") or (
            [context["crew_workcenter_id"]] if context.get("crew_workcenter_id") else []
        )
        if not wanted:
            return
        groups = data.setdefault("groups", [])
        present = {
            value[0] if isinstance(value, (list, tuple)) else value
            for value in (group.get("workcenter_id") for group in groups)
            if value
        }
        workcenters = self.env["mrp.workcenter"].browse(wanted).exists()
        added = 0
        for workcenter in workcenters.filtered(lambda wc: wc.id not in present):
            group = {
                "workcenter_id": (workcenter.id, workcenter.display_name),
                "id:array_agg": [],
                "__extra_domain": [("workcenter_id", "=", workcenter.id)],
            }
            if "crew_lane" in groupby[1:2]:
                group["crew_lane"] = 1
                group["__extra_domain"] = group["__extra_domain"] + [("crew_lane", "=", 1)]
            groups.append(group)
            added += 1
        if not added:
            return
        data["length"] = data.get("length", 0) + added
        # Редът на центровете — като в ядрото (`mrp.workcenter._order`);
        # сортирането е стабилно, пистите на един център остават наред.
        order = {
            wc.id: index
            for index, wc in enumerate(
                self.env["mrp.workcenter"].browse(present | set(workcenters.ids)).sorted()
            )
        }
        groups.sort(
            key=lambda group: order.get(
                group["workcenter_id"][0] if group.get("workcenter_id") else 0, len(order)
            )
        )

    def crew_train_preview(self):
        """M22: проекцията на влака към СЕГА (без закръгляне) — само четене,
        същата функция като часовата задача (С8). Връща само поръчките,
        при които проекцията се различава или има тревога."""
        self.check_access("read")
        now = fields.Datetime.now()
        records = {}
        lanes = {
            (wo.workcenter_id, wo.crew_lane)
            for wo in self
            if wo.workcenter_id and wo.state in CREW_LANE_STATES
        }
        plans = {}
        alerts = set()
        for workcenter, lane in lanes:
            # 19.0.1.5.2: вагонът, чийто запис влакът не успя да направи,
            # стои — проекцията го показва там, където е в базата (Р36).
            plan = workcenter._crew_train_plan(
                lane, now, pinned=workcenter._crew_train_pinned(lane)
            )
            plans[workcenter, lane] = plan
            # 19.0.1.5.5: тревогата е на ДВЕТЕ страни, а наследникът по Р35
            # е в друга писта — затова всички конфликти се събират преди
            # отговора, не по писта (иначе наследникът не мигаше).
            alerts |= {successor.id for _pred, successor, _end in plan["conflicts"]}
            alerts |= {pred.id for pred, _successor, _end in plan["conflicts"]}
        for (workcenter, lane), plan in plans.items():
            moved = {move["workorder"].id: move for move in plan["moves"]}
            for wo in self.filtered(
                lambda w, wc=workcenter, ln=lane: w.workcenter_id == wc and w.crew_lane == ln
            ):
                move = moved.get(wo.id)
                if move:
                    start, stop = move["date_start"], move["date_finished"]
                else:
                    start, stop = wo.date_start, wo.date_finished
                stretch = 0.0
                if wo._crew_is_started() and wo.crew_planned_finish:
                    stretch = workcenter._crew_stretch_hours(
                        wo.crew_planned_finish, max(now, stop or now)
                    )
                overstretched = workcenter._crew_is_over(stretch)
                dep_alert = wo.id in alerts
                if move or overstretched or dep_alert:
                    records[wo.id] = {
                        "date_start": _dt(start),
                        "date_finished": _dt(stop),
                        "stretch_hours": stretch,
                        "overstretched": overstretched,
                        "dep_alert": dep_alert,
                    }
        return {"server_now": fields.Datetime.to_string(now), "records": records}

    # ------------------------------------------------------------------
    # Миграция 19.0.1.5.0 (§9.5)
    # ------------------------------------------------------------------

    @api.model
    def _crew_migrate_1_5_0(self):
        """1. `crew_planned_finish = date_finished` за започнатите
        неприключени; 2. САМО доклад за заварените застъпвания (писта 1)
        по центрове в лога — нищо не се мести; 3. влакът е изключен.
        Връща доклада {център: брой двойки}."""
        cr = self.env.cr
        self.flush_model()
        cr.execute(
            "UPDATE mrp_workorder SET crew_planned_finish = date_finished "
            "WHERE state = 'progress' AND crew_planned_finish IS NULL "
            "AND date_finished IS NOT NULL"
        )
        self.invalidate_model(["crew_planned_finish"])
        cr.execute(
            SQL(
                """
                SELECT a.workcenter_id, COUNT(*)
                  FROM mrp_workorder a
                  JOIN mrp_workorder b
                    ON b.workcenter_id = a.workcenter_id
                   AND b.crew_lane = a.crew_lane
                   AND b.id > a.id
                 WHERE a.state IN %(states)s
                   AND b.state IN %(states)s
                   AND b.date_start < a.date_finished
                   AND a.date_start < b.date_finished
                   AND NOT (%(a_started)s AND %(b_started)s)
                 GROUP BY a.workcenter_id
                 ORDER BY a.workcenter_id
                """,
                states=CREW_LANE_STATES,
                a_started=self._crew_started_sql("a"),
                b_started=self._crew_started_sql("b"),
            )
        )
        report = dict(cr.fetchall())
        for workcenter in self.env["mrp.workcenter"].browse(list(report)):
            _logger.warning(
                "Crew lanes 19.0.1.5.0: %s has %s overlapping pair(s) of work "
                "orders in lane 1; not moved (use Recompute).",
                workcenter.display_name,
                report[workcenter.id],
            )
        cron = self.env.ref(
            "mrp_workcenter_crew_roster.ir_cron_crew_train", raise_if_not_found=False
        )
        if cron:
            cron.active = False
        return report
