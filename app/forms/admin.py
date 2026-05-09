"""Admin forms."""
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    FloatField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    NumberRange,
    Optional,
    Regexp,
)


class UserForm(FlaskForm):
    username = StringField("Username", validators=[
        DataRequired(),
        Length(min=3, max=64),
        Regexp(r"^[A-Za-z0-9_.\-]+$", message="Letters, numbers, ._- only."),
    ])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField("Role", choices=[("user", "User"), ("admin", "Admin")], default="user")
    is_active = BooleanField("Active", default=True)
    password = PasswordField("Password (leave blank to keep current)", validators=[Optional(), Length(min=8)])
    confirm = PasswordField("Confirm password", validators=[Optional(), EqualTo("password")])
    submit = SubmitField("Save")


class TargetAddressForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    address = StringField("Address", validators=[DataRequired(), Length(max=500)])
    lat = FloatField("Latitude", validators=[Optional(), NumberRange(min=-90, max=90)])
    lng = FloatField("Longitude", validators=[Optional(), NumberRange(min=-180, max=180)])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")


class AppSettingForm(FlaskForm):
    key = StringField("Key", validators=[DataRequired(), Length(max=120)])
    value = StringField("Value", validators=[Optional(), Length(max=4000)])
    description = StringField("Description", validators=[Optional(), Length(max=500)])
    submit = SubmitField("Save")
