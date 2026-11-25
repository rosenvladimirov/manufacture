# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Пистите на центъра и влакът на времето (SPEC Р29–Р38, ADR 0002,
TECH_DESIGN §9): полетата на центъра, M14.1/M14.2 (слот с писти),
`_crew_walk`, M18 (влакът), Р35 и M19 (тревогата)."""
import logging
import math
from bisect import bisect_left
from datetime import datetime, timedelta
from itertools import accumulate

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import SQL, float_compare
from odoo.service.model import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY
from odoo.tools.misc import format_datetime

_logger = logging.getLogger(__name__)

# Контекстът, в който слотът се търси по стандарта, без писти (M14.2).
CREW_LANE_RAW = "crew_lane_raw"
# Контекстът, в който слотът се търси само в тази писта (M14.2).
CREW_SLOT_LANE = "crew_slot_lane"
# Контекстът на записите на влака (M18): M14.5 не се задейства.
CREW_TRAIN = "crew_train"
# Отлагане на M15: викащият я пуска сам накрая (M6, M14.4, M17, M18).
CREW_LANE_DEFER = "crew_lane_defer"
# Таванът на пистите на център (Р29, §9.2).
CREW_LANE_MAX = 20
# Отворените състояния на поръчка в пистата (М13).
# В 18 „blocked“ на 19 е две състояния: pending (чака друга РП) и waiting (материали).
CREW_LANE_STATES = ("pending", "waiting", "ready", "progress")
# МО, чиито поръчки влакът мести (M18) — като двигателя (M6.3).
CREW_TRAIN_MO_STATES = ("confirmed", "progress", "to_close")
TRAIN_TICK_PARAM = "mrp_workcenter_crew_roster.train_tick_minutes"
# Росен 12.10.2026: поставена след друга поръчка в пистата, новата почва
# секунда след края ѝ — „веднага след нея“, не в същия момент. Подготовката
# на центъра е в продължителността, затова разликата иначе е 0. Краят на
# поръчката не се мести (тя е с секунда по-къса) — иначе секундите се трупат
# по веригата и последната прелива през почивката или в другия ден.
CREW_GAP = timedelta(seconds=1)


def crew_whole_second(value):
    """Момент от хода по календара → цели секунди (находка 3 на проверката
    от 07.10): ред на календара до 24:00 е 23:59:59.999999 в ядрото, затова
    ходът през полунощ оставя край …:00.000001 и допирането изглежда като
    застъпване. Закръгля до най-близката секунда."""
    if not value:
        return value
    return (value + timedelta(microseconds=500000)).replace(microsecond=0)


class MrpWorkcenter(models.Model):
    _inherit = "mrp.workcenter"

    crew_lane_count = fields.Integer(
        string="Lanes",
        required=True,
        default=1,
        help="How many work orders the work center runs at the same time. A "
        "lane is a time band in which work orders follow each other without "
        "overlapping.",
    )
    crew_responsible_id = fields.Many2one(
        "res.users",
        string="Responsible",
        domain=[("share", "=", False)],
        check_company=True,
        help="Receives an activity when a started work order of the work "
        "center runs past its planned end for longer than the maximum stretch, "
        "and the notes about dependent work orders that the train did not move.",
    )
    crew_max_stretch_hours = fields.Float(
        string="Maximum Stretch (Hours)",
        default=0.0,
        help="A started work order running this many hours past its planned "
        "end raises an alert to the responsible. 0 disables the alert.",
    )
    # Росен 13.10.2026: при всяко местене първият незапочнат вагон в пистата
    # се залепва за влака. Изключването е за център, който умишлено държи
    # празнина пред първата поръчка.
    crew_snap_head = fields.Boolean(
        string="Attach to the Train",
        default=True,
        help="When a work order of the work center is moved, the first work "
        "order that has not started in the lane is pulled back to the train "
        "(now, or the end of the started work order before it), so the train "
        "can push the work orders behind it.",
    )
    # Печатът на M15: пише се само със SQL, без изглед (§9.2).
    crew_lane_stamp = fields.Integer(readonly=True, copy=False)

    @api.constrains("crew_lane_count")
    def _check_crew_lane_count(self):
        """Р29: 1 ≤ n ≤ 20; намаляване под заета писта → грешка с поръчките.
        Тук `@api.constrains` е безопасно — полето е на центъра (С15)."""
        WorkOrder = self.env["mrp.workorder"]
        for workcenter in self:
            if not 1 <= workcenter.crew_lane_count <= CREW_LANE_MAX:
                raise ValidationError(
                    self.env._(
                        "The number of lanes of %(wc)s must be between 1 and %(max)s.",
                        wc=workcenter.display_name,
                        max=CREW_LANE_MAX,
                    )
                )
            busy = WorkOrder.search(
                [
                    ("workcenter_id", "=", workcenter.id),
                    ("state", "in", CREW_LANE_STATES),
                    ("crew_lane", ">", workcenter.crew_lane_count),
                ]
            )
            if busy:
                raise ValidationError(
                    self.env._(
                        "%(wc)s cannot have %(count)s lane(s): these open work "
                        "orders are in a higher lane: %(wos)s.",
                        wc=workcenter.display_name,
                        count=workcenter.crew_lane_count,
                        wos=", ".join(busy.mapped("display_name")),
                    )
                )

    # ------------------------------------------------------------------
    # M14.1 / M14.2 — първият свободен слот с писти
    # ------------------------------------------------------------------

    def _crew_workorder_leaves(self, lane=None):
        """Leave-овете на поръчките на центъра; с `lane` — само на тези в
        ДРУГИТЕ писти (тях пистата `lane` не вижда, К1)."""
        self.ensure_one()
        self.env["mrp.workorder"].flush_model(["workcenter_id", "crew_lane", "leave_id"])
        query = SQL(
            "SELECT leave_id FROM mrp_workorder "
            "WHERE workcenter_id = %s AND leave_id IS NOT NULL",
            self.id,
        )
        if lane is not None:
            query = SQL("%s AND crew_lane != %s", query, lane)
        self.env.cr.execute(query)
        return self.env["resource.calendar.leaves"].browse(
            [row[0] for row in self.env.cr.fetchall()]
        )

    def _crew_first_slot_lanes(
        self,
        start,
        duration,
        forward=True,
        leaves_to_ignore=None,
        extra_leaves_slots=(),
        extra_by_lane=None,
        lanes=None,
    ):
        """M14.1: (писта, начало, край) на първия свободен слот по пистите
        или (False, False, съобщение).

        За всяка писта стандартното търсене пренебрегва leave-овете на
        поръчките в другите писти. Изборът: най-ранният край, после
        по-ранното начало, после по-малката писта; назад — най-късното начало.
        """
        self.ensure_one()
        count = max(self.crew_lane_count or 1, 1)
        lanes = list(lanes or range(1, count + 1))
        base = leaves_to_ignore or self.env["resource.calendar.leaves"]
        raw = self.with_context(**{CREW_LANE_RAW: True})
        best = None
        error = False
        for lane in lanes:
            ignore = base
            if count > 1:
                ignore |= self._crew_workorder_leaves(lane)
            extra = list(extra_leaves_slots) + list((extra_by_lane or {}).get(lane, []))
            date_from, date_to = raw._get_first_available_slot(
                start,
                duration,
                forward=forward,
                leaves_to_ignore=ignore,
                extra_leaves_slots=extra,
            )
            if not date_from:
                error = date_to
                continue
            if forward:
                key = (date_to, date_from, lane)
            else:
                key = (-date_from.timestamp(), -date_to.timestamp(), lane)
            if best is None or key < best[0]:
                best = (key, lane, date_from, date_to)
        if best is None:
            return False, False, error or self.env._("No available slot.")
        return best[1], crew_whole_second(best[2]), crew_whole_second(best[3])

    def _get_first_available_slot(
        self,
        start_datetime,
        duration,
        forward=True,
        leaves_to_ignore=False,
        extra_leaves_slots=[],  # noqa: B006 — сигнатурата на ядрото
    ):
        """M14.2: еднопистов център (или `crew_lane_raw`) — чистият стандарт;
        иначе най-рано свободната писта (или само `crew_slot_lane`). Така
        „Plan“, оценката на МО и EE reschedule виждат пистите (К6, К8, К11)."""
        if (
            self.env.context.get(CREW_LANE_RAW)
            or len(self) != 1
            or self.crew_lane_count <= 1
        ):
            return super()._get_first_available_slot(
                start_datetime,
                duration,
                forward=forward,
                leaves_to_ignore=leaves_to_ignore,
                extra_leaves_slots=extra_leaves_slots,
            )
        lane = self.env.context.get(CREW_SLOT_LANE)
        result = self._crew_first_slot_lanes(
            start_datetime,
            duration,
            forward=forward,
            leaves_to_ignore=leaves_to_ignore or None,
            extra_leaves_slots=extra_leaves_slots,
            lanes=[lane] if lane else None,
        )
        return result[1:]

    def _crew_walk(self, start, minutes, extra_leaves_slots=()):
        """Ходът по календара: `minutes` работно време от `start`, като
        прекъсванията по календара се прескачат (Р34). Поръчките на центъра
        не се гледат (веригата ги мести сама); leave `other` без поръчка и
        `extra_leaves_slots` се заобикалят. Връща (начало, край) или
        (False, съобщение)."""
        self.ensure_one()
        date_from, date_to = self.with_context(
            **{CREW_LANE_RAW: True}
        )._get_first_available_slot(
            start,
            minutes,
            leaves_to_ignore=self._crew_workorder_leaves(),
            extra_leaves_slots=list(extra_leaves_slots),
        )
        if not date_from:
            return date_from, date_to
        return crew_whole_second(date_from), crew_whole_second(date_to)

    def _crew_progress_slots(self, now, by_lane=False):
        """M6.7: заетостта на поръчките в progress, чийто планиран край е
        минал — [now, now + остатък]. С `by_lane` — речник писта → слотове
        (започнатата блокира само своята писта, §9.3 M6)."""
        self.ensure_one()
        slots = {} if by_lane else []
        workorders = self.env["mrp.workorder"].search(
            [("workcenter_id", "=", self.id), ("state", "=", "progress")]
        )
        for workorder in workorders:
            if workorder.date_finished and workorder.date_finished > now:
                continue
            remaining = (workorder.duration_expected or 0.0) - (workorder.duration or 0.0)
            if remaining <= 0:
                continue
            # №145: остатъкът е в човеко-минути — бригадата дели своя дял.
            remaining *= workorder._crew_window_factor(now)
            slot = (now, now + timedelta(minutes=remaining))
            if by_lane:
                slots.setdefault(workorder.crew_lane, []).append(slot)
            else:
                slots.append(slot)
        return slots

    # ------------------------------------------------------------------
    # M18 — влакът (Р34–Р36)
    # ------------------------------------------------------------------

    def _crew_lane_wagons(self, lane, exclude_ids=()):
        """Вагоните на пистата: отворените поръчки с дати, по начало и id."""
        self.ensure_one()
        workorders = self.env["mrp.workorder"].search(
            [
                ("workcenter_id", "=", self.id),
                ("crew_lane", "=", lane),
                ("state", "in", CREW_LANE_STATES),
                ("date_start", "!=", False),
                ("date_finished", "!=", False),
                ("id", "not in", list(exclude_ids)),
            ]
        )
        return workorders.sorted(lambda wo: (wo.date_start, wo.id))

    def _crew_train_pinned(self, lane, before=None):
        """Вагоните на пистата, чийто запис влакът последно не успя да
        направи (`crew_train_refused_since`): за проекцията M22 те стоят.

        19.0.1.5.4: `before` — само тези, които започват преди този момент
        (мястото на вмъкване в M17; вагоните след него се избутват)."""
        self.ensure_one()
        return set(
            self._crew_lane_wagons(lane)
            .filtered(
                lambda wo: wo.crew_train_refused_since
                and (before is None or wo.date_start < before)
            )
            .ids
        )

    def _crew_train_plan(
        self, lane, moment, exclude_ids=(), positions=None, pinned=()
    ):
        """Влакът на пистата към момента `moment` — ЧИСТО изчисление, без
        запис (С8: същата функция за часовата задача и за проекцията M22).

        - вагон от `pinned` (записът му е отказан, 19.0.1.5.2) и вагон на МО
          извън CREW_TRAIN_MO_STATES: неподвижна пречка на мястото си;
        - започнат вагон (десен теглич): началото е закотвено; край < T →
          край = T; `cursor = max(cursor, край)`;
        - незапочнат (ляв теглич): долната граница е
          `max(cursor, _crew_replan_earliest())` — същата точка за
          разширение като в двигателя M6. Начало ≥ границата и без
          застъпване с неподвижен → вагонът стои; край на минаването е само
          ако и нататък няма застъпване (с неподвижен или между два
          незапочнати, 19.0.1.5.3) и никой вагон не е преди границата си
          (19.0.1.5.5, находка 6ж); иначе ходът от границата със
          започнатите като заети слотове (прескача ги изцяло, В2).
        `positions` подменя началото/края на вагоните (проекцията в M17).

        Връща {moves, conflicts, errors}: ходовете (речници), зависимостите
        извън пистата, които новият край застъпва (Р35), и вагоните без слот.
        """
        self.ensure_one()
        positions = positions or {}
        params = None
        earliest = {}

        def span(wo):
            return positions.get(wo.id, (wo.date_start, wo.date_finished))

        def bound(wo):
            # Като M6 (_crew_plan_write): параметрите са нормализираните
            # входни данни; празната точка дава datetime.min. 19.0.1.5.5:
            # границата се смята веднъж на вагон — ползват я и обратният
            # проход (`clean_from`), и минаването.
            nonlocal params
            if wo.id not in earliest:
                if params is None:
                    params = self.env[
                        "mrp.workcenter.replan.batch"
                    ]._crew_normalize_params({"workcenter_ids": self.ids})
                earliest[wo.id] = wo._crew_replan_earliest(params) or datetime.min
            return earliest[wo.id]

        def floor(wo, cursor):
            return max(cursor, bound(wo))

        wagons = self._crew_lane_wagons(lane, exclude_ids).sorted(
            lambda wo: (span(wo)[0], wo.id)
        )

        moves = []
        new = {}
        fixed = []
        for wo in wagons:
            start, end = span(wo)
            if wo.id in pinned:
                new[wo.id] = (start, end)
                fixed.append((start, end))
            elif wo._crew_is_started():
                if end < moment:
                    new[wo.id] = (start, moment)
                    moves.append(self._crew_move(wo, lane, start, moment, "train", True))
                else:
                    new[wo.id] = (start, end)
                fixed.append(new[wo.id])
            elif wo.production_id.state not in CREW_TRAIN_MO_STATES:
                new[wo.id] = (start, end)
                fixed.append((start, end))

        # 19.0.1.5.3 (живият тест, 07.10): минаването НЕ спира на първия
        # валиден незапочнат вагон, ако по-нататък има заварено застъпване —
        # с неподвижен (започнат, чужда МО, закотвен отказан) или с
        # предходния незапочнат. Неподвижните са подредени по начало с
        # префиксен максимум на края: застъпването е O(log F), а „чисто ли е
        # оттук нататък“ — един обратен проход, O(N log F).
        # 19.0.1.5.5 (находка 6ж, Росен 07.10): „чисто“ значи и „никой
        # вагон нататък не почва преди границата си“
        # (`_crew_replan_earliest`) — иначе вагон след валиден участък
        # оставаше пред границата (напр. конфекция пред края на фолиото).
        fixed_sorted = sorted(fixed)
        fixed_starts = [s for s, _e in fixed_sorted]
        fixed_max_end = list(accumulate((e for _s, e in fixed_sorted), max))

        def overlaps_fixed(start, end):
            index = bisect_left(fixed_starts, end)
            return index > 0 and fixed_max_end[index - 1] > start

        movable = [wo for wo in wagons if wo.id not in new]
        clean_from = {}
        next_start = None
        clean = True
        for wo in reversed(movable):
            start, end = span(wo)
            clean = (
                clean
                and start >= bound(wo)
                and not overlaps_fixed(start, end)
                and (next_start is None or next_start >= end)
            )
            clean_from[wo.id] = clean
            next_start = start

        errors = []
        cursor = moment
        # Дали `cursor` е краят на поръчка (тогава новото място е секунда след
        # него), а не моментът на влака.
        after_wagon = False
        for wo in wagons:
            if wo.id in new:
                if (
                    wo.id in pinned
                    or wo._crew_is_started()
                    or wo.production_id.state not in CREW_TRAIN_MO_STATES
                ):
                    cursor = max(cursor, new[wo.id][1])
                    after_wagon = True
                continue
            start, end = span(wo)
            low = floor(wo, cursor)
            if start >= low and not overlaps_fixed(start, end):
                if clean_from[wo.id]:
                    # Краят на минаването: оттук нататък пистата е валидна.
                    break
                # Вагонът е на мястото си, но по-нататък има застъпване —
                # остава и минаването продължава.
                new[wo.id] = (start, end)
                cursor = max(cursor, end)
                after_wagon = True
                continue
            date_from, date_to = wo._crew_with_share(self)._crew_walk(
                low, wo.duration_expected, extra_leaves_slots=fixed
            )
            # Опира в края на предходния вагон → почва секунда след него;
            # краят остава от хода (секундите не се трупат по веригата и не
            # преливат през почивка или края на смяната — Росен 12.10.2026).
            if date_from and after_wagon and date_from == cursor:
                date_from += CREW_GAP
            if not date_from:
                errors.append((wo, date_to))
                new[wo.id] = (start, end)
                cursor = max(cursor, end)
                after_wagon = True
                continue
            new[wo.id] = (date_from, date_to)
            cursor = date_to
            after_wagon = True
            if (date_from, date_to) != (start, end):
                moves.append(self._crew_move(wo, lane, date_from, date_to, "train", False))

        conflicts = []
        for move in moves:
            wo = move["workorder"]
            for successor in wo.needed_by_workorder_ids:
                if successor.state not in CREW_LANE_STATES or not successor.date_start:
                    continue
                if successor.workcenter_id == self and successor.crew_lane == lane:
                    continue
                succ_start = positions.get(successor.id, (successor.date_start,))[0]
                if succ_start < move["date_finished"]:
                    conflicts.append((wo, successor, move["date_finished"]))
        return {"moves": moves, "conflicts": conflicts, "errors": errors}

    def _crew_move(self, workorder, lane, date_start, date_finished, reason, started):
        """Един ход на плана (за M17, M18 и партидата)."""
        return {
            "workorder": workorder,
            "old_workcenter": workorder.workcenter_id,
            "old_lane": workorder.crew_lane,
            "old_date_start": workorder.date_start,
            "old_date_finished": workorder.date_finished,
            "old_duration": workorder.duration_expected,
            "workcenter": self,
            "lane": lane,
            "date_start": date_start,
            "date_finished": date_finished,
            "duration": workorder.duration_expected,
            "reason": reason,
            "started": started,
        }

    def _crew_apply_moves(self, moves):
        """Записът на ходовете на влака/веригата (под `crew_lane_defer`,
        `crew_train` за разтягането и bypass): незапочнат — начало и край;
        започнат — само краят (`duration_expected` не се пипа, П7).
        M15 НЕ се пуска тук — викащият е длъжен (П17)."""
        WorkOrder = self.env["mrp.workorder"]
        touched = WorkOrder
        for move in moves:
            wo = move["workorder"].with_context(
                **{CREW_LANE_DEFER: True, "bypass_duration_calculation": True}
            )
            if move["started"]:
                wo.with_context(**{CREW_TRAIN: True}).write(
                    {"date_finished": move["date_finished"]}
                )
            else:
                vals = {
                    "date_start": move["date_start"],
                    "date_finished": move["date_finished"],
                }
                if move.get("set_duration"):
                    vals["duration_expected"] = move["duration"]
                if wo.crew_lane != move["lane"]:
                    vals["crew_lane"] = move["lane"]
                if move["reason"] == "train":
                    wo = wo.with_context(**{CREW_TRAIN: True})
                wo.write(vals)
            touched |= move["workorder"]
        return touched

    def _crew_train_lane(self, lane, moment):
        """Прилага влака на пистата (M18): планът, записът, M15 върху
        пипнатите. Връща плана (с „mo_snapshot“ — датите на МО преди, и
        „refused“ — [(поръчка, съобщение)] на вагоните, които стоят).

        19.0.1.5.2: опитът е в savepoint. Отказ (UserError/ValidationError,
        напр. чуждо ограничение по датите на МО) при запис на ЕДИН вагон
        връща опита; вагонът става неподвижна пречка на мястото си
        (`pinned`) и планът се смята наново без него. Всеки кръг закотвя
        поне един нов вагон, затова кръговете са най-много колкото ходовете.
        Отказ, който не е от запис на вагон (M15 накрая), пуска грешката
        нагоре — пистата се пропуска както досега."""
        self.ensure_one()
        WorkOrder = self.env["mrp.workorder"]
        pinned = {}
        while True:
            plan = self._crew_train_plan(lane, moment, pinned=pinned)
            plan["refused"] = list(pinned.values())
            plan["mo_snapshot"] = {
                mo.id: (mo.date_start, mo.date_finished)
                for mo in WorkOrder.union(
                    *[m["workorder"] for m in plan["moves"]]
                ).production_id
            }
            if not plan["moves"]:
                return plan
            failed = None
            try:
                with self.env.cr.savepoint():
                    touched = WorkOrder
                    for move in plan["moves"]:
                        try:
                            touched |= self._crew_apply_moves([move])
                        except (UserError, ValidationError) as error:
                            failed = (move["workorder"], error)
                            raise
                    touched._crew_check_lane_overlap()
            except (UserError, ValidationError):
                if failed is None:
                    raise
                wo, error = failed
                pinned[wo.id] = (wo, str(error.args[0] if error.args else error))
                continue
            return plan

    @api.model
    def _crew_train_tick(self, now=None):
        """T = сега, закръглено надолу до `train_tick_minutes` (по
        подразбиране 60): повторен пуск в същия час не мести нищо (П8)."""
        now = now or fields.Datetime.now()
        value = self.env["ir.config_parameter"].sudo().get_param(TRAIN_TICK_PARAM, "60")
        try:
            tick = max(int(float(value)), 1)
        except (TypeError, ValueError):
            tick = 60
        minutes = now.hour * 60 + now.minute
        floor = minutes - minutes % tick
        return now.replace(
            hour=floor // 60, minute=floor % 60, second=0, microsecond=0
        )

    @api.model
    def _cron_crew_train(self):
        """Часовата задача „Crew: train“ (M18): активните центрове с
        календар, под sudo, по фирми; след всеки център — commit (К15),
        но само когато сме в cron (тестовете не комитват).

        Находка 2 на проверката от 07.10: всеки център е в savepoint;
        грешка от едновременен запис (serialization, deadlock — операторът
        пише същата започната поръчка) връща само този център и задачата
        продължава. В cron-а провалените се опитват още веднъж накрая —
        след commit-а снимъкът е свеж. `remaining` казва колко остава
        (с повторенията), иначе ir.cron отчита пуска като FAILED."""
        moment = self._crew_train_tick()
        workcenters = (
            self.sudo()
            .search([("resource_calendar_id", "!=", False)])
            .sorted(lambda wc: (wc.company_id.id, wc.id))
        )
        in_cron = bool(self.env.context.get("ir_cron_progress_id"))
        failed = []
        done = 0
        for index, workcenter in enumerate(workcenters):
            if not workcenter._crew_train_safe(moment):
                failed.append(workcenter)
            if in_cron:
                done += 1
                left = len(workcenters) - index - 1
                self._crew_commit_progress(done, left + len(failed))
        if in_cron:
            for index, workcenter in enumerate(failed):
                workcenter._crew_train_safe(moment)
                done += 1
                self._crew_commit_progress(done, len(failed) - index - 1)
        return True

    def _crew_commit_progress(self, done, remaining):
        """В 18 няма ir.cron._commit_progress (дошъл в 19): прогресът се
        записва с _notify_progress и стъпката се commit-ва."""
        self.env["ir.cron"]._notify_progress(done=done, remaining=remaining)
        self.env.cr.commit()

    def _crew_train_safe(self, moment):
        """`_crew_train` за един център в savepoint. Грешка от едновременен
        запис → връща центъра, ред в лога, False."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self.with_company(self.company_id)._crew_train(moment)
        except PG_CONCURRENCY_EXCEPTIONS_TO_RETRY as error:
            _logger.warning(
                "Crew train: %s skipped this run (concurrent update): %s",
                self.display_name,
                error,
            )
            return False
        return True

    def _crew_train(self, moment):
        """M18 за центровете в `self`: всяка писта в savepoint; заключена от
        човек → пропуска се. После: датите на МО, нарядът, партида `train`
        само при ход, Р35 (бележки за зависимостите), шината и M19."""
        Lock = self.env["mrp.workcenter.lane.lock"]
        Batch = self.env["mrp.workcenter.replan.batch"]
        for workcenter in self:
            if not workcenter.resource_calendar_id:
                continue
            moves = []
            conflicts = []
            refused = []
            lanes_done = []
            snapshot = {}
            for lane in range(1, max(workcenter.crew_lane_count, 1) + 1):
                if Lock._crew_lane_locked(workcenter, lane):
                    _logger.info(
                        "Crew train: lane %s of %s is locked, skipped.",
                        lane,
                        workcenter.display_name,
                    )
                    continue
                try:
                    with self.env.cr.savepoint():
                        plan = workcenter._crew_train_lane(lane, moment)
                except (UserError, ValidationError) as error:
                    _logger.warning(
                        "Crew train: lane %s of %s skipped: %s",
                        lane,
                        workcenter.display_name,
                        error,
                    )
                    continue
                for wo, message in plan["errors"]:
                    _logger.warning(
                        "Crew train: %s not moved: %s", wo.display_name, message
                    )
                moves += plan["moves"]
                conflicts += plan["conflicts"]
                refused += plan["refused"]
                lanes_done.append(lane)
                for mo_id, dates in plan["mo_snapshot"].items():
                    snapshot.setdefault(mo_id, dates)
            if moves:
                batch = Batch._crew_record_moves(
                    "train", moves, workcenter, snapshot=snapshot
                )
                touched = batch.line_ids.workorder_id
                batch._crew_finish_moves(touched)
                Lock._crew_lane_notify(
                    workcenter,
                    "changed",
                    {
                        "workcenter_ids": workcenter.ids,
                        "workorder_ids": touched.ids,
                        "source": "train",
                    },
                )
            workcenter._crew_refusal_notes(refused, lanes_done, moment)
            workcenter._crew_dependency_notes(conflicts, moment)
            workcenter._crew_stretch_alarm(moment)
        return True

    def _crew_refusal_notes(self, refused, lanes, moment):
        """19.0.1.5.2: вагоните, чийто запис влакът не успя да направи
        (`_crew_train_lane`, „refused“) — ред в лога всеки път; бележка в
        chatter-а на МО до отговорника на центъра само първия път (като
        Р35: `crew_train_refused_since` пази от повторение, докато отказът
        трае). Без отговорник — само логът. Флагът се слага и без
        отговорник: по него проекцията M22 оставя вагона на мястото му.
        В обработените писти (`lanes`) флагът на вагоните, които този път
        не са отказани, се чисти."""
        self.ensure_one()
        WorkOrder = self.env["mrp.workorder"]
        responsible = self.crew_responsible_id
        flagged = WorkOrder
        for wo, message in refused:
            flagged |= wo
            _logger.warning(
                "Crew train: %s of %s stays in place, its new dates are "
                "refused: %s",
                wo.display_name,
                self.display_name,
                message,
            )
            if wo.crew_train_refused_since:
                continue
            if responsible:
                body = self.env._(
                    "The train could not move %(wo)s (%(error)s). It stays at "
                    "%(start)s until the cause is removed.",
                    wo=wo.display_name,
                    error=message.strip().rstrip("."),
                    start=format_datetime(self.env, wo.date_start),
                )
                wo.production_id.sudo().message_post(
                    body=body,
                    partner_ids=responsible.partner_id.ids,
                    subtype_xmlid="mail.mt_note",
                )
            wo.sudo().write({"crew_train_refused_since": moment})
        if lanes:
            stale = WorkOrder.search(
                [
                    ("workcenter_id", "=", self.id),
                    ("crew_lane", "in", list(lanes)),
                    ("crew_train_refused_since", "!=", False),
                    ("id", "not in", flagged.ids),
                ]
            )
            if stale:
                stale.sudo().write({"crew_train_refused_since": False})

    # ------------------------------------------------------------------
    # Р35 — зависимостите, които влакът не мести
    # ------------------------------------------------------------------

    def _crew_dependency_notes(self, conflicts, moment):
        """Р35: зависима N извън пистата с начало < новия край на M →
        бележка в chatter-а на МО на N до отговорника на центъра на N
        (резерва: на центъра на M, после отговорникът на МО). Веднъж:
        `crew_dep_conflict_since` пази от повторение; изчезналият
        конфликт чисти полето."""
        self.ensure_one()
        flagged = self.env["mrp.workorder"]
        for predecessor, successor, end in conflicts:
            flagged |= successor
            if successor.crew_dep_conflict_since:
                continue
            responsible = (
                successor.workcenter_id.crew_responsible_id
                or predecessor.workcenter_id.crew_responsible_id
                or successor.production_id.user_id
            )
            body = self.env._(
                "%(pred)s now ends at %(end)s, after the planned start of "
                "%(wo)s (%(start)s). The train did not move it.",
                pred=predecessor.display_name,
                end=format_datetime(self.env, end),
                wo=successor.display_name,
                start=format_datetime(self.env, successor.date_start),
            )
            successor.production_id.sudo().message_post(
                body=body,
                partner_ids=responsible.partner_id.ids,
                subtype_xmlid="mail.mt_note",
            )
            successor.sudo().write({"crew_dep_conflict_since": moment})
        # Изчезналите конфликти: зависимите от поръчки на центъра, които
        # вече не са застъпени от предшественик.
        stale = self.env["mrp.workorder"].search(
            [
                ("crew_dep_conflict_since", "!=", False),
                ("blocked_by_workorder_ids.workcenter_id", "=", self.id),
                ("id", "not in", flagged.ids),
            ]
        )
        for successor in stale:
            still = successor.state in CREW_LANE_STATES and any(
                pred.state in CREW_LANE_STATES
                and pred.date_finished
                and successor.date_start
                and pred.date_finished > successor.date_start
                for pred in successor.blocked_by_workorder_ids
            )
            if not still:
                successor.sudo().write({"crew_dep_conflict_since": False})

    # ------------------------------------------------------------------
    # M19 — тревогата (Р37)
    # ------------------------------------------------------------------

    def _crew_stretch_hours(self, planned_finish, end):
        """Разтягането в РАБОТНИ часове по календара на центъра между
        планирания край при старта и `end` (В4: нощта и почивните не се
        броят)."""
        self.ensure_one()
        if not planned_finish or not end or end <= planned_finish:
            return 0.0
        calendar = self.resource_calendar_id
        if not calendar:
            return (end - planned_finish).total_seconds() / 3600.0
        return calendar.get_work_duration_data(planned_finish, end)["hours"]

    def _crew_is_over(self, stretch):
        """Над максимума: max > 0 и разтягането ≥ max (k ≥ 1 в M19)."""
        self.ensure_one()
        maximum = self.crew_max_stretch_hours
        return bool(
            maximum > 0 and float_compare(stretch, maximum, precision_digits=4) >= 0
        )

    def _crew_stretch_alarm(self, moment):
        """M19: за всяка започната неприключена поръчка с
        `crew_planned_finish` — разтягането се записва; при
        k = ⌊разтягане / max⌋ ≥ 1 и k > нивото: дейност на МО за
        отговорника, бележка в chatter-а на МО, нивото = k. Без отговорник —
        само бележката."""
        self.ensure_one()
        workorders = self.env["mrp.workorder"].search(
            [
                ("workcenter_id", "=", self.id),
                ("state", "=", "progress"),
                ("crew_planned_finish", "!=", False),
            ]
        )
        maximum = self.crew_max_stretch_hours
        responsible = self.crew_responsible_id
        for wo in workorders:
            end = max(moment, wo.date_finished or moment)
            stretch = self._crew_stretch_hours(wo.crew_planned_finish, end)
            vals = {}
            if float_compare(stretch, wo.crew_stretch_hours, precision_digits=4):
                vals["crew_stretch_hours"] = stretch
            if maximum > 0:
                level = int(math.floor(stretch / maximum + 1e-9))
                if level >= 1 and level > wo.crew_stretch_alert_level:
                    wo._crew_send_stretch_alert(stretch, maximum, responsible)
                    vals["crew_stretch_alert_level"] = level
            if vals:
                wo.sudo().write(vals)

    def _crew_stretch_summary(self, workorder, stretch, maximum):
        return self.env._(
            "%(wo)s: %(h).1f h past its planned end (max %(max).1f h)",
            wo=workorder.display_name,
            h=stretch,
            max=maximum,
        )


class MrpWorkorderStretch(models.Model):
    _inherit = "mrp.workorder"

    def _crew_send_stretch_alert(self, stretch, maximum, responsible):
        """Р37: дейност на МО за отговорника + бележка в chatter-а на МО
        (поръчката няма chatter, К12/В5)."""
        self.ensure_one()
        production = self.production_id.sudo()
        summary = self.workcenter_id._crew_stretch_summary(self, stretch, maximum)
        if responsible:
            production.activity_schedule(
                "mail.mail_activity_data_todo",
                date_deadline=fields.Date.context_today(self),
                summary=summary,
                user_id=responsible.id,
            )
        production.message_post(
            body=Markup("<p>%s</p>") % summary,
            partner_ids=responsible.partner_id.ids,
            subtype_xmlid="mail.mt_note",
        )
