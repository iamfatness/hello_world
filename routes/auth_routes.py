"""Authentication routes for OAuth2/OIDC SSO login flow.

Provides:
- /auth/login     - Redirects to the identity provider
- /auth/callback  - Handles the OAuth2 redirect back from the provider
- /auth/logout    - Clears the session and optionally redirects to IdP logout
"""

import logging

from flask import (
    Blueprint, redirect, url_for, session, flash, current_app, request,
    render_template,
)

from auth import get_oauth_client, check_user_authorized

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login")
def login():
    """Initiate the OAuth2/OIDC login flow.

    If SSO is disabled, redirects straight to the admin dashboard.
    Otherwise, redirects the user to the identity provider's authorization page.
    """
    if not current_app.config.get("SSO_ENABLED"):
        return redirect(url_for("admin.dashboard"))

    client = get_oauth_client()
    redirect_uri = url_for("auth.callback", _external=True)
    return client.authorize_redirect(redirect_uri)


@auth_bp.route("/callback")
def callback():
    """Handle the OAuth2/OIDC callback from the identity provider.

    Exchanges the authorization code for tokens, retrieves user info,
    checks authorization, and creates the session.
    """
    if not current_app.config.get("SSO_ENABLED"):
        return redirect(url_for("admin.dashboard"))

    client = get_oauth_client()

    try:
        token = client.authorize_access_token()
    except Exception as e:
        logger.error("OAuth token exchange failed: %s", e)
        flash("Authentication failed. Please try again.", "danger")
        return redirect(url_for("auth.login_page"))

    # Get user info - try from ID token first, then userinfo endpoint
    user_info = token.get("userinfo")
    if not user_info:
        try:
            user_info = client.userinfo()
        except Exception as e:
            logger.error("Failed to fetch user info: %s", e)
            flash("Could not retrieve user information.", "danger")
            return redirect(url_for("auth.login_page"))

    if not user_info:
        flash("No user information received from provider.", "danger")
        return redirect(url_for("auth.login_page"))

    # Check authorization
    allowed, reason = check_user_authorized(user_info)
    if not allowed:
        logger.warning("User %s denied access: %s", user_info.get("email"), reason)
        flash(f"Access denied: {reason}", "danger")
        return redirect(url_for("auth.login_page"))

    # Store user in session
    session["user"] = {
        "email": user_info.get("email", ""),
        "name": user_info.get("name", user_info.get("email", "Unknown")),
        "picture": user_info.get("picture", ""),
        "sub": user_info.get("sub", ""),
    }
    session.permanent = True

    logger.info("User logged in: %s", session["user"]["email"])

    # Redirect to the page they originally tried to access, or dashboard
    next_url = session.pop("next_url", None)
    return redirect(next_url or url_for("admin.dashboard"))


@auth_bp.route("/logout")
def logout():
    """Log the user out by clearing their session."""
    user = session.pop("user", None)
    if user:
        logger.info("User logged out: %s", user.get("email"))
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login_page"))


@auth_bp.route("/login-page")
def login_page():
    """Render the login page with SSO button."""
    if not current_app.config.get("SSO_ENABLED"):
        return redirect(url_for("admin.dashboard"))

    if session.get("user"):
        return redirect(url_for("admin.dashboard"))

    provider_name = current_app.config.get("SSO_PROVIDER_NAME", "OAuth")
    return render_template("login.html", provider_name=provider_name)
