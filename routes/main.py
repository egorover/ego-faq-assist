"""Публичные маршруты сайта."""

import logging

from flask import Blueprint, abort, flash, redirect, render_template, url_for

from data.cases import get_all_cases, get_case_by_slug
from extensions import db
from forms.contact_form import ContactForm
from models.contact import ContactSubmission

logger = logging.getLogger(__name__)

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Главная страница с hero и превью кейсов."""
    cases = get_all_cases()
    return render_template("main/index.html", cases=cases)


@main_bp.route("/cases")
def cases_list():
    """Список всех кейсов."""
    cases = get_all_cases()
    return render_template("main/cases.html", cases=cases)


@main_bp.route("/cases/<slug>")
def case_detail(slug):
    """Детальная страница кейса."""
    case = get_case_by_slug(slug)
    if case is None:
        abort(404)
    return render_template("main/case_detail.html", case=case)


@main_bp.route("/contact", methods=["GET", "POST"])
def contact():
    """Форма обратной связи."""
    form = ContactForm()
    if form.validate_on_submit():
        submission = ContactSubmission(
            name=form.name.data.strip(),
            email=form.email.data.strip().lower(),
            phone=form.phone.data.strip(),
            subject=form.subject.data.strip(),
        )
        db.session.add(submission)
        db.session.commit()
        logger.info("New contact submission id=%s", submission.id)
        flash("Спасибо! Ваше сообщение отправлено.", "success")
        return redirect(url_for("main.contact"))
    return render_template("main/contact.html", form=form)
