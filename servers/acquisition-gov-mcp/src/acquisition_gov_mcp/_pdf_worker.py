"""Private, isolated PDF parser entry point. No network or tool execution."""
import json
import sys
from .constants import MAX_PDF_BYTES, MAX_PDF_WORKER_BYTES, MAX_PDF_WORKER_MEMORY_BYTES


def main():
    # Linux is the hosted runtime. macOS/Windows still get process isolation,
    # a parent-enforced deadline and explicit content/output bounds.
    if sys.platform == "linux":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (MAX_PDF_WORKER_MEMORY_BYTES, MAX_PDF_WORKER_MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    from ._pdf import _read_pdf
    body = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
    if len(body) > MAX_PDF_BYTES:
        raise ValueError("PDF input too large")
    try:
        result = _read_pdf(body, page_start=int(sys.argv[1]), page_end=None if sys.argv[2] == "none" else int(sys.argv[2]))
    except Exception as exc:
        result = ("", "error", [f"PDF parsing failed: {type(exc).__name__}."], {}, 0, 0)
    output = json.dumps(result, ensure_ascii=False).encode("utf-8")
    if len(output) > MAX_PDF_WORKER_BYTES:
        raise ValueError("PDF result too large")
    sys.stdout.buffer.write(output)

if __name__ == "__main__":
    main()
