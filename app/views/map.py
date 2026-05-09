"""Map blueprint."""
from flask import Blueprint, render_template
from flask_login import login_required

from app.models.location import TargetAddress


bp = Blueprint("map", __name__, template_folder="../templates")


@bp.route("/")
@login_required
def map_view():
    targets = TargetAddress.query.filter_by(is_active=True).order_by(TargetAddress.name).all()
    return render_template("map/map.html", targets=targets)
