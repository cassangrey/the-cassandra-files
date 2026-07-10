"""Generate the website timeline page from a CSV export of the evidence matrix.

The source sheet contains private/internal columns. This generator only publishes the
website-facing columns and treats access status as the publication boundary.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import shutil
from pathlib import Path

ACCESS_DO_NOT_PUBLISH = {"Do not publish"}
ACCESS_BLANK_DESCRIPTION = {
    "Legally restricted",
    "Legally restricted: TBC",
    "Restricted access only",
}
PUBLIC_EVIDENCE_ACCESS = {"public"}
PSEUDONYMOUS_PUBLIC_HANDLES = {
    "barnaclebuster26",
    "bobby.bottle0",
    "sunny.daze184",
    "tom.tank0",
}
SITE_FILE_RE = re.compile(r"SITE FILE:\s*([^\r\n]+)")
URL_RE = re.compile(r"https?://[^\s;,)]+")
IMAGE_PATH_RE = re.compile(r"(?P<path>(?:[A-Za-z]:)?[^;\r\n]+?\.(?:png|jpe?g|webp))", re.IGNORECASE)
CHILD_REFERENCE_RE = re.compile(r"\b(?:SRB|child|daughter)\b", re.IGNORECASE)
PUBLIC_SCREENSHOT_DIR = Path("docs/evidence/public-post-screenshots")
WORKSPACE_ROOT = Path.cwd().parents[1] if Path.cwd().name == "site" and len(Path.cwd().parents) > 1 else Path.cwd()

INTRO = """# The record

This chronology is generated from the website-facing publication columns of the evidence matrix. It is not a public document dump.

Where a record is legally restricted, the dated row is retained but the descriptive entry is left blank. This preserves the shape of the chronology without publishing material that should only be handled through legal review or controlled access.

