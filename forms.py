"""All forms. Flask-WTF adds a CSRF token to each one and checks it on submit.

Every rule here runs on the server. The JavaScript checks in static/js/main.js are
only there to give faster feedback.
"""
from datetime import date, timedelta

from flask import current_app
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileSize, MultipleFileField
from wtforms import BooleanField, DateField, EmailField, PasswordField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, Regexp, ValidationError

from utils.validators import clean_line, clean_text, is_college_email, password_problems

CATEGORIES = [
    "Electronics",
    "Mobile Phones",
    "Wallets & Purses",
    "ID Cards & Documents",
    "Keys",
    "Bags",
    "Books & Stationery",
    "Clothing",
    "Jewellery & Accessories",
    "Water Bottles",
    "Sports Equipment",
    "Other",
]
IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp"]
IMAGE_ONLY = "Only JPG, PNG or WEBP images are allowed."
FIVE_MB = 5 * 1024 * 1024


# --- Reusable validators --------------------------------------------------------


class CollegeEmail:
    def __call__(self, form, field):
        if not is_college_email(field.data):
            domains = ", ".join("@" + d for d in current_app.config["ALLOWED_EMAIL_DOMAINS"])
            raise ValidationError(f"Use your college email address ({domains}).")


class StrongPassword:
    def __call__(self, form, field):
        problems = password_problems(field.data)
        if problems:
            raise ValidationError("Password must " + ", ".join(problems) + ".")


def not_in_future(form, field):
    # One day of slack for timezone differences between the browser and the server.
    if field.data and field.data > date.today() + timedelta(days=1):
        raise ValidationError("The date can't be in the future.")
    if field.data and field.data < date.today() - timedelta(days=365):
        raise ValidationError("Only items from the last 12 months can be reported.")


def _email_field(label="College email"):
    return EmailField(
        label,
        validators=[DataRequired(), Email(message="Enter a valid email address."), Length(max=120)],
        filters=[clean_line],
    )


# --- Authentication ---------------------------------------------------------------


class RegisterForm(FlaskForm):
    name = StringField(
        "Full name",
        validators=[
            DataRequired(),
            Length(2, 60),
            Regexp(r"^[A-Za-z][A-Za-z .'\-]*$", message="Use letters, spaces, dots, hyphens or apostrophes only."),
        ],
        filters=[clean_line],
    )
    email = _email_field()
    password = PasswordField("Password", validators=[DataRequired(), StrongPassword()])
    confirm = PasswordField(
        "Confirm password", validators=[DataRequired(), EqualTo("password", message="Passwords don't match.")]
    )

    def validate_email(self, field):
        CollegeEmail()(self, field)


class OtpForm(FlaskForm):
    code = StringField(
        "6-digit code",
        validators=[DataRequired(), Regexp(r"^\d{6}$", message="Enter the 6-digit code from the email.")],
        filters=[lambda v: v.replace(" ", "") if isinstance(v, str) else v],
    )


class LoginForm(FlaskForm):
    email = _email_field("Email")
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])
    remember = BooleanField("Keep me logged in for 7 days")


class ForgotPasswordForm(FlaskForm):
    email = _email_field("Email")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New password", validators=[DataRequired(), StrongPassword()])
    confirm = PasswordField(
        "Confirm new password", validators=[DataRequired(), EqualTo("password", message="Passwords don't match.")]
    )


class ChangePasswordForm(ResetPasswordForm):
    current_password = PasswordField("Current password", validators=[DataRequired(), Length(max=128)])


class ProfileForm(FlaskForm):
    name = RegisterForm.name


# --- Items ----------------------------------------------------------------------


class LostItemForm(FlaskForm):
    title = StringField(
        "What did you lose?", validators=[DataRequired(), Length(3, 80)], filters=[clean_line]
    )
    category = SelectField("Category", choices=[("", "Choose a category")] + [(c, c) for c in CATEGORIES],
                           validators=[DataRequired(message="Choose a category.")])
    description = TextAreaField(
        "Description", validators=[DataRequired(), Length(10, 1000)], filters=[clean_text]
    )
    location = StringField(
        "Last seen location", validators=[DataRequired(), Length(2, 80)], filters=[clean_line]
    )
    date = DateField("Date lost", validators=[DataRequired(message="Pick a date."), not_in_future])
    photo = FileField(
        "Photo (optional)",
        validators=[Optional(), FileAllowed(IMAGE_EXTENSIONS, IMAGE_ONLY), FileSize(FIVE_MB, message="Max 5 MB.")],
    )


