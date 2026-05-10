"""Map blueprint."""
from flask import Blueprint, g, render_template
from flask_login import login_required


bp = Blueprint("map", __name__, template_folder="../templates")


@bp.route("/")
@login_required
def map_view():
    targets = g.ctx.target_query().order_by("name").all()
    return render_template("map/map.html", targets=targets)
