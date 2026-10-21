# -*- coding: utf-8 -*-
# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
"""Прогресът на фоновата подготовка (ADR-0098 / ADR-0100).

Огледало на `logikal.import.progress` (вносът от ЛогиКал): редът живее в
ОТДЕЛНА таблица и се пише САМО със собствен курсор и commit — иначе
главната транзакция на задачата държи МО-тата заключени и прогресът се
вижда чак накрая. Писането по самите МО-та от втори курсор би чакало
същите заключвания (или би гръмнало с „concurrent update“).
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class MrpProductionPrepProgress(models.Model):
    _name = "mrp.production.prep.progress"
    _description = "Background Preparation Progress"
    _rec_name = "job_uuid"

    job_uuid = fields.Char(required=True, index=True)
    progress = fields.Float()
    stage = fields.Char()

    _sql_constraints = [
        ("job_uuid_uniq", "unique(job_uuid)", "One progress row per job."),
    ]

    @api.model
    def _report(self, job_uuid, production_ids, progress, stage):
        """Пише прогреса със свой курсор и опреснява отворените форми."""
        if not job_uuid:
            return
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, self.env.uid, self.env.context)
                Progress = env[self._name].sudo()
                row = Progress.search([("job_uuid", "=", job_uuid)], limit=1)
                vals = {"progress": progress, "stage": stage}
                if row:
                    row.write(vals)
                else:
                    Progress.create(dict(vals, job_uuid=job_uuid))
                # l10n_bg_live_refresh, ако го има — формата се презарежда сама
                # (както при вноса); без него прогресът се вижда при опресняване.
                if "live.refresh" in env:
                    env["live.refresh"].notify(
                        model="mrp.production", res_ids=production_ids,
                        mode="record")
                cr.commit()
        except Exception:  # noqa: BLE001 — прогресът не бива да спира задачата
            _logger.warning("Staged: прогресът на %s не се записа", job_uuid,
                            exc_info=True)
