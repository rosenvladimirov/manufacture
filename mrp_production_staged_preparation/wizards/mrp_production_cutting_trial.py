# -*- coding: utf-8 -*-
# №116 (Любо, 01.10): пробният разкрой при отказ — само за гледане. Записът е
# преходен; самият разкрой е откатен, преди прозорецът да се отвори.
from odoo import fields, models


class MrpProductionCuttingTrial(models.TransientModel):
    _name = "mrp.production.cutting.trial"
    _description = "Trial cutting run (nothing saved)"

    production_ids = fields.Many2many(
        comodel_name="mrp.production", string="Manufacturing Orders",
        readonly=True)
    problems_text = fields.Text(string="Why It Was Refused", readonly=True)
    report_html = fields.Html(
        string="Trial Cutting", readonly=True, sanitize=False)
