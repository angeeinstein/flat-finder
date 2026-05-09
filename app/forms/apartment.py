"""Apartment-related forms."""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    FloatField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, URL


class ImportURLForm(FlaskForm):
    urls = TextAreaField(
        "Listing URLs (one per line)",
        validators=[DataRequired(), Length(min=10, max=20000)],
        render_kw={"rows": 6, "placeholder": "https://www.willhaben.at/iad/immobilien/..."},
    )
    submit = SubmitField("Start import")


class ApartmentSearchForm(FlaskForm):
    class Meta:
        csrf = False

    q = StringField("Search", validators=[Optional(), Length(max=200)])
    min_price = DecimalField("Min price", validators=[Optional(), NumberRange(min=0)])
    max_price = DecimalField("Max price", validators=[Optional(), NumberRange(min=0)])
    min_area = FloatField("Min area (m²)", validators=[Optional(), NumberRange(min=0)])
    max_area = FloatField("Max area (m²)", validators=[Optional(), NumberRange(min=0)])
    min_rooms = FloatField("Min rooms", validators=[Optional(), NumberRange(min=0)])
    city = StringField("City", validators=[Optional(), Length(max=120)])
    has_balcony = BooleanField("Balcony")
    has_parking = BooleanField("Parking")
    online_only = BooleanField("Online only")
    sort = SelectField(
        "Sort by",
        choices=[
            ("newest", "Newest"),
            ("price_asc", "Price ↑"),
            ("price_desc", "Price ↓"),
            ("area_desc", "Area ↓"),
            ("rooms_desc", "Rooms ↓"),
        ],
        default="newest",
    )
    submit = SubmitField("Apply")


class ApartmentForm(FlaskForm):
    title = StringField("Title", validators=[Optional(), Length(max=500)])
    description = TextAreaField("Description", validators=[Optional()])

    price = DecimalField("Rent (€/month)", validators=[Optional(), NumberRange(min=0)], places=2)
    operating_costs = DecimalField("Operating costs (€/month)", validators=[Optional(), NumberRange(min=0)], places=2)
    total_monthly_cost = DecimalField("Total monthly cost (€)", validators=[Optional(), NumberRange(min=0)], places=2)
    deposit = DecimalField("Deposit (€)", validators=[Optional(), NumberRange(min=0)], places=2)
    commission = DecimalField("Commission (€)", validators=[Optional(), NumberRange(min=0)], places=2)

    address = StringField("Address", validators=[Optional(), Length(max=500)])
    city = StringField("City", validators=[Optional(), Length(max=120)])
    postal_code = StringField("Postal code", validators=[Optional(), Length(max=32)])
    country = StringField("Country", validators=[Optional(), Length(max=120)])
    address_is_approximate = BooleanField("Address is approximate")
    lat = FloatField("Latitude", validators=[Optional(), NumberRange(min=-90, max=90)])
    lng = FloatField("Longitude", validators=[Optional(), NumberRange(min=-180, max=180)])

    living_area_m2 = FloatField("Living area (m²)", validators=[Optional(), NumberRange(min=0)])
    rooms = FloatField("Rooms", validators=[Optional(), NumberRange(min=0)])
    floor = StringField("Floor", validators=[Optional(), Length(max=64)])
    building_type = StringField("Building type", validators=[Optional(), Length(max=120)])
    heating_type = StringField("Heating type", validators=[Optional(), Length(max=120)])
    energy_cert_info = StringField("Energy certificate", validators=[Optional(), Length(max=255)])

    has_balcony = BooleanField("Balcony")
    has_terrace = BooleanField("Terrace")
    has_garden = BooleanField("Garden")
    has_parking = BooleanField("Parking / Garage")
    has_cellar = BooleanField("Cellar / Storage")
    is_furnished = BooleanField("Furnished")

    available_from = DateField("Available from", validators=[Optional()])
    lease_duration_limited = BooleanField("Limited lease duration")
    lease_duration_text = StringField("Lease duration notes", validators=[Optional(), Length(max=255)])

    contact_name = StringField("Contact name", validators=[Optional(), Length(max=255)])
    contact_info = StringField("Contact info", validators=[Optional(), Length(max=500)])

    is_offline = BooleanField("Listing is offline")

    source_url = StringField("Source URL", validators=[Optional(), URL(), Length(max=2000)])
    source_platform = StringField("Source platform", validators=[Optional(), Length(max=64)])

    submit = SubmitField("Save")
