"""OAuth2/OIDC Single Sign-On authentication for the admin portal.

Supports any standards-compliant OAuth2/OIDC identity provider including:
- Microsoft Entra ID (Azure AD)
- Okta
- Google Workspace
- Keycloak
- Auth0
- Any OIDC-compliant provider

Configuration can be done via:
1. OIDC Discovery URL (recommended) - auto-configures all endpoints
2. Manual endpoint specification - for providers without discovery

When SSO is disabled (SSO_ENABLED=false), the admin portal is open with no
authentication. When enabled, all /admin/* routes require a valid SSO session.
"""

import functools
import logging

from flask import session, redirect, url_for, request, current_app
from authlib.integrations.flask_client import OAuth

logger = logging.getLogger(__name__)

oauth = OAuth()


def init_sso(app):
    """Initialize the OAuth2/OIDC client with the Flask application.

    Reads SSO configuration from app config (which loads from env vars
    and/or database-persisted settings) and registers the OAuth provider.

    Args:
        app: The Flask application instance.
    """
    oauth.init_app(app)

    cfg = app.config

    if not cfg.get("SSO_ENABLED"):
        logger.info("SSO is disabled - admin portal is unauthenticated")
        return

    client_kwargs = {
        "scope": cfg.get("SSO_SCOPES", "openid email profile"),
    }

    provider_config = {
        "client_id": cfg["SSO_CLIENT_ID"],
        "client_secret": cfg["SSO_CLIENT_SECRET"],
        "client_kwargs": client_kwargs,
    }

    # Prefer OIDC Discovery for auto-configuration
    discovery_url = cfg.get("SSO_DISCOVERY_URL", "")
    if discovery_url:
        provider_config["server_metadata_url"] = discovery_url
    else:
        # Manual endpoint configuration
        provider_config["authorize_url"] = cfg.get("SSO_AUTHORIZATION_ENDPOINT", "")
        provider_config["access_token_url"] = cfg.get("SSO_TOKEN_ENDPOINT", "")
        provider_config["userinfo_endpoint"] = cfg.get("SSO_USERINFO_ENDPOINT", "")

    provider_name = cfg.get("SSO_PROVIDER_NAME", "oauth")
    oauth.register(provider_name, **provider_config)
    app.config["SSO_PROVIDER_NAME"] = provider_name

    logger.info(
        "SSO enabled with provider '%s' (discovery=%s)",
        provider_name,
        bool(discovery_url),
    )


def get_oauth_client():
    """Get the registered OAuth client for the configured provider."""
    provider_name = current_app.config.get("SSO_PROVIDER_NAME", "oauth")
    return getattr(oauth, provider_name)


def login_required(f):
    """Decorator to protect admin routes with SSO authentication.

    When SSO is disabled, all requests pass through. When enabled,
    unauthenticated requests are redirected to the login page.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not current_app.config.get("SSO_ENABLED"):
            return f(*args, **kwargs)

        user = session.get("user")
        if not user:
            session["next_url"] = request.url
            return redirect(url_for("auth.login"))

        return f(*args, **kwargs)
    return decorated


def check_user_authorized(user_info):
    """Verify that an authenticated user is allowed to access the admin portal.

    Checks against configured domain allowlist, email allowlist, and
    optional role claims.

    Args:
        user_info: Dict of user claims from the OIDC provider.

    Returns:
        (allowed: bool, reason: str)
    """
    email = user_info.get("email", "")

    # Check allowed emails
    allowed_emails = current_app.config.get("SSO_ALLOWED_EMAILS", "")
    if allowed_emails:
        email_list = [e.strip().lower() for e in allowed_emails.split(",") if e.strip()]
        if email_list and email.lower() not in email_list:
            return False, f"Email {email} is not in the allowed list"

    # Check allowed domains
    allowed_domains = current_app.config.get("SSO_ALLOWED_DOMAINS", "")
    if allowed_domains:
        domain_list = [d.strip().lower() for d in allowed_domains.split(",") if d.strip()]
        if domain_list:
            user_domain = email.split("@")[-1].lower() if "@" in email else ""
            if user_domain not in domain_list:
                return False, f"Domain {user_domain} is not allowed"

    # Check role claim if configured
    role_claim = current_app.config.get("SSO_ADMIN_ROLE_CLAIM", "")
    if role_claim:
        user_roles = user_info.get(role_claim, [])
        if isinstance(user_roles, str):
            user_roles = [user_roles]
        if "admin" not in [r.lower() for r in user_roles]:
            return False, "User does not have the admin role"

    return True, ""
