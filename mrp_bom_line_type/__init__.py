# -*- coding: utf-8 -*-
from . import models


def post_load():
    """Post load hook to patch the explode method on MrpBom."""
    from .models.mrp_bom import explode_with_line_type
    from odoo.addons.mrp.models.mrp_bom import MrpBom
    
    MrpBom._original_explode = MrpBom.explode
    MrpBom.explode = explode_with_line_type
