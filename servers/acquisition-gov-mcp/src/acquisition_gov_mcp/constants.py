# SPDX-License-Identifier: MIT
from . import __version__

BASE_URL = "https://www.acquisition.gov"
RFO_INDEX_URL = f"{BASE_URL}/far-overhaul/far-part-deviation-guide"
GUIDANCE_URLS = {
    "faq": f"{BASE_URL}/far-overhaul/faqs",
    "policy_and_guidance": f"{BASE_URL}/far-overhaul/policy-and-guidance",
    "deviation_guidance": (
        f"{BASE_URL}/sites/default/files/page_file_uploads/"
        "FAR-Council-Deviation-Guidance-on-FAR-Overhaul.pdf"
    ),
}
ALLOWED_HOSTS = frozenset({"acquisition.gov", "www.acquisition.gov"})
USER_AGENT = f"acquisition-gov-mcp/{__version__}"
DEFAULT_TIMEOUT = 10.0
MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 25
MAX_REDIRECTS = 3
DEFAULT_MAX_CHARACTERS = 20_000
MAX_OUTPUT_CHARACTERS = 40_000
