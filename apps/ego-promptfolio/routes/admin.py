"""Маршруты админ-панели."""

import logging

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db
from forms.login_form import LoginForm
from models.contact import ContactSubmission
from models.user import User

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    """Вход администратора."""
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            logger.info("Admin login: user_id=%s", user.id)
            flash("Вы успешно вошли.", "success")
            next_page = url_for("admin.dashboard")
            return redirect(next_page)
        flash("Неверный логин или пароль.", "danger")

    return render_template("admin/login.html", form=form)


@admin_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """Выход из админ-панели."""
    logger.info("Admin logout: user_id=%s", current_user.id)
    logout_user()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
@login_required
def dashboard():
    """Таблица всех обращений."""
    submissions = (
        ContactSubmission.query.order_by(ContactSubmission.created_at.desc()).all()
    )
    return render_template("admin/dashboard.html", submissions=submissions)


@admin_bp.route("/submissions/<int:submission_id>/read", methods=["POST"])
@login_required
def mark_read(submission_id):
    """Отметить заявку как прочитанную."""
    submission = db.session.get(ContactSubmission, submission_id)
    if submission is None:
        flash("Заявка не найдена.", "warning")
        return redirect(url_for("admin.dashboard"))
    submission.is_read = True
    db.session.commit()
    logger.info("Submission marked read id=%s", submission_id)
    flash("Заявка отмечена как прочитанная.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/submissions/<int:submission_id>/delete", methods=["POST"])
@login_required
def delete_submission(submission_id):
    """Удалить заявку."""
    submission = db.session.get(ContactSubmission, submission_id)
    if submission is None:
        flash("Заявка не найдена.", "warning")
        return redirect(url_for("admin.dashboard"))
    db.session.delete(submission)
    db.session.commit()
    logger.info("Submission deleted id=%s", submission_id)
    flash("Заявка удалена.", "success")
    return redirect(url_for("admin.dashboard"))