class FoundItemForm(LostItemForm):
    title = StringField("What did you find?", validators=[DataRequired(), Length(3, 80)], filters=[clean_line])
    location = StringField("Where did you find it?", validators=[DataRequired(), Length(2, 80)], filters=[clean_line])
    date = DateField("Date found", validators=[DataRequired(message="Pick a date."), not_in_future])
    held_at = SelectField(
        "Where is the item now?",
        choices=[
            ("security_desk", "I've handed it to the security desk"),
            ("finder", "I still have it (I'll drop it at the security desk)"),
        ],
        validators=[DataRequired()],
    )
    hidden_details = TextAreaField(
        "Private details (only you and the admin can see these)",
        validators=[DataRequired(), Length(10, 600)],
        filters=[clean_text],
    )
    q1 = StringField("Question 1", validators=[DataRequired(), Length(5, 150)], filters=[clean_line])
    a1 = StringField("Answer 1", validators=[DataRequired(), Length(1, 150)], filters=[clean_line])
    q2 = StringField("Question 2 (optional)", validators=[Optional(), Length(5, 150)], filters=[clean_line])
    a2 = StringField("Answer 2", validators=[Optional(), Length(1, 150)], filters=[clean_line])
    q3 = StringField("Question 3 (optional)", validators=[Optional(), Length(5, 150)], filters=[clean_line])
    a3 = StringField("Answer 3", validators=[Optional(), Length(1, 150)], filters=[clean_line])

    def question_pairs(self):
        return [(self.q1, self.a1), (self.q2, self.a2), (self.q3, self.a3)]

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        for question, answer in self.question_pairs():
            if bool(question.data) != bool(answer.data):
                (answer if question.data else question).errors.append(
                    "Fill in both the question and its answer, or leave both empty."
                )
                ok = False
        return ok

    def verification_questions(self):
        return [{"question": q.data, "answer": a.data} for q, a in self.question_pairs() if q.data and a.data]


# --- Claims ------------------------------------------------------------------------


class ClaimFormBase(FlaskForm):
    details = TextAreaField(
        "Describe the item in your own words",
        validators=[DataRequired(), Length(10, 600)],
        filters=[clean_text],
    )
    proofs = MultipleFileField(
        "Proof of ownership (up to 3 images)",
        validators=[FileAllowed(IMAGE_EXTENSIONS, IMAGE_ONLY), FileSize(FIVE_MB, message="Each image must be 5 MB or smaller.")],
    )
    confirm = BooleanField(
        "I confirm this item is mine. I understand that false claims lower my trust score and can block me from claiming.",
        validators=[DataRequired(message="Please confirm before submitting.")],
    )


def build_claim_form(questions, **kwargs):
    """One answer box per verification question the finder wrote."""
    fields = {
        f"answer_{i}": TextAreaField(
            q["question"], validators=[DataRequired(message="Please answer this question."), Length(1, 300)],
            filters=[clean_line],
        )
        for i, q in enumerate(questions)
    }
    form = type("ClaimForm", (ClaimFormBase,), fields)(**kwargs)
    form.answer_fields = [form[f"answer_{i}"] for i in range(len(questions))]
    return form


class ReviewForm(FlaskForm):
    note = TextAreaField("Note to the claimant (optional)", validators=[Optional(), Length(max=300)], filters=[clean_text])


class HandoverForm(FlaskForm):
    code = OtpForm.code
    id_checked = BooleanField(
        "I checked the claimant's college ID card and it matches the account name.",
        validators=[DataRequired(message="Check the college ID card before handing over the item.")],
    )


class RemoveItemForm(FlaskForm):
    reason = StringField("Reason", validators=[DataRequired(), Length(3, 200)], filters=[clean_line])