"""


def norm(value: str | None) -> str:
    return (value or "").strip()


def first_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = norm(row.get(name))
        if value:
            return value
    return ""


def cell(value: str) -> str:
    escaped = html.escape(value, quote=False)
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n\n", "<br><br>").replace("\n", "<br>")


def site_file_href(raw_path: str) -> str:
    path = raw_path.strip().replace("\\", "/")
    marker = "Restricted Evidence Portal/site/docs/"
    if marker in path:
        return "../" + path.split(marker, 1)[1]
    docs_marker = "docs/"
    if path.startswith(docs_marker):
        return "../" + path.split(docs_marker, 1)[1]
    return path


def link_label(href: str) -> str:
    lower = href.lower()
    if lower.endswith(".pdf"):
        return "Open redacted PDF"
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "Open screenshot"
    if "youtube.com" in lower or "youtu.be" in lower:
        return "Open video"
    if "tiktok.com" in lower:
        return "Open post"
    return "Open evidence"


def row_mentions_child(row: dict[str, str]) -> bool:
    text = " ".join(
        norm(row.get(name))
        for name in (
            "Incident",
            "Actor / institution",
            "Context",
            "Public wording",
            "Website wording",
            "Source / verification",
        )
    )
    return bool(CHILD_REFERENCE_RE.search(text))


def clean_candidate_path(raw_path: str) -> Path:
    path = raw_path.strip().strip(" .,:;\"")
    path = re.sub(
        r"^(?:local capture|source/original|screenshot|capture|local video|redacted upload file):\s*",
        "",
        path,
        flags=re.IGNORECASE,
    )
    return Path(path.strip().strip('"'))


def copy_public_screenshot(source_path: Path, row_index: int) -> str | None:
    candidates = [source_path]
    if not source_path.is_absolute():
        candidates.append(WORKSPACE_ROOT / source_path)
        candidates.append(Path.cwd() / source_path)

    resolved_source = next((candidate for candidate in candidates if candidate.exists() and candidate.is_file()), None)
    if resolved_source is None:
        return None

    PUBLIC_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    safe_stem = re.sub(r"[^A-Za-z0-9.-]+", "-", resolved_source.stem).strip("-")[:90] or "screenshot"
    destination = PUBLIC_SCREENSHOT_DIR / f"{row_index:03d}-{safe_stem}{resolved_source.suffix.lower()}"

    try:
        from PIL import Image

        with Image.open(resolved_source) as image:
            image.save(destination)
    except Exception:
        shutil.copy2(resolved_source, destination)

    return "../" + destination.as_posix().split("docs/", 1)[1]

def public_screenshot_links(row: dict[str, str], row_index: int, evidence_access: str) -> list[str]:
    # Do not auto-publish raw screenshots. Public-post captures often contain
    # names or surrounding context that needs a separate redaction pass.
    return []


def has_pseudonymous_live_url(source: str) -> bool:
    lower = source.lower()
    return any(handle in lower for handle in PSEUDONYMOUS_PUBLIC_HANDLES)


def should_publish_live_url(row: dict[str, str], evidence_access: str) -> bool:
    if evidence_access.strip().lower() in PUBLIC_EVIDENCE_ACCESS:
        return True

    item = first_value(row, "Public evidence item", "Website evidence status").lower()
    source = norm(row.get("Source / verification"))
    publication = norm(row.get("Access / publication decision")).lower()

    if "public post" not in item and "public post" not in source.lower() and "tiktok" not in source.lower():
        return False
    if not has_pseudonymous_live_url(source):
        return False
    if publication.startswith("legally restricted") or publication == "do not publish":
        return False
    return True

def public_evidence_links(row: dict[str, str], row_index: int, evidence_access: str) -> list[str]:
    source = norm(row.get("Source / verification"))
    if not should_publish_live_url(row, evidence_access):
        return []

    links: list[str] = public_screenshot_links(row, row_index, evidence_access)

    for match in SITE_FILE_RE.finditer(source):
        links.append(site_file_href(match.group(1)))

    if not links:
        for match in URL_RE.finditer(source):
            links.append(match.group(0).rstrip(".,"))

    deduped: list[str] = []
    for link in links:
        if link and link not in deduped:
            deduped.append(link)
    return deduped

def evidence_cell(value: str, links: list[str]) -> str:
    rendered = cell(value)
    if not links:
        return rendered

    anchors: list[str] = []
    for index, link in enumerate(links, start=1):
        label = link_label(link)
        if len(links) > 1:
            label = f"{label} {index}"
        href = html.escape(link, quote=True)
        anchors.append(f'<a href="{href}" target="_blank" rel="noopener">{html.escape(label)}</a>')

    if rendered:
        rendered += "<br>"
    return rendered + '<span class="evidence-links">' + " ".join(anchors) + "</span>"


def is_blank_description(access: str) -> bool:
    return access in ACCESS_BLANK_DESCRIPTION or access.lower().startswith("legally restricted")


def display_publication(access: str) -> str:
    if access == "Discussable; evidence restricted":
        return "Discussable on request; not publishable here"
    return access


def wording_for(row: dict[str, str]) -> str:
    publication = norm(row.get("Access / publication decision"))
    if is_blank_description(publication):
        return ""
    return norm(row.get("Website wording"))


def render_table(rows: list[dict[str, str]], limit: int | None = None) -> str:
    body: list[str] = []
    count = 0
    for row in rows:
        publication = norm(row.get("Access / publication decision"))
        if publication in ACCESS_DO_NOT_PUBLISH:
            continue

        date = norm(row.get("Date"))
        if not date:
            continue

        wording = wording_for(row)
        evidence_item = first_value(row, "Public evidence item", "Website evidence status")
        evidence_access = first_value(row, "Evidence access", "Evidence access route")
        links = public_evidence_links(row, count + 1, evidence_access)

        body.append("  <tr>")
        body.append(f"    <td>{cell(date)}</td>")
        body.append(f"    <td>{cell(wording)}</td>")
        body.append(f"    <td>{evidence_cell(evidence_item, links)}</td>")
        body.append(f"    <td>{cell(evidence_access)}</td>")
        body.append(f"    <td>{cell(display_publication(publication))}</td>")
        body.append("  </tr>")
        count += 1
        if limit is not None and count >= limit:
            break

    table = [
        '<table class="record-table">',
        '  <thead>',
        '    <tr>',
        '      <th>Date</th>',
        '      <th>Record</th>',
        '      <th>Evidence item</th>',
        '      <th>Evidence access</th>',
        '      <th>Publication level</th>',
        '    </tr>',
        '  </thead>',
        '  <tbody>',
        *body,
        '  </tbody>',
        '</table>',
        '',
    ]
    return "\n".join(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate docs/institutional-timeline.md from a CSV export.")
    parser.add_argument("csv_path", type=Path, help="Path to CSV exported from the evidence matrix.")
    parser.add_argument("--output", type=Path, default=Path("docs/institutional-timeline.md"))
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for review drafts.")
    args = parser.parse_args()

    with args.csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    headers = set(rows[0].keys() if rows else [])
    required = {"Date", "Access / publication decision", "Website wording"}
    missing = required.difference(headers)
    if missing:
        raise SystemExit(f"CSV is missing required columns: {', '.join(sorted(missing))}")

    if not ({"Evidence access", "Evidence access route"} & headers):
        raise SystemExit("CSV is missing an evidence access column")

    output = INTRO + render_table(rows, args.limit)
    args.output.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
