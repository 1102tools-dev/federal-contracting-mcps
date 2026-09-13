"""Private HTML parser process. Reads bounded stdin; performs no network calls."""
import json
import sys


def main():
    if sys.platform == 'linux':
        import resource
        memory = 192 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    from ._html import _parse_index, _parse_html_document
    from .constants import MAX_HTML_BYTES, MAX_HTML_WORKER_BYTES
    body = sys.stdin.buffer.read(MAX_HTML_BYTES + 1)
    if len(body) > MAX_HTML_BYTES:
        raise ValueError('HTML input exceeds download limit')
    try:
        arguments = json.loads(sys.argv[2])
        if sys.argv[1] == 'index':
            value = _parse_index(body, **arguments)
        elif sys.argv[1] == 'document':
            value = _parse_html_document(body, **arguments)
        else:
            raise ValueError('Unknown HTML parser operation')
        result = {'result': value}
    except (ValueError, RuntimeError) as exc:
        result = {'kind': type(exc).__name__, 'error': str(exc)}
    except Exception as exc:
        result = {'kind': type(exc).__name__, 'error': 'HTML parsing failed.'}
    output = json.dumps(result, ensure_ascii=False).encode('utf-8')
    if len(output) > MAX_HTML_WORKER_BYTES:
        raise ValueError('HTML result exceeds output limit')
    sys.stdout.buffer.write(output)


if __name__ == '__main__':
    main()
