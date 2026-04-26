"""
Data cleaning utilities:
  - Normalize phone numbers
  - Validate + filter junk emails
  - Deduplicate leads by website or name
  - Merge Maps data + Contact scraper data into one clean lead
"""
import re
from urllib.parse import urlparse

# ── Email filtering ───────────────────────────────────────────────────────────

JUNK_EMAIL_PATTERNS = [
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "example", "test@", "admin@", "webmaster@", "postmaster@",
    "support@", "info@info", "hello@hello", "contact@contact",
    "@example.", "@test.", "@domain.", "@email.", "@yoursite.",
    "@sampleemail.", "@mailinator.", "@guerrillamail."
]

JUNK_DOMAINS = [
    "example.com", "test.com", "domain.com", "email.com",
    "mailinator.com", "guerrillamail.com", "tempmail.com",
    "throwam.com", "yopmail.com"
]


def is_valid_email(email: str) -> bool:
    if not email:
        return False
    email = email.strip().lower()
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email):
        return False
    # Filter junk patterns
    if any(j in email for j in JUNK_EMAIL_PATTERNS):
        return False
    # Filter junk domains
    domain = email.split("@")[-1]
    if domain in JUNK_DOMAINS:
        return False
    return True


# ── URL normalization ─────────────────────────────────────────────────────────

def normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip().lower()
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")


# ── Phone cleaning ────────────────────────────────────────────────────────────

def clean_phone(phone: str) -> str:
    if not phone:
        return ""
    cleaned = re.sub(r"[^\d\+\-\(\)\s]", "", str(phone)).strip()
    return cleaned if len(cleaned) >= 7 else ""


# ── Name cleaning ─────────────────────────────────────────────────────────────

def clean_name(name: str) -> str:
    if not name:
        return ""
    return name.strip().title()


# ── Lead merging ──────────────────────────────────────────────────────────────

def merge_lead(maps_data: dict, contact_data: dict) -> dict:
    name    = clean_name(maps_data.get("title") or maps_data.get("name") or "")
    website = (maps_data.get("website") or "").strip()
    phone   = clean_phone(
        contact_data.get("best_phone") or
        contact_data.get("phone") or
        maps_data.get("phone") or
        maps_data.get("phoneUnformatted") or ""
    )
    email      = (contact_data.get("best_email") or "").strip().lower()
    confidence = float(contact_data.get("best_contact_confidence_score") or 0)

    return {
        "name":       name,
        "website":    website,
        "email":      email,
        "phone":      phone,
        "confidence": round(confidence, 2),
    }


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(leads: list[dict]) -> list[dict]:
    seen_domains: dict[str, dict] = {}
    seen_names:   dict[str, dict] = {}

    for lead in leads:
        domain = normalize_url(lead.get("website", ""))
        name   = lead.get("name", "").lower().strip()

        if domain and domain in seen_domains:
            if lead["confidence"] > seen_domains[domain]["confidence"]:
                seen_domains[domain] = lead
            continue

        if name and name in seen_names:
            if lead["confidence"] > seen_names[name]["confidence"]:
                seen_names[name] = lead
            continue

        if domain:
            seen_domains[domain] = lead
        elif name:
            seen_names[name] = lead

    all_leads = list(seen_domains.values())
    domain_websites = {normalize_url(l["website"]) for l in all_leads}
    for lead in seen_names.values():
        if normalize_url(lead.get("website", "")) not in domain_websites:
            all_leads.append(lead)

    return sorted(all_leads, key=lambda x: x["confidence"], reverse=True)
