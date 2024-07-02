# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import copy
import functools
from datetime import datetime

from dateutil import relativedelta

from odoo import api, fields, models, _, tools
from werkzeug import urls

import logging

_logger = logging.getLogger(__name__)

try:
    # We use a jinja2 sandboxed environment to render mako templates.
    # Note that the rendering does not cover all the mako syntax, in particular
    # arbitrary Python statements are not accepted, and not all expressions are
    # allowed: only "public" attributes (not starting with '_') of objects may
    # be accessed.
    # This is done on purpose: it prevents incidental or malicious execution of
    # Python code that may break the security of the server.
    from jinja2.sandbox import SandboxedEnvironment

    mako_template_env = SandboxedEnvironment(
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="${",
        variable_end_string="}",
        comment_start_string="<%doc>",
        comment_end_string="</%doc>",
        line_statement_prefix="%",
        line_comment_prefix="##",
        trim_blocks=True,  # do not output newline after blocks
        autoescape=True,  # XML/HTML automatic escaping
    )
    mako_template_env.globals.update({
        'str': str,
        'quote': urls.url_quote,
        'urlencode': urls.url_encode,
        'datetime': datetime,
        'len': len,
        'abs': abs,
        'min': min,
        'max': max,
        'sum': sum,
        'filter': filter,
        'reduce': functools.reduce,
        'map': map,
        'round': round,
        # dateutil.relativedelta is an old-style class and cannot be directly
        # instanciated wihtin a jinja2 expression, so a lambda "proxy"
        # is needed, apparently.
        'relativedelta': lambda *a, **kw: relativedelta.relativedelta(*a, **kw),
    })
    mako_safe_template_env = copy.copy(mako_template_env)
    mako_safe_template_env.autoescape = False
except ImportError:
    _logger.warning("jinja2 not available, templating features will not work!")


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    def _post_record_production(self):
        if self.final_lot_id and self.product_id and self.product_id.ref_lot:
            render_result = self.product_id.ref_lot
            locals_dict = {
                'save': True,
                'object': self,
            }
            for line in self.active_move_line_ids:
                locals_dict.update({
                    'components': line,
                })
                msg = render_result
                try:
                    mako_env = mako_safe_template_env if locals_dict.get('safe') else mako_template_env
                    template = mako_env.from_string(tools.ustr(msg))
                except Exception:
                    _logger.info("Failed to load template %r", msg, exc_info=True)
                    break

                try:
                    render_result = template.render(locals_dict)
                except Exception:
                    _logger.info("Failed to render template %r using values %r" % (template, locals_dict), exc_info=True)
                    continue

                if render_result == u"False":
                    render_result = self.product_id.ref_lot
                    continue

            if render_result:
                self.final_lot_id.ref = render_result
        return super()._post_record_production()
