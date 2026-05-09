"""Rating-related forms."""
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    FloatField,
    IntegerField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class RatingCategoryForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    description = StringField("Description", validators=[Optional(), Length(max=500)])
    weight = FloatField("Weight", validators=[DataRequired(), NumberRange(min=0)], default=1.0)
    min_score = IntegerField("Min score", validators=[DataRequired(), NumberRange(min=0)], default=0)
    max_score = IntegerField("Max score", validators=[DataRequired(), NumberRange(min=1)], default=10)
    display_order = IntegerField("Display order", validators=[DataRequired()], default=0)
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")
