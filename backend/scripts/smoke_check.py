"""Small API availability smoke check; does not mutate application data."""
import argparse, json, sys
from urllib.error import URLError, HTTPError
from urllib.request import urlopen

def fetch(url):
    with urlopen(url, timeout=8) as response:
        return response.status, json.loads(response.read().decode("utf-8"))

def main():
    p=argparse.ArgumentParser(); p.add_argument("--base-url", default="http://127.0.0.1:8000"); args=p.parse_args()
    base=args.base_url.rstrip("/")
    failed=False
    for path in ("/health", "/api/v1/health", "/api/v1/ai/status"):
        try:
            status, body=fetch(base+path)
            ok=status==200
            print(("PASS" if ok else "FAIL"), path, "HTTP", status, json.dumps(body, ensure_ascii=False)[:500])
            failed |= not ok
        except (URLError, HTTPError, TimeoutError, ValueError) as exc:
            print("FAIL", path, str(exc)); failed=True
    return 1 if failed else 0
if __name__=="__main__": sys.exit(main())
