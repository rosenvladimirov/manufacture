# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MrpBomStage(models.Model):
    _name = 'mrp.bom.stage'
    _description = 'Етап на BOM'
    _order = 'sequence, id'

    name = fields.Char(string='Stage name', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    code = fields.Char(string='Code', help='Identification stage code')
    description = fields.Text(string='Description')
    active = fields.Boolean(string='Active', default=True)
    is_common = fields.Boolean(
        string='General stage',
        help='Generic/unidentified stage for materials without a specific stage'
    )

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'The stage code must be unique!'),
    ]

    @api.constrains('is_common')
    def _check_single_common_stage(self):
        """Проверка, че има само един общ етап"""
        if self.is_common:
            common_count = self.search_count([('is_common', '=', True), ('id', '!=', self.id)])
            if common_count > 0:
                raise ValidationError('There can only be one common stage!')
