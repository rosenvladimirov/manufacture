# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from odoo.tests import HttpCase, tagged

# Сюитата на модула в Hoot (static/tests/crew_gantt.test.js).
HOOT_SUITE = "@mrp_workcenter_crew_roster"


def hoot_hash(name):
    """Идентификаторът на сюита/тест в Hoot (като `HOOTCommon` в web)."""
    value = 0
    for char in name:
        value = ((value << 5) - value + ord(char)) & 0xFFFFFFFF
    return "%08x" % value


@tagged("post_install", "-at_install", "-standard", "crew_roster_js")
class TestCrewGanttJs(HttpCase):
    """Hoot тестовете на Ганта „Планирай център“ (модел и контролер).

    Не са в стандартния пуск (`-standard`): нужен е браузър. Пускат се
    изрично с `--test-tags crew_roster_js`.
    """

    def test_crew_gantt_hoot(self):
        self.browser_js(
            "/web/tests?headless&loglevel=2&preset=desktop&timeout=15000&id=%s"
            % hoot_hash(HOOT_SUITE),
            "",
            "",
            login="admin",
            timeout=1800,
            success_signal="[HOOT] Test suite succeeded",
            error_checker=lambda message: "[HOOT]" not in message,
        )
