"""Note and tag forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, Regexp


class NoteForm(FlaskForm):
    content = TextAreaField("Note", validators=[DataRequired(), Length(max=10000)])
    submit = SubmitField("Save note")


class TagForm(FlaskForm):
    name = StringField("Tag name", validators=[
        DataRequired(),
        Length(min=2, max=64),
        Regexp(r"^[A-Za-z0-9 _\-]+$", message="Letters, numbers, spaces, _- only."),
    ])
    color = StringField("Color (hex)", validators=[Optional(), Regexp(r"^#?[0-9A-Fa-f]{6}$")])
    submit = SubmitField("Add tag")
