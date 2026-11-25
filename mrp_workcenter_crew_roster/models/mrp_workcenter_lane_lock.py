# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Ключалката на пистата и шината (SPEC Р38, TECH_DESIGN §9.3 M20, С2–С5).

Докато някой влачи, пистата е заключена за другите с изтичане 60 s от
последния сигнал; позицията и промените вървят по шината в защитен канал
по фирма, който само сървърът добавя."""
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL

LOCK_SECONDS_PARAM = "mrp_workcenter_crew_roster.lane_lock_seconds"
# Низът, който Гантът праща в addChannel; сървърът го превежда в
# (фирма, CREW_LANE_CHANNEL) за всяка фирма на потребителя (С3).
CREW_LANE_CHANNEL = "mrp_crew_lane"


class MrpWorkcenterLaneLock(models.Model):
    _name = "mrp.workcenter.lane.lock"
    _description = "Work Center Lane Lock"
    _order = "workcenter_id, lane"

    workcenter_id = fields.Many2one(
        "mrp.workcenter",
        string="Work Center",
        required=True,
        index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        related="workcenter_id.company_id", store=True, index=True
    )
    lane = fields.Integer(required=True)
    user_id = fields.Many2one(
        "res.users", string="User", required=True, ondelete="cascade"
    )
    workorder_id = fields.Many2one(
        "mrp.workorder", string="Work Order", ondelete="set null"
    )
    tab = fields.Char()
    expires_at = fields.Datetime(string="Expires At", required=True)

    _sql_constraints = [
        (
            "unique_lane",
            "unique(workcenter_id, lane)",
            "A lane of a work center can be locked only once.",
        ),
    ]

    # ------------------------------------------------------------------
    # Помощни
    # ------------------------------------------------------------------

    @api.model
    def _crew_lock_seconds(self):
        value = self.env["ir.config_parameter"].sudo().get_param(LOCK_SECONDS_PARAM, "60")
        try:
            return max(int(float(value)), 1)
        except (TypeError, ValueError):
            return 60

    @api.model
    def _crew_lane_rows(self, workcenter, lane, active_only=True):
        domain = [("workcenter_id", "=", workcenter.id), ("lane", "=", lane)]
        if active_only:
            domain.append(("expires_at", ">=", fields.Datetime.now()))
        return self.sudo().search(domain)

    @api.model
    def _crew_lane_locked(self, workcenter, lane):
        """Влакът пропуска пистата, ако някой я държи (M18)."""
        return bool(self._crew_lane_rows(workcenter, lane))

    @api.model
    def _crew_lane_locked_message(self, workcenter, lane, holder=None):
        name = (holder or {}).get("user")
        if not name:
            name = self._crew_lane_rows(workcenter, lane)[:1].user_id.name or ""
        return self.env._(
            "Lane %(lane)s of %(wc)s is being moved by %(user)s. Try again in a minute.",
            lane=lane,
            wc=workcenter.display_name,
            user=name,
        )

    @api.model
    def _crew_lane_check_lock(self, workcenter, lane):
        """M20.3: чужд ред с `expires_at` ≥ сега → отказ (M16, M17)."""
        if not workcenter:
            return
        rows = self._crew_lane_rows(workcenter, lane).filtered(
            lambda row: row.user_id != self.env.user
        )
        if rows:
            raise UserError(
                self._crew_lane_locked_message(
                    workcenter, lane, {"user": rows[:1].user_id.name}
                )
            )

    @api.model
    def _crew_lane_take(self, workcenter, lane, workorder=None, tab=None):
        """Атомичното хващане (С2): INSERT … ON CONFLICT DO UPDATE само ако
        чуждата ключалка е изтекла или ключалката е своя."""
        now = fields.Datetime.now()
        expires = now + timedelta(seconds=self._crew_lock_seconds())
        self.flush_model()
        self.env.cr.execute(
            SQL(
                """
                INSERT INTO mrp_workcenter_lane_lock AS l
                       (workcenter_id, company_id, lane, user_id, workorder_id,
                        tab, expires_at, create_uid, create_date, write_uid,
                        write_date)
                VALUES (%(wc)s, %(company)s, %(lane)s, %(uid)s, %(wo)s,
                        %(tab)s, %(expires)s, %(uid)s, %(now)s, %(uid)s, %(now)s)
                ON CONFLICT (workcenter_id, lane) DO UPDATE
                   SET user_id = EXCLUDED.user_id,
                       workorder_id = EXCLUDED.workorder_id,
                       tab = EXCLUDED.tab,
                       expires_at = EXCLUDED.expires_at,
                       write_uid = EXCLUDED.write_uid,
                       write_date = EXCLUDED.write_date
                 WHERE l.expires_at < %(now)s OR l.user_id = EXCLUDED.user_id
                RETURNING l.id
                """,
                wc=workcenter.id,
                company=workcenter.company_id.id or None,
                lane=lane,
                uid=self.env.uid,
                wo=workorder.id if workorder else None,
                tab=tab or None,
                expires=expires,
                now=now,
            )
        )
        row = self.env.cr.fetchone()
        self.invalidate_model()
        if row:
            return {"ok": True, "expires_at": fields.Datetime.to_string(expires)}
        holder = self._crew_lane_rows(workcenter, lane, active_only=False)[:1]
        return {
            "ok": False,
            "user": holder.user_id.name,
            "user_id": holder.user_id.id,
            "expires_at": fields.Datetime.to_string(holder.expires_at),
        }

    @api.model
    def _crew_lane_release_own(self, pairs, workorder=None):
        """Освобождава своите ключалки на двойките (център, писта) и — с
        `workorder` — всички свои ключалки на влаченето на тази поръчка:
        пистите, над които вагонът е минал, не остават заключени до
        изтичането (Р38, находка 2 на проверката от 07.10)."""
        rows = self.sudo().browse()
        for workcenter, lane in pairs:
            if workcenter:
                rows |= self._crew_lane_rows(workcenter, lane, active_only=False).filtered(
                    lambda row: row.user_id == self.env.user
                )
        if workorder:
            rows |= self.sudo().search(
                [("user_id", "=", self.env.uid), ("workorder_id", "in", workorder.ids)]
            )
        self._crew_lane_unlink(rows)

    @api.model
    def _crew_lane_release_passed(self, keep, workorder=None, tab=None):
        """Ping: своите ключалки на същото влачене (поръчката, иначе
        раздела) извън `keep` — източника и текущата цел — се пускат.
        Без поръчка и раздел не се пипа нищо (не се знае кое е влачене)."""
        if not workorder and not tab:
            return
        domain = [("user_id", "=", self.env.uid)]
        if workorder:
            domain.append(("workorder_id", "=", workorder.id))
        if tab:
            domain.append(("tab", "=", tab))
        keep = {(workcenter.id, lane) for workcenter, lane in keep}
        rows = self.sudo().search(domain).filtered(
            lambda row: (row.workcenter_id.id, row.lane) not in keep
        )
        self._crew_lane_unlink(rows)

    @api.model
    def _crew_lane_held(self, workcenter, lane):
        """Държи ли текущият потребител активна ключалка на пистата."""
        return bool(
            self._crew_lane_rows(workcenter, lane).filtered(
                lambda row: row.user_id == self.env.user
            )
        )

    def _crew_lane_unlink(self, rows):
        for row in rows:
            self._crew_lane_notify(
                row.workcenter_id,
                "released",
                {
                    "workcenter_id": row.workcenter_id.id,
                    "lane": row.lane,
                    "user_id": row.user_id.id,
                    "user_name": row.user_id.name,
                    "tab": row.tab or False,
                },
            )
        rows.unlink()

    @api.model
    def _crew_active_locks(self, workcenters):
        """Активните ключалки за `get_gantt_data` (M21)."""
        rows = self.sudo().search(
            [
                ("workcenter_id", "in", workcenters.ids),
                ("expires_at", ">=", fields.Datetime.now()),
            ]
        )
        return [
            {
                "workcenter_id": row.workcenter_id.id,
                "lane": row.lane,
                "user_id": row.user_id.id,
                "user_name": row.user_id.name,
                "workorder_id": row.workorder_id.id,
                "tab": row.tab or False,
                "expires_at": fields.Datetime.to_string(row.expires_at),
            }
            for row in rows
        ]

    @api.model
    def _crew_lane_notify(self, workcenters, kind, payload):
        """Съобщение по шината в канала (фирма, "mrp_crew_lane"); тръгва
        при commit (К13)."""
        companies = workcenters.company_id or self.env.company
        for company in companies:
            self.env["bus.bus"]._sendone(
                (company, CREW_LANE_CHANNEL), "mrp_crew_lane/%s" % kind, payload
            )

    def _crew_check_workorder(self, workorder_id, workcenter_id):
        """Правото: запис върху поръчката (иначе AccessError), четене на центъра."""
        workcenter = self.env["mrp.workcenter"].browse(workcenter_id).exists()
        if not workcenter:
            raise UserError(self.env._("Select a work center."))
        workcenter.check_access("read")
        workorder = self.env["mrp.workorder"].browse(workorder_id).exists()
        if workorder:
            workorder.check_access("write")
        return workcenter, workorder

    # ------------------------------------------------------------------
    # M20 — по RPC от Ганта
    # ------------------------------------------------------------------

    @api.model
    def crew_lane_acquire(self, workcenter_id, lane, workorder_id=False, tab=False):
        """M20.1: хваща пистата; при чужда активна ключалка връща името и
        изтичането ѝ."""
        workcenter, workorder = self._crew_check_workorder(workorder_id, workcenter_id)
        result = self._crew_lane_take(workcenter, int(lane), workorder, tab)
        if result["ok"]:
            self._crew_lane_notify(
                workcenter,
                "locked",
                {
                    "workcenter_id": workcenter.id,
                    "lane": int(lane),
                    "workorder_id": workorder.id,
                    "user_id": self.env.uid,
                    "user_name": self.env.user.name,
                    "tab": tab or False,
                    "expires_at": result["expires_at"],
                },
            )
        return result

    @api.model
    def crew_lane_ping(
        self,
        workcenter_id,
        lane,
        workorder_id=False,
        target_workcenter_id=False,
        target_lane=False,
        after_workorder_id=False,
        date_start=False,
        date_finished=False,
        tab=False,
    ):
        """M20.2: подновява САМО своите ключалки, опитва да хване целта,
        пуска своите ключалки на това влачене извън източника и целта
        (пистите, над които вагонът е минал) и праща позицията на влачения
        вагон (`mrp_crew_lane/drag`). Съобщението казва какво влачещият
        наистина държи (`source_locked`, `target_locked`) и носи СВОЕТО
        изтичане: отказаната цел не се показва като негова (Р38, находки
        2 и 3 на проверката от 07.10)."""
        workcenter, workorder = self._crew_check_workorder(workorder_id, workcenter_id)
        now = fields.Datetime.now()
        expires = now + timedelta(seconds=self._crew_lock_seconds())
        self.flush_model()
        self.env.cr.execute(
            SQL(
                "UPDATE mrp_workcenter_lane_lock SET expires_at = %s, write_date = %s "
                "WHERE user_id = %s",
                expires,
                now,
                self.env.uid,
            )
        )
        self.invalidate_model()
        target = self.env["mrp.workcenter"].browse(target_workcenter_id or workcenter.id)
        target_lane = int(target_lane or lane)
        result = self._crew_lane_take(target, target_lane, workorder, tab)
        self._crew_lane_release_passed(
            [(workcenter, int(lane)), (target, target_lane)], workorder, tab
        )
        source_locked = self._crew_lane_held(workcenter, int(lane))
        self._crew_lane_notify(
            workcenter | target,
            "drag",
            {
                "workorder_id": workorder.id,
                "user_id": self.env.uid,
                "user_name": self.env.user.name,
                "tab": tab or False,
                "source": [workcenter.id, int(lane)],
                "target": [target.id, target_lane],
                "after_id": after_workorder_id or False,
                "date_start": date_start or False,
                "date_finished": date_finished or False,
                "source_locked": source_locked,
                "target_locked": bool(result["ok"]),
                "expires_at": fields.Datetime.to_string(expires),
            },
        )
        return result

    @api.model
    def crew_lane_release(self, workcenter_id=None, lane=None, tab=None):
        """M20.4: трие своите ключалки (по желание — само на центъра,
        пистата, раздела) и праща `mrp_crew_lane/released`."""
        domain = [("user_id", "=", self.env.uid)]
        if workcenter_id:
            domain.append(("workcenter_id", "=", workcenter_id))
        if lane:
            domain.append(("lane", "=", int(lane)))
        if tab:
            domain.append(("tab", "=", tab))
        rows = self.sudo().search(domain)
        count = len(rows)
        self._crew_lane_unlink(rows)
        return count

    @api.autovacuum
    def _gc_expired_locks(self):
        """Изтеклите ключалки се чистят от autovacuum."""
        self.sudo().search([("expires_at", "<", fields.Datetime.now())]).unlink()


class IrWebsocket(models.AbstractModel):
    _inherit = "ir.websocket"

    def _crew_lane_channels(self):
        """Защитеният канал (С3): кортежът (фирма, "mrp_crew_lane") за всяка
        фирма на потребителя — само за `mrp.group_mrp_user`."""
        user = self.env.user
        if not self.env.uid or user._is_public() or not user.has_group("mrp.group_mrp_user"):
            return []
        return [(company, CREW_LANE_CHANNEL) for company in user.company_ids]

    def _build_bus_channel_list(self, channels):
        """Клиентът праща само низове (К13); низът "mrp_crew_lane" се
        превежда в защитените канали по фирма, а самият низ отпада."""
        def is_ours(channel):
            return isinstance(channel, str) and channel == CREW_LANE_CHANNEL

        if any(is_ours(channel) for channel in channels):
            channels = [channel for channel in channels if not is_ours(channel)]
            channels.extend(self._crew_lane_channels())
        return super()._build_bus_channel_list(channels)
