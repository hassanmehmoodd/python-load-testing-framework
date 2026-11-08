"""Hard safety limits. Configuration files cannot raise these values."""

ABSOLUTE_MAX_USERS = 50
ABSOLUTE_MAX_SPAWN_RATE = 15.0
ABSOLUTE_MAX_DURATION_SECONDS = 600
MIN_DURATION_SECONDS = 5

DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "::1")

# Well-known public services. Matched as the host or as a subdomain.
# Acknowledgement does not override this list.
PUBLIC_DENYLIST_SUFFIXES = (
    "google.com",
    "googleapis.com",
    "gstatic.com",
    "github.com",
    "githubusercontent.com",
    "facebook.com",
    "fb.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "microsoft.com",
    "office.com",
    "live.com",
    "cloudflare.com",
    "amazon.com",
    "wikipedia.org",
    "reddit.com",
    "netflix.com",
    "apple.com",
    "openai.com",
    "anthropic.com",
)

PROFILES = ("constant", "ramp", "stress", "spike", "endurance")
ACK_TRUTHY = frozenset({"1", "true", "yes", "y"})
