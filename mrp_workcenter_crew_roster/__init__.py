from . import models
from . import wizard


def post_init_hook(env):
    """При инсталация полетата на наряда се попълват само за незавършените
    работни поръчки (колоните са създадени празни в _auto_init)."""
    env["mrp.workorder"]._crew_init_open_workorders()
