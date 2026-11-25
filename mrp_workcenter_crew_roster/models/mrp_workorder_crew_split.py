# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
import hashlib
import json
from collections import defaultdict
from datetime import datetime, time, timedelta

from pytz import utc

from odoo import fields, models

# Типовете време, които се делят между хората от наряда (Р26): реалното
# продуктивно време и „намалената скорост“ (performance).
CREW_SPLIT_LOSS_TYPES = ("productive", "performance")
# Колко дни около редовете се търсят блокове, за да има предходен/следващ
# блок за парче извън смените (M5.2) — и при календар пон–пет.
CREW_SPLIT_PAD_DAYS = 8


def _seconds(start, end):
    """Дължината на интервала в цели секунди."""
    return int((end - start).total_seconds())


def _union(spans):
    """Обединението на интервалите (начало, край): подредено и слято."""
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _real_spans(union, offset, length):
    """Отрязъкът [offset, offset + length) от СВИТОТО време (секунди от
    началото на `union`, без празнините) — върнат в реално време и разрязан
    по празнините на `union`."""
    result = []
    position = 0
    stop = offset + length
    for start, end in union:
        size = _seconds(start, end)
        low, high = max(offset, position), min(stop, position + size)
        if low < high:
            result.append(
                (
                    start + timedelta(seconds=low - position),
                    start + timedelta(seconds=high - position),
                )
            )
        position += size
        if position >= stop:
            break
    return result


