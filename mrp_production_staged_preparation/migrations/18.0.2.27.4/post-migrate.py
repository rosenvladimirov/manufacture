# -*- coding: utf-8 -*-
"""2.27.4 — №159: заварените МО, „върнати“ с Unplan, но останали в подготовка.

До 2.27.4 Unplan не сваляше preparation → confirmed. Връщат се МО-тата, които
са в preparation, НЕ са пуснати (staged_released) и вече НЕ са планирани
(is_planned) — точно състоянието след стария Unplan (fulltest 13.10: M002090/91/92,
M002122, M002218). Планираните и пуснатите не се пипат.

⚪ Идемпотентна.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    mos = env["mrp.production"].search([
        ("state", "=", "preparation"), ("staged_released", "=", False)])
    stuck = mos.filtered(lambda p: not p.is_planned)
    if stuck:
        stuck.write({"state": "confirmed"})
    _logger.info("№159: %s МО preparation → confirmed (без план, непуснати): %s",
                 len(stuck), ", ".join(stuck.mapped("name")) or "—")
