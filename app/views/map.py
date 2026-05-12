"""Map blueprint."""
from flask import Blueprint, g, render_template
from flask_login import login_required


bp = Blueprint("map", __name__, template_folder="../templates")

_VALID_MODES = {"car", "walking", "bicycle", "transit"}


@bp.route("/")
@login_required
def map_view():
    from app.models.settings import AppSetting
    targets = g.ctx.target_query().order_by("name").all()
    default_mode = AppSetting.get("default_transport_mode") or "car"
    if default_mode not in _VALID_MODES:
        default_mode = "car"
    return render_template("map/map.html", targets=targets, default_mode=default_mode)
