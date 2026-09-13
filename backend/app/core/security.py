"""
API Key authentication + secure HTTP headers injection.

Mutation/ingestion endpoints require X-API-Key header.
Read-only forecast endpoints are public (but rate-limited).
"""
import secrets

from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from app.core.config import get_settings

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# The default in config.py. If the operator never set APP_API_KEY, ingestion must
# be closed rather than accepting a value that is published in .env.example.
_PLACEHOLDER_KEYS = frozenset({"change-me", "your-secret-api-key-here", ""})


def require_api_key(
    api_key: str | None = Security(_API_KEY_HEADER),
) -> str:
    """Dependency: validates X-API-Key for mutation endpoints."""
    expected = get_settings().app_api_key

    if expected in _PLACEHOLDER_KEYS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion is disabled: APP_API_KEY is unset or still the placeholder value.",
        )

    # compare_digest, not ==: a plain string comparison short-circuits on the
    # first differing byte, which leaks the shared secret one character at a time
    # to anyone who can time the response.
    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-API-Key",
        )
    return api_key


# Secure response headers applied globally via middleware in main.py
SECURE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self' data: blob:; "
        "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' 'unsafe-eval' blob:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https://* http://*; "
        "media-src 'self' data: blob: https://*; "
        "connect-src 'self' data: blob: https://* http://*"
    ),
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
}

# Swagger UI and ReDoc are served as thin HTML shells that pull their JS/CSS from
# cdn.jsdelivr.net. Under the strict policy above, script-src 'self' blocked that
# bundle and /docs rendered as a blank page -- while README.md and API.md both
# tell the reader to open it. Rather than weakening the policy for the whole API,
# the middleware swaps in this relaxed variant for the documentation routes only.
DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "media-src 'self' data: blob:; "
    "worker-src 'self' blob:; "
    "connect-src 'self'"
)

DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})

# The built React console (webapp/dist, mounted at /console) loads its own JS and
# CSS same-origin, so script-src 'self' already covers them and Vite emits no
# inline scripts. It does, however, pull the IBM Plex families from Google Fonts,
# which the global style-src/font-src block. As with the docs, we relax the policy
# for the console document only rather than weakening it API-wide. 'unsafe-inline'
# stays for style (React sets element style attributes for widths and the live
# accent colour); scripts remain 'self' with no inline allowance.
#
# The station map's online renderer (Leaflet) loads raster basemap tiles as plain
# <img> elements from a few keyless tile hosts, so only img-src is widened — never
# script-src or connect-src. Each host below backs one basemap style in
# webapp/src/lib/mapgeo.ts (CARTO dark/voyager, Esri World Imagery, OpenTopoMap);
# adding a style there means adding its host here. Leaflet's own CSS is bundled, so
# no extra style/font host is needed.
CONSOLE_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "img-src 'self' data: "
    "https://*.basemaps.cartocdn.com https://server.arcgisonline.com https://*.tile.opentopomap.org "
    "https://soft-zoom-63098134.figma.site https://*.figma.site https://images.unsplash.com; "
    "media-src 'self' data: blob: https://d8j0ntlcm91z4.cloudfront.net https://*.cloudfront.net; "
    "connect-src 'self' https://api.groq.com"
)



# Matched as a prefix (the document is /console/, assets live under /console/…).
CONSOLE_PATH_PREFIX = "/console"