def crew_layout(total, covered, count):
    """Подреждането от M5.5 в свитото време.

    `total` е S (човекосекунди), `covered` е U (секунди на обединението),
    `count` е N. Връща за всеки човек (подредени по id) списък от парчета
    (отместване, дължина) в [0, U).

    - L = S // N; последният взима остатъка, за да е сборът точно S;
    - човек i почва в τᵢ = i·(U − Lₙ)/(N − 1) (цели секунди, надолу);
      понеже S ≥ U, стъпката е ≤ L и U се покрива изцяло;
    - дял ≥ U (работили са повече хора от наряда, Р20) се реже на
      застъпващи се парчета за същия човек: L // U цели U и остатък.
    """
    if count <= 0 or total <= 0 or covered <= 0:
        return [[] for _i in range(max(count, 0))]
    share = total // count
    lengths = [share] * (count - 1) + [total - share * (count - 1)]
    longest = lengths[-1]
    layout = []
    for index, length in enumerate(lengths):
        if length <= 0:
            layout.append([])
        elif length >= covered:
            pieces = [(0, covered)] * (length // covered)
            if length % covered:
                pieces.append((0, length % covered))
            layout.append(pieces)
        elif longest < covered:
            # Никой не покрива U сам: стълба от N души, последният свършва в U.
            layout.append([(index * (covered - longest) // (count - 1), length)])
        else:
            # Последният покрива U сам; останалите се разпръскват в U.
            layout.append([(index * (covered - length) // (count - 1), length)])
    return layout


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    crew_time_original = fields.Json(
        string="Original Time Log",
        readonly=True,
        copy=False,
        help="The time log of the work order before the first split of the "
        "time among the crew (audit).",
    )
    crew_split_signature = fields.Char(
        string="Crew Split Signature",
        readonly=True,
        copy=False,
        help="Fingerprint of the shifts, crews and times of the last split of "
        "the time among the crew. While it does not change, the work order "
        "is not split again.",
    )

    # ------------------------------------------------------------------
    # M4 — кука при приключване
    # ------------------------------------------------------------------

    def button_finish(self):
        """M4: след приключването времето се дели между наряда (M5).

        Всички пътища към `done` минават оттук (action_mark_as_done,
        do_finish, post_record_production, button_mark_done на МО). Ако няма
        реални редове, M5 създава планираните още тук — тогава EE
        `_set_default_time_log` и `_post_inventory` на МО ги пропускат.
        """
        todo = self.filtered(lambda wo: wo.state not in ("done", "cancel"))
        res = super().button_finish()
        todo.filtered(lambda wo: wo.state == "done")._crew_split_time()
        return res

    # ------------------------------------------------------------------
    # M5 — разделянето на времето
    # ------------------------------------------------------------------

    def _crew_split_time(self, recompute=False):
        """M5: дели отработеното време на всяка поръчка между хората от
        наряда на всяка смяна, през която е минала (Р3, Р7, Р19–Р21, Р23, Р26).

        `recompute=True` е пътят на „Преизчисли“ (стъпка 5): включва
        гардовете от M5.9.

        Връща {id на поръчката: резултат}; резултатът е един от:
        `split` (разделено), `unchanged` (подписът е същият), `no_crew`
        (никоя смяна няма наряд — редовете остават), `no_time`,
        `no_shift`, `mo_done` и `posted` (гардовете на „Преизчисли“).
        """
        return {wo.id: wo._crew_split_one(recompute) for wo in self}

    def _crew_split_one(self, recompute=False):
        self.ensure_one()
        Productivity = self.env["mrp.workcenter.productivity"].sudo()
        if recompute:
            # M5.9: приключена МО или осчетоводено време не се пипат.
            if self.production_id.state == "done":
                return "mo_done"
            if "account_move_line_id" in Productivity._fields and any(
                line.account_move_line_id for line in self.sudo().time_ids
            ):
                return "posted"

        fragments = self._crew_split_sources()
        if not fragments:
            return "no_time"
        blocks = self._crew_split_blocks(
            min(f[0] for f in fragments), max(f[1] for f in fragments)
        )
        if not blocks:
            return "no_shift"

        # M5.2: парчетата по блокове и тип (Р19).
        groups = defaultdict(list)
        for start, end, line, loss_type, loss in fragments:
            for index, piece_start, piece_end in self._crew_cut(
                blocks, start, end, self.workcenter_id._crew_calendar_tz()
            ):
                groups[(index, loss_type)].append((piece_start, piece_end, line, loss))

        crews = self._crew_split_crews(blocks, {index for index, _t in groups})
        signature = self._crew_split_signature(blocks, groups, crews)
        if signature == self.crew_split_signature:
            # M5.8: нищо не се е сменило — поръчката не се пипа.
            return "unchanged"
        crewed = {index for index, crew in crews.items() if crew}
        if not crewed:
            # Никоя смяна няма наряд (или всички са в отпуск): редовете
            # остават, както са отчетени.
            return "no_crew"

        # Заменят се само редовете, които имат парче в смяна с наряд;
        # парчетата им в смени без наряд се пресъздават, както са отчетени.
        replaced = Productivity.browse()
        for (index, _loss_type), pieces in groups.items():
            if index in crewed:
                for _s, _e, line, _l in pieces:
                    if line:
                        replaced |= line
        vals_list = []
        for (index, _loss_type), pieces in sorted(groups.items(), key=lambda g: g[0]):
            if index in crewed:
                vals_list += self._crew_split_share_vals(pieces, crews[index])
                continue
            for start, end, line, loss in pieces:
                if not line:
                    # Планирано време в смяна без наряд — като стандарта
                    # (служителят идва от потребителя).
                    vals_list.append(self._crew_split_line_vals(loss, None, start, end))
                elif line in replaced:
                    vals = self._crew_split_line_vals(loss, line.employee_id, start, end)
                    vals.update(user_id=line.user_id.id, description=line.description)
                    vals_list.append(vals)

        write_vals = {"crew_split_signature": signature}
        if not self.crew_time_original:
            # M5.7: одитът е само от първото разделяне.
            write_vals["crew_time_original"] = self._crew_split_original(fragments)
        self._crew_split_replace(vals_list, replaced)
        self.sudo().write(write_vals)
        return "split"

    def _crew_split_sources(self):
        """M5.1: (начало, край, ред, тип, загуба) на времето, което се дели.

        Реалните редове `productive`/`performance` с край (секундите са
        цели, като в `duration`). Без такива — виртуален интервал
        [край − duration_expected, край] без повторно × time_efficiency
        (Р21: ефективността вече е в duration_expected).
        """
        lines = self.sudo().time_ids.filtered(
            lambda t: t.loss_type in CREW_SPLIT_LOSS_TYPES
            and t.date_start
            and t.date_end
        )
        fragments = []
        for line in lines.sorted(lambda t: (t.date_start, t.id)):
            start = line.date_start.replace(microsecond=0)
            end = line.date_end.replace(microsecond=0)
            if end > start:
                fragments.append((start, end, line, line.loss_type, line.loss_id))
        if lines:
            return fragments
        seconds = int(round((self.duration_expected or 0.0) * 60))
        end = self._crew_split_virtual_end()
        if seconds <= 0 or not end:
            return []
        loss = self.env["mrp.workcenter.productivity.loss"].sudo().search(
            [("loss_type", "=", "productive")], limit=1
        )
        if not loss:
            return []
        end = end.replace(microsecond=0)
        return [(end - timedelta(seconds=seconds), end, None, "productive", loss)]

    def _crew_split_virtual_end(self):
        """Краят на виртуалния интервал (без реални редове): по подразбиране
        приключването. Контекстът crew_split_end_at (UTC, datetime или
        низ) го мести — напр. часът, в който монтажникът е ИЗПРАТИЛ отчета,
        когато одобрението идва ден по-късно (Теолино №173: минутите отиват
        при наряда от деня на отчета, не от деня на одобрението)."""
        self.ensure_one()
        end_at = self.env.context.get("crew_split_end_at")
        if end_at:
            return fields.Datetime.to_datetime(end_at)
        return self.date_finished

    def _crew_split_blocks(self, date_from, date_to):
        """Блоковете на центъра около [date_from, date_to] (UTC без tz),
        подредени по начало, с границите в UTC без tz (`start_utc`/`stop_utc`)."""
        workcenter = self.workcenter_id
        if not workcenter or not workcenter._crew_shift_supported():
            return []
        pad = timedelta(days=CREW_SPLIT_PAD_DAYS)
        blocks = workcenter._crew_shift_blocks(
            utc.localize(date_from - pad), utc.localize(date_to + pad)
        )
        result = []
        for block in sorted(blocks, key=lambda b: b["start"]):
            result.append(
                dict(
                    block,
                    start_utc=block["start"].astimezone(utc).replace(tzinfo=None),
                    stop_utc=block["stop"].astimezone(utc).replace(tzinfo=None),
                )
            )
        return result

    @staticmethod
    def _crew_cut(blocks, start, end, tz=utc):
        """Реже [start, end) по границите на блоковете (M5.2, Р19).

        Връща (индекс на блока, начало, край) за всяко парче. Парче в
        празнина между блоковете (решение 06.10):
        - ПРЕДИ началото на следващия блок в същия местен ден (`tz` на
          календара, напр. 07:50–08:00) — към следващия блок;
        - иначе (след края на смяната, напр. 17:00–17:10) — към предходния;
        - ако от едната страна няма блок — към другата.
        Празнините се режат и в местната полунощ, за да е ясен денят на
        всяко парче.
        """
        points = {start, end}
        for block in blocks:
            for point in (block["start_utc"], block["stop_utc"]):
                if start < point < end:
                    points.add(point)

        def local_date(moment):
            return utc.localize(moment).astimezone(tz).date()

        def in_block(moment):
            return any(b["start_utc"] < moment < b["stop_utc"] for b in blocks)

        day = local_date(start) + timedelta(days=1)
        while day <= local_date(end):
            midnight = (
                tz.localize(datetime.combine(day, time.min))
                .astimezone(utc)
                .replace(tzinfo=None)
            )
            if start < midnight < end and not in_block(midnight):
                points.add(midnight)
            day += timedelta(days=1)
        points = sorted(points)
        result = []
        for piece_start, piece_end in zip(points, points[1:]):
            index = None
            for i, block in enumerate(blocks):
                if block["start_utc"] <= piece_start and piece_end <= block["stop_utc"]:
                    index = i
                    break
            if index is None:
                before = [i for i, b in enumerate(blocks) if b["stop_utc"] <= piece_start]
                after = [i for i, b in enumerate(blocks) if b["start_utc"] >= piece_end]
                if after and (
                    not before
                    or local_date(piece_start) == blocks[after[0]]["start"].date()
                ):
                    index = after[0]
                else:
                    index = before[-1]
            result.append((index, piece_start, piece_end))
        return result

    def _crew_split_crews(self, blocks, indexes):
        """M5.4: екипът на всеки блок = нарядът минус хората в отпуск.

        Подредени по id. Без наряд за блока — празен екип.
        """
        Employee = self.env["hr.employee"]
        days = list({blocks[i]["date"] for i in indexes})
        rosters = (
            self.env["mrp.workcenter.roster"]
            .sudo()
            .search([("workcenter_id", "=", self.workcenter_id.id), ("date", "in", days)])
        )
        by_shift = {(r.date, r.shift_key): r.employee_ids for r in rosters}
        crews = {}
        for index in indexes:
            block = blocks[index]
            crew = by_shift.get((block["date"], block["key"]), Employee)
            if crew:
                crew = crew - self._crew_absent(crew, block)
            crews[index] = crew.sorted("id")
        return crews

    def _crew_absent(self, employees, block):
        """Хората с одобрен отпуск, който се застъпва с блока (Р9, Р23).

        - под sudo (Ф2): правилото на hr.leave показва на потребител без HR
          права само собствения му отпуск, а операторът в Shop Floor е такъв;
        - само `time_type = leave`: командировката (`other`) не изключва;
        - частичен отпуск изключва човека от ЦЕЛИЯ блок.
        """
        leaves = (
            self.env["hr.leave"]
            .sudo()
            .search(
                [
                    ("employee_id", "in", employees.ids),
                    ("state", "=", "validate"),
                    ("holiday_status_id.time_type", "=", "leave"),
                    ("date_from", "<", block["stop_utc"]),
                    ("date_to", ">", block["start_utc"]),
                ]
            )
        )
        return leaves.employee_id

    @staticmethod
    def _crew_split_signature(blocks, groups, crews):
        """M5.8: хеш на блока, екипа, S и U (с границите на обединението)."""
        payload = []
        for (index, loss_type), pieces in sorted(groups.items(), key=lambda g: g[0]):
            block = blocks[index]
            union = _union([(s, e) for s, e, _line, _loss in pieces])
            payload.append(
                [
                    block["date"].isoformat(),
                    block["key"],
                    loss_type,
                    sum(_seconds(s, e) for s, e, _line, _loss in pieces),
                    [[s.isoformat(), e.isoformat()] for s, e in union],
                    crews[index].ids,
                ]
            )
        return hashlib.sha256(json.dumps(payload).encode()).hexdigest()

    def _crew_split_share_vals(self, pieces, crew):
        """M5.3 и M5.5 за един (блок, тип): S и U в секунди, подреждането,
        по един или повече реда на човек. Загубата е тази с най-голям дял
        в източника."""
        total = sum(_seconds(s, e) for s, e, _line, _loss in pieces)
        union = _union([(s, e) for s, e, _line, _loss in pieces])
        covered = sum(_seconds(s, e) for s, e in union)
        weight = defaultdict(int)
        for start, end, _line, loss in pieces:
            weight[loss] += _seconds(start, end)
        loss = max(weight, key=lambda lo: (weight[lo], -lo.id))
        vals_list = []
        for employee, parts in zip(crew, crew_layout(total, covered, len(crew))):
            for offset, length in parts:
                for start, end in _real_spans(union, offset, length):
                    vals_list.append(self._crew_split_line_vals(loss, employee, start, end))
        return vals_list

    def _crew_split_line_vals(self, loss, employee, start, end):
        """Стойностите на нов ред време. `employee=None` — служителят се
        изчислява от потребителя (като в стандарта)."""
        vals = {
            "workorder_id": self.id,
            "workcenter_id": self.workcenter_id.id,
            "company_id": self.company_id.id,
            "loss_id": loss.id,
            "user_id": self.env.uid,
            "date_start": start,
            "date_end": end,
        }
        if employee is not None:
            vals["employee_id"] = employee.id
            vals["description"] = self.env._(
                "Crew share: %(employee)s", employee=employee.name
            )
        return vals

    def _crew_split_replace(self, vals_list, old_lines):
        """M5.6: новите редове се СЪЗДАВАТ (с `employee_id` изрично), после
        старите се трият. Никога `write` на `employee_id`: при приключена
        поръчка ставката на реда е замразена (E mrp_workcenter.py:67-75)."""
        new_lines = self.env["mrp.workcenter.productivity"].sudo().create(vals_list)
        old_lines.sudo().unlink()
        return new_lines

    def _crew_split_original(self, fragments):
        """Одитът (M5.7): всички редове време преди първото разделяне, плюс
        виртуалният интервал, ако е делено планираното време (Р21)."""
        lines = self.sudo().time_ids
        virtual = [
            {
                "virtual": True,
                "date_start": fields.Datetime.to_string(start),
                "date_end": fields.Datetime.to_string(end),
                "loss_type": loss_type,
            }
            for start, end, line, loss_type, _loss in fragments
            if not line
        ]
        return virtual + [
            {
                "id": line.id,
                "employee_id": line.employee_id.id,
                "user_id": line.user_id.id,
                "loss_id": line.loss_id.id,
                "loss_type": line.loss_type,
                "date_start": fields.Datetime.to_string(line.date_start),
                "date_end": fields.Datetime.to_string(line.date_end),
                "duration": line.duration,
            }
            for line in lines.sorted(lambda t: (t.date_start, t.id))
        ]
