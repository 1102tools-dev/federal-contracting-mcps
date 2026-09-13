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

# PDF parsing runs outside the server event loop with bounded input and output.
MAX_PDF_TEXT_CHARACTERS = 200_000
MAX_PDF_PAGE_STREAM_BYTES = 2 * 1024 * 1024
MAX_PDF_PARSE_SECONDS = 30
MAX_PDF_WORKER_BYTES = 2 * 1024 * 1024
MAX_PDF_WORKER_MEMORY_BYTES = 160 * 1024 * 1024

MAX_HTML_WORKER_BYTES = 8 * 1024 * 1024
