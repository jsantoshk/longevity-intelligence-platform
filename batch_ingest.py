"""Batch-ingest a folder of global Senior Living / 50-city PDFs into the running LIP server."""

import argparse
import sys
import time
from pathlib import Path

import httpx

DEFAULT_API = "http://localhost:8000"


def infer_city(pdf_path: Path, explicit_city: str) -> str:
    if explicit_city:
        return explicit_city
    # Infer city from filename prefix like "Cardiff_Age_Friendly_2025.pdf" -> "Cardiff"
    stem = pdf_path.stem.replace("-", "_").split("_")[0].strip()
    return stem.title() if stem.isalpha() else ""


def ingest_file(client: httpx.Client, api_url: str, pdf_path: Path, city: str, country: str, sector: str) -> bool:
    print(f"\n[UPLOAD] {pdf_path.name} (city={city or 'auto'}, country={country or '-'}, sector={sector})")
    with pdf_path.open("rb") as f:
        res = client.post(
            f"{api_url}/api/upload",
            files={"file": (pdf_path.name, f, "application/pdf")},
            data={"city": city, "country": country, "sector": sector},
            timeout=120,
        )
    if res.status_code != 200:
        print(f"  [ERROR] Upload failed ({res.status_code}): {res.text}")
        return False

    job_id = res.json()["job_id"]
    while True:
        time.sleep(2)
        poll = client.get(f"{api_url}/api/jobs/{job_id}", timeout=30)
        if poll.status_code != 200:
            print(f"  [ERROR] Poll failed: {poll.status_code}")
            return False
        job = poll.json()
        status = job["status"]
        if status == "running":
            active = next((s for s in job["stages"] if s["state"] == "active"), None)
            if active:
                print(f"  -> Stage {active['id']:02d} ({active['name']}): {active['detail']}", end="\r", flush=True)
            continue

        print(" " * 80, end="\r")
        if status == "error":
            print(f"  [FAILED] {job['error']}")
            return False
        if job.get("duplicate"):
            print("  [SKIPPED] Duplicate SHA-256 already stored.")
            return True
        c = job["counts"]
        print(f"  [DONE] {c['dimensions']} dimensions, {c['kpis']} KPIs, {c['interventions']} interventions.")
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch ingest PDFs into LIP.")
    parser.add_argument("--dir", required=True, help="Folder containing PDF files")
    parser.add_argument("--api", default=DEFAULT_API, help="LIP server URL (default: http://localhost:8000)")
    parser.add_argument("--city", default="", help="City tag (optional; inferred from filename if blank)")
    parser.add_argument("--country", default="", help="Country tag (e.g., UK, Japan, Singapore)")
    parser.add_argument("--sector", default="Senior Living", help="Sector tag (e.g., Senior Living, Smart City)")
    args = parser.parse_args()

    folder = Path(args.dir).expanduser().resolve()
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"No PDF files found in {folder}")
        sys.exit(1)

    print(f"Found {len(pdfs)} PDF(s) in {folder}. Starting unattended ingestion...")
    ok = failed = 0
    with httpx.Client() as client:
        for pdf in pdfs:
            city = infer_city(pdf, args.city)
            if ingest_file(client, args.api.rstrip("/"), pdf, city, args.country, args.sector):
                ok += 1
            else:
                failed += 1

    print(f"\nBatch complete: {ok} succeeded/skipped, {failed} failed.")


if __name__ == "__main__":
    main()