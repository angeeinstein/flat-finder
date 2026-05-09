"""Custom decorators."""
from functools import wraps

from flask import abort
from flask_login import current_user


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.is_admin or not current_user.is_active:
            abort(403)
        return view(*args, **kwargs)

    return wrapper
