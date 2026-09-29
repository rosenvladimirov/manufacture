# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)


def post_init_hook(env):
    """Локацията „Lot Relabel" за всяка ВЕЧЕ съществуваща фирма.

    Новите фирми я получават от `_create_per_company_locations`. Тук — за да
    може счетоводителят да ѝ зададе сметките веднага след инсталацията, преди
    първото преетикетиране (иначе тя би се родила чак при него, без сметки, и
    то би паднало с грешка).
    """
    for company in env["res.company"].search([]):
        company._get_lot_relabel_location()
