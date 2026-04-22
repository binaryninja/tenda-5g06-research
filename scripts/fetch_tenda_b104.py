#!/usr/bin/env python3
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


API_URL = "https://www.tendacn.com/prod/api/data/center/list"
USER_AGENT = "Mozilla/5.0 (compatible; codex-firmware-fetcher/1.0)"


def request_json(url, params):
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def safe_name(value):
    value = re.sub(r"[^\w.\-()+]+", "_", value.strip())
    value = value.strip("._")
    return value or "firmware"


def normalize_url(url):
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(urllib.parse.unquote(parts.query), safe="=&?:/@!$'()*+,;%-._~")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def normalize_record(record):
    url = normalize_url(record.get("file") or record.get("linkUrl") or "")
    basename = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
    title = safe_name(record.get("title") or record.get("name") or "firmware")
    version = safe_name(record.get("version") or "unknown")
    suffix = safe_name(basename) if basename else f"{title}_{version}.bin"
    sync_flag = str(record.get("syncFlag") or record.get("id") or title)
    return {
        "id": record.get("id"),
        "syncFlag": record.get("syncFlag"),
        "title": record.get("title"),
        "version": record.get("version"),
        "products": record.get("linkProdOrClassName") or [],
        "format": record.get("format"),
        "fileSize": record.get("fileSize") or 0,
        "updateTime": record.get("updateTime"),
        "url": url,
        "filename": f"{sync_flag}_{suffix}",
        "detailUrl": f"https://www.tendacn.com/material/show/{sync_flag}",
    }


def fetch_manifest(site_id, url_flag, page_size):
    params = {
        "urlFlag": url_flag,
        "sortField": "updateTime",
        "pageSize": page_size,
        "pageNum": 1,
        "siteId": site_id,
        "linkProductOrClass": "",
        "keyword": "",
    }
    payload = request_json(API_URL, params)
    if payload.get("code") != 200:
        raise RuntimeError(f"Tenda API returned code={payload.get('code')} msg={payload.get('msg')}")
    data = payload.get("data") or {}
    records = data.get("records") or []
    total = int(data.get("total") or len(records))
    if total > len(records):
        params["pageSize"] = total
        payload = request_json(API_URL, params)
        data = payload.get("data") or {}
        records = data.get("records") or []
    items = [normalize_record(item) for item in records if item.get("file") or item.get("linkUrl")]
    return {
        "source": "https://www.tendacn.com/download?urlFlag=B104",
        "api": API_URL,
        "siteId": site_id,
        "urlFlag": url_flag,
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": total,
        "count": len(items),
        "totalFileSize": sum(float(item.get("fileSize") or 0) for item in items),
        "items": items,
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_one(item, download_dir, hash_files=False):
    url = item["url"]
    output = download_dir / item["filename"]
    expected_size = int(float(item.get("fileSize") or 0))
    if output.exists() and output.stat().st_size > 0:
        actual_size = output.stat().st_size
        status = "exists" if expected_size <= 0 or actual_size == expected_size else "exists-size-diff"
        result = {
            "filename": output.name,
            "status": status,
            "bytes": actual_size,
            "expectedBytes": expected_size,
        }
        if hash_files:
            result["sha256"] = sha256_file(output)
        return result

    part = output.with_suffix(output.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as response, part.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    os.replace(part, output)

    actual_size = output.stat().st_size
    status = "downloaded" if expected_size <= 0 or actual_size == expected_size else "downloaded-size-diff"
    result = {
        "filename": output.name,
        "status": status,
        "bytes": actual_size,
        "expectedBytes": expected_size,
    }
    if hash_files:
        result["sha256"] = sha256_file(output)
    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch Tenda B104 firmware metadata and archives.")
    parser.add_argument("--site-id", type=int, default=14)
    parser.add_argument("--url-flag", default="B104")
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--output", default="manifest.json")
    parser.add_argument("--urls-output", default="urls.txt")
    parser.add_argument("--download-dir", default="downloads")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Download only the first N manifest entries.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--hash", action="store_true", help="Compute SHA-256 for downloaded files.")
    args = parser.parse_args()

    manifest = fetch_manifest(args.site_id, args.url_flag, args.page_size)
    output = Path(args.output)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(args.urls_output).write_text(
        "\n".join(item["url"] for item in manifest["items"]) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {manifest['count']} entries to {output}", file=sys.stderr)

    if not args.download:
        return

    download_dir = Path(args.download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)
    items = manifest["items"][: args.limit] if args.limit else manifest["items"]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_map = {
            executor.submit(download_one, item, download_dir, args.hash): item for item in items
        }
        for future in concurrent.futures.as_completed(future_map):
            item = future_map[future]
            try:
                result = future.result()
                results.append(result)
                print(f"{result['status']}: {result['filename']} ({result['bytes']} bytes)", flush=True)
            except Exception as exc:
                result = {
                    "filename": item.get("filename"),
                    "url": item.get("url"),
                    "status": "failed",
                    "error": str(exc),
                }
                results.append(result)
                print(f"failed: {item.get('filename')}: {exc}", file=sys.stderr, flush=True)

    (download_dir / "download_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    failed = [item for item in results if item.get("status") == "failed"]
    if failed:
        print(f"completed with {len(failed)} failed downloads", file=sys.stderr)


if __name__ == "__main__":
    main()
