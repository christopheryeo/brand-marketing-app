#!/usr/bin/env python3
"""Deterministic Influential Brands Wiki ingestion and quality pipeline."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.utils
import hashlib
import html
import io
import json
import logging
import os
import re
import shutil
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

SGT = dt.timezone(dt.timedelta(hours=8))
ROOT = Path(os.environ.get("IB_WIKI_ROOT", Path(__file__).resolve().parents[1])).resolve()
DEFAULT_EXCEL = Path(os.environ.get(
    "IB_EXCEL_SOURCE",
    "/Users/chrisyeo/Library/CloudStorage/Dropbox/Work/CEO (Sentient)/Alex (Dev)/Scratchpad/OLM/Database to Explore.xlsx",
))
DEFAULT_OLM = Path(os.environ.get(
    "IB_OLM_SOURCE",
    "/Users/chrisyeo/Library/CloudStorage/Dropbox/Work/CEO (Sentient)/Alex (Dev)/Scratchpad/OLM/Outlook for Mac Archive.olm",
))
SYSTEM_FILES = {"index.md", "catalog.md", "log.md"}
EXCLUDED_FOLDERS = {"drafts", "trash", "spam"}
ROLE_PREFIXES = {
    "admin", "billing", "contact", "customerservice", "enquiry", "hello", "hr",
    "info", "mail", "marketing", "office", "orders", "sales", "support", "team",
}
RELATIONSHIP_ID_FIELDS = {
    "personId", "organisationId", "ownerOrganisationId", "industryId", "locationId", "brandId",
    "functionId", "marketingSegmentId", "campaignId", "productServiceId", "projectInitiativeId",
    "opportunityId", "meetingEventId", "ownerId", "prospectOrganisationId", "providerOrganisationId",
    "parentIndustryId", "parentLocationId",
}
PLACEHOLDERS = {"", "-", "n/a", "na", "none", "not applicable", "null", "unknown"}
EXPECTED_EXCEL_ROWS = int(os.environ.get("IB_EXPECTED_EXCEL_ROWS", "2008"))
EXPECTED_OLM_MESSAGES = int(os.environ.get("IB_EXPECTED_OLM_MESSAGES", "4918"))
EXPECTED_ELIGIBLE_MESSAGES = int(os.environ.get("IB_EXPECTED_ELIGIBLE_MESSAGES", "4717"))
EXPECTED_EXCLUDED_MESSAGES = int(os.environ.get("IB_EXPECTED_EXCLUDED_MESSAGES", "201"))
EXPECTED_OLM_ATTACHMENTS = int(os.environ.get("IB_EXPECTED_OLM_ATTACHMENTS", "4609"))
EXPECTED_OLM_EVENTS = int(os.environ.get("IB_EXPECTED_OLM_EVENTS", "12"))
EXPECTED_OLM_CONTACTS = int(os.environ.get("IB_EXPECTED_OLM_CONTACTS", "1"))
EXPECTED_EXCEL_HASH = os.environ.get("IB_EXCEL_SHA256", "45bce6eabeb54fcec448049cad0bbb0a7da235b839492c68c3dc9385f7e30737")
EXPECTED_OLM_HASH = os.environ.get("IB_OLM_SHA256", "0e83705b5eecc03f15f6ab6f2f5750bfe5c58e4cb4cb4a78055a8f05ca953520")
ENTITY_CONFIG = {
    "person": ("people", "personId", "displayName"),
    "organisation": ("organisations", "organisationId", "name"),
    "brand": ("brands", "brandId", "name"),
    "location": ("locations", "locationId", "name"),
    "industry": ("industries", "industryId", "name"),
    "appointment": ("appointments", "appointmentId", "title"),
    "organisational-function": ("organisational-functions", "functionId", "name"),
    "marketing-segment": ("marketing-segments", "marketingSegmentId", "name"),
    "marketing-campaign": ("marketing-campaigns", "campaignId", "name"),
    "email-message": ("email-messages", "emailMessageId", "subject"),
    "product-service": ("products-services", "productServiceId", "name"),
    "project-initiative": ("projects-initiatives", "projectInitiativeId", "name"),
    "sales-opportunity": ("sales-opportunities", "opportunityId", "name"),
    "meeting-event": ("meetings-events", "meetingEventId", "title"),
    "topic": ("topics", "topicId", "name"),
    "source": ("sources", "sourceId", "name"),
}


def now_sgt() -> str:
    return dt.datetime.now(SGT).isoformat(timespec="seconds")


def clay_enhanced_schema() -> dict[str, Any]:
    return {
        "type": ["string", "null"],
        "format": "date",
        "description": "Date of the latest successful Clay enhancement in YYYY-MM-DD format, or null when no verified enhancement is recorded.",
    }


def to_enhance_schema() -> dict[str, Any]:
    return {
        "type": ["boolean", "null"],
        "description": "True when this Person record's notes require enhancement, false when assessed and clear, and null when not yet assessed.",
    }


def validate_clay_enhanced_date(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError("clayEnhanced must be an ISO date string or null")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("clayEnhanced must use YYYY-MM-DD format") from error
    if parsed.isoformat() != value:
        raise ValueError("clayEnhanced must use YYYY-MM-DD format")


def validate_to_enhance(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, bool):
        raise ValueError("ToEnhance must be a Boolean or null")


def canonical_timestamp() -> str:
    override = os.environ.get("IB_CANONICAL_TIMESTAMP")
    if override:
        return override
    timestamps = [path.stat().st_mtime for path in (DEFAULT_EXCEL, DEFAULT_OLM) if path.exists()]
    return dt.datetime.fromtimestamp(max(timestamps), SGT).isoformat(timespec="seconds") if timestamps else "2026-08-08T00:00:00+08:00"


def run_id() -> str:
    return dt.datetime.now(SGT).strftime("%Y%m%dT%H%M%S+0800")


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value)).strip()
    return re.sub(r"\s+", " ", text)


def null_if_placeholder(value: Any) -> str | None:
    text = normalize_text(value)
    return None if text.casefold() in PLACEHOLDERS else text


def normalize_email(value: Any) -> tuple[str | None, list[str]]:
    raw = normalize_text(value)
    repairs: list[str] = []
    if not raw:
        return None, repairs
    candidate = raw
    if candidate.casefold().startswith("mailto:"):
        candidate = candidate[7:]
        repairs.append("removed-mailto-prefix")
    stripped = candidate.strip(" <>\t\r\n,;")
    if stripped != candidate:
        repairs.append("removed-surrounding-punctuation")
    candidate = stripped.casefold()
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", candidate):
        return candidate, repairs
    return None, repairs


def normalize_url(value: Any) -> str | None:
    text = null_if_placeholder(value)
    if not text:
        return None
    text = text.strip().rstrip("/")
    text = re.sub(r"^http://", "https://", text, flags=re.I)
    return text


def slug(value: str, limit: int = 64) -> str:
    base = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()
    return (base[:limit].rstrip("-") or "record")


def stable_id(kind: str, key: str) -> str:
    return f"{slug(kind, 24)}-{slug(key, 48)}-{hashlib.sha256(key.casefold().encode()).hexdigest()[:10]}"


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def write_ndjson(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with temp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    temp.replace(path)
    return count


def read_ndjson(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def source_ref(source_id: str, locator: str, method: str = "deterministic") -> dict[str, str]:
    return {
        "sourceId": source_id,
        "locator": locator,
        "method": method,
        "evidenceHash": hashlib.sha256(locator.encode()).hexdigest(),
    }


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def xml_child_text(root: ET.Element, name: str) -> str | None:
    for node in root.iter():
        if local_name(node.tag) == name:
            return normalize_text(node.text) or None
    return None


def xml_addresses(root: ET.Element, container: str) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for node in root.iter():
        if local_name(node.tag) != container:
            continue
        for address in node.iter():
            if local_name(address.tag) != "emailAddress":
                continue
            email_value = normalize_email(address.attrib.get("OPFContactEmailAddressAddress"))[0]
            if email_value:
                output.append({
                    "email": email_value,
                    "name": normalize_text(address.attrib.get("OPFContactEmailAddressName")),
                })
    return output


def excel_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Read the first XLSX worksheet without altering or recalculating the workbook."""
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root:
                shared.append("".join(node.text or "" for node in item.iter() if local_name(node.tag) == "t"))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        first_sheet = next(node for node in workbook.iter() if local_name(node.tag) == "sheet")
        rel_id = next(value for key, value in first_sheet.attrib.items() if key.endswith("}id"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(node.attrib["Target"] for node in rels if node.attrib["Id"] == rel_id)
        sheet_name = target.lstrip("/") if target.startswith("/") else "xl/" + target.lstrip("/")
        root = ET.fromstring(archive.read(sheet_name))
        parsed: list[list[str]] = []
        max_col = 0
        for row in (node for node in root.iter() if local_name(node.tag) == "row"):
            values: dict[int, str] = {}
            for cell in (node for node in row if local_name(node.tag) == "c"):
                ref = cell.attrib.get("r", "A1")
                letters = re.match(r"[A-Z]+", ref).group(0)
                column = 0
                for letter in letters:
                    column = column * 26 + ord(letter) - 64
                column -= 1
                value_node = next((n for n in cell if local_name(n.tag) == "v"), None)
                inline = next((n for n in cell.iter() if local_name(n.tag) == "t"), None)
                value = value_node.text if value_node is not None and value_node.text is not None else (inline.text if inline is not None else "")
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                values[column] = value
                max_col = max(max_col, column)
            parsed.append([values.get(index, "") for index in range(max_col + 1)])
    headers = [normalize_text(value) for value in parsed[1]]
    records: list[dict[str, Any]] = []
    for excel_row, values in enumerate(parsed[2:], start=3):
        values += [""] * (len(headers) - len(values))
        if not any(normalize_text(value) for value in values):
            continue
        records.append({"sourceRow": excel_row, **dict(zip(headers, values))})
    return headers, records


def prepare_excel(path: Path, output_dir: Path, source_id: str) -> dict[str, Any]:
    headers, records = excel_rows(path)
    repairs: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    for record in records:
        email_value, email_repairs = normalize_email(record.get("Email Address"))
        for repair in email_repairs:
            repairs.append({"condition": "C1", "sourceRow": record["sourceRow"], "field": "Email Address", "repair": repair})
        first = null_if_placeholder(record.get("First Name"))
        last = null_if_placeholder(record.get("Last Name"))
        display = normalize_text(" ".join(value for value in (first, last) if value))
        linkedin = normalize_url(record.get("LinkedIn URL"))
        company = null_if_placeholder(record.get("Company"))
        sufficient = bool(email_value or linkedin or (display and company))
        normalized.append({
            "sourceRow": record["sourceRow"],
            "sourceRef": source_ref(source_id, f"Merged List!row {record['sourceRow']}"),
            "raw": record,
            "person": {"firstName": first, "lastName": last, "displayName": display or email_value, "email": email_value, "rawEmail": normalize_text(record.get("Email Address")), "linkedInUrl": linkedin},
            "organisation": company,
            "country": null_if_placeholder(record.get("Country")),
            "business": null_if_placeholder(record.get("Business")),
            "brand": null_if_placeholder(record.get("Brand")),
            "brandCategory": null_if_placeholder(record.get("Brand Category")),
            "function": null_if_placeholder(record.get("Function")),
            "position": null_if_placeholder(record.get("Position")),
            "industry": null_if_placeholder(record.get("Industry")),
            "designation": null_if_placeholder(record.get("Designation")),
            "marketingSegment": null_if_placeholder(record.get("EDM to")),
            "statusObservation": null_if_placeholder(record.get("2026 Status")),
            "companyUpdate": null_if_placeholder(record.get("Company Update")),
            "positionUpdate": null_if_placeholder(record.get("Position Update")),
            "disposition": "candidate" if sufficient else "quarantined",
            "issues": [] if sufficient else ["insufficient-stable-identity"],
        })
    emails = [row["person"]["email"] for row in normalized if row["person"]["email"]]
    email_counts = Counter(emails)
    for row in normalized:
        email_value = row["person"]["email"]
        if email_value and email_counts[email_value] > 1:
            row["issues"].append("duplicate-email-candidate")
    output_dir.mkdir(parents=True, exist_ok=True)
    write_ndjson(output_dir / "contacts.ndjson", normalized)
    write_ndjson(output_dir / "repair-log.ndjson", repairs)
    quality = {
        "sourceRows": len(records),
        "dispositions": dict(Counter(row["disposition"] for row in normalized)),
        "headers": headers,
        "populatedEmails": len(emails),
        "uniqueValidEmails": len(email_counts),
        "duplicateOccurrences": len(emails) - len(email_counts),
        "invalidOrMissingEmails": sum(1 for row in normalized if not row["person"]["email"]),
        "safeRepairs": len(repairs),
        "reconciled": len(records) == EXPECTED_EXCEL_ROWS,
    }
    json_dump(output_dir / "quality-report.json", quality)
    build_normalized_workbook(path, output_dir, output_dir / "contacts.ndjson", output_dir / "quality-report.json")
    return quality


def build_normalized_workbook(source: Path, output_dir: Path, contacts: Path, quality: Path) -> None:
    node = os.environ.get("IB_NODE_BIN") or shutil.which("node")
    if not node:
        raise RuntimeError("C0 Node.js is required to build and visually verify the normalized workbook")
    script = ROOT / "scripts" / "build_normalized_workbook.mjs"
    preview_dir = ROOT / "tmp" / "workbook-previews"
    command = [node, str(script), str(source), str(contacts), str(quality), str(output_dir / "database-to-explore.normalized.xlsx"), str(preview_dir)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"C0 normalized workbook build failed: {(result.stderr or result.stdout)[-1000:]}")


def mailbox_parts(name: str) -> tuple[str, str]:
    parts = name.split("/")
    account = parts[1] if parts and parts[0] == "Accounts" else "Local"
    try:
        marker = parts.index("com.microsoft.__Messages")
        folder = "/".join(parts[marker + 1:-1]) or "root"
    except ValueError:
        folder = "unknown"
    return account, folder


def parse_olm_message(data: bytes, path: str, source_id: str) -> dict[str, Any]:
    root = ET.fromstring(data)
    account, folder = mailbox_parts(path)
    folder_leaf = folder.rsplit("/", 1)[-1].casefold()
    from_values = xml_addresses(root, "OPFMessageCopyFromAddresses")
    to_values = xml_addresses(root, "OPFMessageCopyToAddresses")
    cc_values = xml_addresses(root, "OPFMessageCopyCCAddresses")
    bcc_values = xml_addresses(root, "OPFMessageCopyBCCAddresses")
    attachment_meta = []
    for node in root.iter():
        if local_name(node.tag) == "messageAttachment":
            attachment_meta.append({key: normalize_text(value) for key, value in node.attrib.items() if not key.startswith("{")})
    message_id = xml_child_text(root, "OPFMessageCopyMessageID")
    subject = xml_child_text(root, "OPFMessageCopySubject") or "(No subject)"
    sent_at = xml_child_text(root, "OPFMessageCopySentTime")
    received_at = xml_child_text(root, "OPFMessageCopyReceivedTime")
    body = xml_child_text(root, "OPFMessageCopyBody") or ""
    html_body = xml_child_text(root, "OPFMessageCopyHTMLBody") or ""
    fingerprint_basis = "|".join([account, path, sent_at or received_at or "", subject, body[:4096]])
    canonical_key = message_id or hashlib.sha256(fingerprint_basis.encode()).hexdigest()
    return {
        "sourcePath": path,
        "sourceRef": source_ref(source_id, path),
        "account": account,
        "folder": folder,
        "eligible": folder_leaf not in EXCLUDED_FOLDERS,
        "exclusionReason": f"excluded-folder:{folder_leaf}" if folder_leaf in EXCLUDED_FOLDERS else None,
        "messageId": message_id,
        "canonicalKey": canonical_key,
        "subject": subject,
        "sentAt": sent_at,
        "receivedAt": received_at,
        "threadTopic": xml_child_text(root, "OPFMessageCopyThreadTopic"),
        "threadIndex": xml_child_text(root, "OPFMessageCopyThreadIndex"),
        "inReplyTo": xml_child_text(root, "OPFMessageCopyInReplyTo"),
        "references": xml_child_text(root, "OPFMessageCopyReferences"),
        "from": from_values,
        "to": to_values,
        "cc": cc_values,
        "bcc": bcc_values,
        "bodyText": body,
        "bodyHtml": html_body,
        "bodyHash": sha256_bytes((body or html_body).encode()),
        "attachments": attachment_meta,
    }


def parse_calendar(data: bytes, source_id: str) -> list[dict[str, Any]]:
    root = ET.fromstring(data)
    events = []
    for ordinal, appointment in enumerate((n for n in root if local_name(n.tag) == "appointment"), start=1):
        values = {local_name(node.tag): normalize_text(node.text) for node in appointment if normalize_text(node.text)}
        attendees = []
        for node in appointment.iter():
            if local_name(node.tag) == "appointmentAttendee":
                attendees.append({key: normalize_text(value) for key, value in node.attrib.items() if not key.startswith("{")})
        locator = f"Local/Calendar/Calendar.xml#appointment-{ordinal}"
        events.append({
            "sourceRef": source_ref(source_id, locator),
            "uuid": values.get("OPFCalendarEventCopyUUID"),
            "title": values.get("OPFCalendarEventCopySummary") or "(Untitled event)",
            "description": values.get("OPFCalendarEventCopyDescriptionPlain") or values.get("OPFCalendarEventCopyDescription"),
            "startAt": values.get("OPFCalendarEventCopyStartTime"),
            "endAt": values.get("OPFCalendarEventCopyEndTime"),
            "location": values.get("OPFCalendarEventCopyLocation"),
            "attendees": attendees,
        })
    return events


def parse_contacts(data: bytes, source_id: str) -> list[dict[str, Any]]:
    root = ET.fromstring(data)
    output = []
    for ordinal, contact in enumerate((n for n in root if local_name(n.tag) == "contact"), start=1):
        values = {local_name(node.tag): normalize_text(node.text) for node in contact if normalize_text(node.text)}
        emails = []
        for node in contact.iter():
            if local_name(node.tag) == "contactEmailAddress":
                value = normalize_email(node.attrib.get("OPFContactEmailAddressAddress"))[0]
                if value:
                    emails.append(value)
        output.append({
            "sourceRef": source_ref(source_id, f"Local/Address Book/Contacts.xml#contact-{ordinal}"),
            "displayName": values.get("OPFContactCopyDisplayName"),
            "firstName": values.get("OPFContactCopyFirstName"),
            "emails": emails,
        })
    return output


def safe_attachment_text(name: str, data: bytes) -> tuple[str | None, str, str | None]:
    """Return extracted text, status, and error. Never executes attachment content."""
    suffix = Path(name).suffix.casefold()
    try:
        if not suffix:
            if data.startswith(b"%PDF"):
                suffix = ".pdf"
            elif data.startswith(b"PK\x03\x04"):
                suffix = ".zip"
            elif data.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8")):
                suffix = ".png"
            elif data and sum(byte in b"\t\n\r" or 32 <= byte <= 126 for byte in data[:4096]) / min(len(data), 4096) > 0.85:
                suffix = ".txt"
        if suffix in {".txt", ".csv", ".tsv", ".log", ".md", ".json", ".xml", ".html", ".htm", ".ics", ".vcf", ".mobileconfig", ".dat"}:
            return data.decode("utf-8", errors="replace"), "extracted", None
        if suffix == ".ai" and data.startswith(b"%PDF"):
            suffix = ".pdf"
        if suffix == ".pdf":
            from pypdf import PdfReader
            logging.getLogger("pypdf").setLevel(logging.ERROR)
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                return None, "quarantined", "encrypted-pdf"
            return "\n".join(page.extract_text() or "" for page in reader.pages), "extracted", None
        if suffix == ".docx":
            from docx import Document
            document = Document(io.BytesIO(data))
            return "\n".join(p.text for p in document.paragraphs), "extracted", None
        if suffix in {".xlsx", ".xlsm", ".pptx"}:
            with zipfile.ZipFile(io.BytesIO(data)) as nested:
                text_parts = []
                for member in nested.namelist():
                    if member.endswith(".xml") and ("sharedStrings" in member or "slides/slide" in member):
                        nested_root = ET.fromstring(nested.read(member))
                        text_parts.extend(node.text or "" for node in nested_root.iter() if local_name(node.tag) in {"t", "v"})
                return "\n".join(text_parts), "extracted", None
        if suffix == ".xls" and shutil.which("soffice"):
            with tempfile.TemporaryDirectory() as tmp:
                source_path = Path(tmp) / "legacy.xls"
                source_path.write_bytes(data)
                result = subprocess.run([shutil.which("soffice"), "--headless", "--convert-to", "xlsx", "--outdir", tmp, str(source_path)], capture_output=True, text=True, timeout=120, check=False)
                converted = Path(tmp) / "legacy.xlsx"
                if result.returncode == 0 and converted.exists():
                    return safe_attachment_text("legacy.xlsx", converted.read_bytes())
                return None, "quarantined", f"legacy-xls-conversion-failed:{result.stderr[-200:]}"
        if suffix == ".eml":
            from email import policy
            from email.parser import BytesParser
            message = BytesParser(policy=policy.default).parsebytes(data)
            parts = [f"Subject: {message.get('subject', '')}", f"From: {message.get('from', '')}", f"To: {message.get('to', '')}"]
            for part in message.walk():
                if part.is_multipart() or part.get_content_disposition() == "attachment" or part.get_content_type() not in {"text/plain", "text/html"}:
                    continue
                payload = part.get_payload(decode=True)
                if payload is None:
                    payload = str(part.get_payload()).encode()
                parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
            return "\n".join(str(part) for part in parts), "extracted", None
        if suffix in {".zip"}:
            with zipfile.ZipFile(io.BytesIO(data)) as nested:
                if sum(item.file_size for item in nested.infolist()) > 100 * 1024 * 1024:
                    return None, "quarantined", "nested-archive-too-large"
                parts = ["Archive members:", *nested.namelist()]
                for item in nested.infolist()[:200]:
                    if item.is_dir() or item.file_size > 20 * 1024 * 1024 or ".." in Path(item.filename).parts:
                        continue
                    nested_data = nested.read(item)
                    nested_text, nested_status, _ = safe_attachment_text(item.filename, nested_data)
                    if nested_status == "extracted" and nested_text:
                        parts += [f"\n--- {item.filename} ---", nested_text]
                return "\n".join(parts), "extracted", None
        if suffix == ".rar" and shutil.which("bsdtar"):
            with tempfile.TemporaryDirectory() as tmp:
                archive_path = Path(tmp) / "archive.rar"
                archive_path.write_bytes(data)
                result = subprocess.run([shutil.which("bsdtar"), "-tf", str(archive_path)], capture_output=True, text=True, timeout=60, check=False)
                if result.returncode == 0:
                    return "Archive members:\n" + result.stdout, "extracted", None
                return None, "quarantined", f"rar-list-failed:{result.stderr[-200:]}"
        if suffix in {".mp4", ".mov", ".m4v"} and shutil.which("mdls"):
            with tempfile.TemporaryDirectory() as tmp:
                media_path = Path(tmp) / ("media" + suffix)
                media_path.write_bytes(data)
                result = subprocess.run([shutil.which("mdls"), "-name", "kMDItemDurationSeconds", "-name", "kMDItemPixelHeight", "-name", "kMDItemPixelWidth", "-name", "kMDItemCodecs", str(media_path)], capture_output=True, text=True, timeout=60, check=False)
                if result.returncode == 0:
                    return result.stdout, "extracted", None
                return None, "quarantined", f"media-metadata-failed:{result.stderr[-200:]}"
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".psd"}:
            if suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
                width = int.from_bytes(data[16:20], "big")
                height = int.from_bytes(data[20:24], "big")
                if min(width, height) <= 3:
                    return "", "extracted", None
            try:
                from PIL import Image
                with Image.open(io.BytesIO(data)) as image:
                    if min(image.size) <= 3:
                        return "", "extracted", None
                    if suffix in {".gif", ".psd"}:
                        converted = io.BytesIO()
                        image.seek(0)
                        image.convert("RGB").save(converted, format="PNG")
                        data = converted.getvalue()
                        suffix = ".png"
            except Exception:
                if shutil.which("sips"):
                    with tempfile.TemporaryDirectory() as tmp:
                        source_path = Path(tmp) / ("source" + suffix)
                        png_path = Path(tmp) / "converted.png"
                        source_path.write_bytes(data)
                        converted = subprocess.run([shutil.which("sips"), "-s", "format", "png", str(source_path), "--out", str(png_path)], capture_output=True, text=True, timeout=120, check=False)
                        if converted.returncode == 0 and png_path.exists():
                            data = png_path.read_bytes()
                            suffix = ".png"
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"} and shutil.which("tesseract"):
            with tempfile.TemporaryDirectory() as tmp:
                image_path = Path(tmp) / ("image" + suffix)
                image_path.write_bytes(data)
                result = subprocess.run(["tesseract", str(image_path), "stdout"], capture_output=True, text=True, timeout=120, check=False)
                if result.returncode == 0:
                    return result.stdout, "extracted", None
                return None, "quarantined", "ocr-failed"
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
            ocr_tool = ensure_ocr_tool()
            if ocr_tool:
                with tempfile.TemporaryDirectory() as tmp:
                    image_path = Path(tmp) / ("image" + suffix)
                    image_path.write_bytes(data)
                    result = subprocess.run([str(ocr_tool), str(image_path)], capture_output=True, text=True, timeout=120, check=False)
                    if result.returncode == 0:
                        return result.stdout, "extracted", None
                    return None, "quarantined", f"vision-ocr-failed:{result.stderr[-200:]}"
            return None, "quarantined", "ocr-engine-unavailable"
        return None, "quarantined", "unsupported-or-unidentified-format"
    except Exception as error:
        return None, "quarantined", f"{type(error).__name__}:{str(error)[:200]}"


def encrypted_zip_text(data: bytes, passwords: list[str]) -> tuple[str | None, str | None]:
    """Safely extract an AES-encrypted ZIP with locally available bsdtar and a source-grounded password."""
    bsdtar = shutil.which("bsdtar")
    if not bsdtar:
        return None, "bsdtar-unavailable"
    with tempfile.TemporaryDirectory(prefix="ib-encrypted-zip-") as temporary:
        archive_path = Path(temporary) / "archive.zip"
        output_dir = Path(temporary) / "out"
        archive_path.write_bytes(data)
        for password in passwords:
            listing = subprocess.run([bsdtar, "--passphrase", password, "-tf", str(archive_path)], capture_output=True, text=True, timeout=60, check=False)
            members = [line.strip() for line in listing.stdout.splitlines() if line.strip()]
            if listing.returncode != 0 or not members or any(Path(member).is_absolute() or ".." in Path(member).parts for member in members):
                continue
            output_dir.mkdir(exist_ok=True)
            extraction = subprocess.run([bsdtar, "--passphrase", password, "-xf", str(archive_path), "-C", str(output_dir)], capture_output=True, text=True, timeout=120, check=False)
            if extraction.returncode != 0:
                continue
            parts = ["Archive members:", *members]
            total = 0
            for extracted_path in sorted(path for path in output_dir.rglob("*") if path.is_file()):
                total += extracted_path.stat().st_size
                if total > 100 * 1024 * 1024 or extracted_path.stat().st_size > 20 * 1024 * 1024:
                    return None, "decrypted-archive-too-large"
                text_value, status, _ = safe_attachment_text(extracted_path.name, extracted_path.read_bytes())
                if status == "extracted" and text_value:
                    parts.extend([f"\n--- {extracted_path.name} ---", text_value])
            return "\n".join(parts), None
    return None, "source-password-did-not-decrypt"


_OCR_TOOL: Path | None | bool = False


def ensure_ocr_tool() -> Path | None:
    global _OCR_TOOL
    if _OCR_TOOL is not False:
        return _OCR_TOOL if isinstance(_OCR_TOOL, Path) else None
    compiler = shutil.which("clang")
    source = ROOT / "scripts" / "ocr_image.m"
    binary = ROOT / "tmp" / "ocr_image"
    if not compiler or not source.exists():
        _OCR_TOOL = None
        return None
    binary.parent.mkdir(parents=True, exist_ok=True)
    module_cache = ROOT / "tmp" / "clang-modules"
    module_cache.mkdir(parents=True, exist_ok=True)
    command = [compiler, "-fobjc-arc", "-fblocks", f"-fmodules-cache-path={module_cache}", str(source), "-o", str(binary), "-framework", "Foundation", "-framework", "Vision", "-framework", "ImageIO", "-framework", "CoreGraphics"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    if result.returncode != 0:
        _OCR_TOOL = None
        return None
    _OCR_TOOL = binary
    return binary


def prepare_olm(path: Path, output_dir: Path, source_id: str, attachment_limit: int | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    messages: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    attachments_manifest: list[dict[str, Any]] = []
    attachment_text_dir = output_dir / "attachment-text"
    events: list[dict[str, Any]] = []
    contacts: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        message_infos = [info for info in infos if re.search(r"/message_\d+\.xml$", info.filename)]
        attachment_infos = [info for info in infos if not info.is_dir() and "/com.microsoft.__Attachments/" in info.filename]
        for info in message_infos:
            try:
                messages.append(parse_olm_message(archive.read(info), info.filename, source_id))
            except Exception as error:
                failures.append({"condition": "C3", "sourcePath": info.filename, "error": f"{type(error).__name__}:{error}", "repairAttempt": "xml-standard-parser"})
        if "Local/Calendar/Calendar.xml" in archive.namelist():
            events = parse_calendar(archive.read("Local/Calendar/Calendar.xml"), source_id)
        if "Local/Address Book/Contacts.xml" in archive.namelist():
            contacts = parse_contacts(archive.read("Local/Address Book/Contacts.xml"), source_id)
        attachment_metadata: dict[str, dict[str, Any]] = {}
        for message in messages:
            for metadata in message["attachments"]:
                url = metadata.get("OPFAttachmentURL")
                if url:
                    attachment_metadata[url] = {
                        "originalName": metadata.get("OPFAttachmentName"),
                        "declaredType": metadata.get("OPFAttachmentContentType"),
                        "declaredExtension": metadata.get("OPFAttachmentContentExtension"),
                        "ownerMessagePath": message["sourcePath"],
                        "ownerEligible": message["eligible"],
                    }
        for ordinal, info in enumerate(attachment_infos):
            metadata = attachment_metadata.get(info.filename, {})
            if attachment_limit is not None and ordinal >= attachment_limit:
                attachments_manifest.append({"sourcePath": info.filename, "archiveIndex": ordinal, "status": "deferred", "size": info.file_size, **metadata})
                continue
            try:
                data = archive.read(info)
                digest = sha256_bytes(data)
                guessed_name = metadata.get("originalName") or Path(info.filename).name
                if not Path(guessed_name).suffix and metadata.get("declaredExtension"):
                    guessed_name = f"{guessed_name}.{metadata['declaredExtension'].lstrip('.')}"
                extracted, status, error = safe_attachment_text(guessed_name, data)
                text_path = None
                if extracted:
                    attachment_text_dir.mkdir(parents=True, exist_ok=True)
                    text_path = f"attachment-text/{digest}.txt"
                    candidate = output_dir / text_path
                    if not candidate.exists():
                        candidate.write_text(extracted, encoding="utf-8", errors="replace")
                attachments_manifest.append({"sourcePath": info.filename, "archiveIndex": ordinal, "sha256": digest, "size": info.file_size, "status": status, "error": error, "textPath": text_path, **metadata})
            except Exception as error:
                attachments_manifest.append({"sourcePath": info.filename, "archiveIndex": ordinal, "size": info.file_size, "status": "quarantined", "error": f"{type(error).__name__}:{error}", **metadata})
    write_ndjson(output_dir / "messages.ndjson", messages)
    write_ndjson(output_dir / "calendar-events.ndjson", events)
    write_ndjson(output_dir / "contacts.ndjson", contacts)
    write_ndjson(output_dir / "attachments-manifest.ndjson", attachments_manifest)
    write_ndjson(output_dir / "repair-and-failure-log.ndjson", failures)
    eligible = sum(1 for message in messages if message["eligible"])
    excluded = len(messages) - eligible
    quality = {
        "archiveEntries": len(infos),
        "fileEntries": sum(1 for info in infos if not info.is_dir()),
        "messageXmlCount": len(message_infos),
        "parsedMessages": len(messages),
        "eligibleMessages": eligible,
        "excludedMessages": excluded,
        "messageParseFailures": len(failures),
        "attachmentFileCount": len(attachment_infos),
        "attachmentDispositions": dict(Counter(row["status"] for row in attachments_manifest)),
        "calendarEvents": len(events),
        "contacts": len(contacts),
        "reconciled": len(message_infos) == len(messages) + len(failures) and len(attachment_infos) == len(attachments_manifest),
    }
    json_dump(output_dir / "quality-report.json", quality)
    return quality


def repair_attachments() -> dict[str, Any]:
    manifest_path = ROOT / "Inputs" / "olm" / "attachments-manifest.ndjson"
    quality_path = ROOT / "Inputs" / "olm" / "quality-report.json"
    rows = list(read_ndjson(manifest_path))
    message_by_path = {message["sourcePath"]: message for message in read_ndjson(ROOT / "Inputs" / "olm" / "messages.ndjson")}
    repairs: list[dict[str, Any]] = []
    with zipfile.ZipFile(DEFAULT_OLM) as archive:
        attachment_infos = [info for info in archive.infolist() if not info.is_dir() and "/com.microsoft.__Attachments/" in info.filename]
        if len(attachment_infos) != len(rows):
            raise RuntimeError(f"C0 attachment manifest length mismatch: {len(rows)} != {len(attachment_infos)}")
        for archive_index, (row, info) in enumerate(zip(rows, attachment_infos)):
            row["archiveIndex"] = archive_index
            if row["sourcePath"] != info.filename:
                raise RuntimeError(f"C0 attachment manifest order mismatch at {archive_index}")
            if row["status"] not in {"quarantined", "metadata-only"}:
                continue
            source_path = row["sourcePath"]
            before = {"status": row["status"], "error": row.get("error")}
            try:
                data = archive.read(info)
                name = row.get("originalName") or Path(source_path).name
                passwords: list[str] = []
                owner = message_by_path.get(row.get("ownerMessagePath"), {})
                owner_text = normalize_text((owner.get("bodyText") or "") + " " + (owner.get("bodyHtml") or ""))
                for match in re.finditer(r"(?i)\b(?:archive|arch|zip|file)?\s*(?:password|pass|pwd)\s*[:=\-]?\s*([A-Za-z0-9!@#$%^&*._-]{2,40})", owner_text):
                    if match.group(1) not in passwords:
                        passwords.append(match.group(1))
                if "encrypted" in str(row.get("error", "")).casefold() and passwords and Path(name).suffix.casefold() == ".zip":
                    decrypted_text, decrypt_error = encrypted_zip_text(data, passwords)
                    text_value, status, error = (decrypted_text, "extracted", None) if decrypted_text is not None else (None, "quarantined", decrypt_error)
                else:
                    text_value, status, error = safe_attachment_text(name, data)
                row.update({"status": status, "error": error})
                if text_value is not None:
                    digest = row.get("sha256") or sha256_bytes(data)
                    text_path = f"attachment-text/{digest}.txt"
                    target = ROOT / "Inputs" / "olm" / text_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text_value, encoding="utf-8", errors="replace")
                    row["textPath"] = text_path
            except Exception as error:
                row.update({"status": "quarantined", "error": f"repair:{type(error).__name__}:{error}"})
            repairs.append({"sourcePath": source_path, "before": before, "after": {"status": row["status"], "error": row.get("error")}})
    write_ndjson(manifest_path, rows)
    write_ndjson(ROOT / "Inputs" / "olm" / "attachment-repair-log.ndjson", repairs)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["attachmentDispositions"] = dict(Counter(row["status"] for row in rows))
    json_dump(quality_path, quality)
    return {"attempted": len(repairs), "successful": sum(1 for repair in repairs if repair["after"]["status"] == "extracted"), "remaining": dict(Counter(row["status"] for row in rows))}


def markdown_record(data: dict[str, Any], summary: str = "") -> str:
    frontmatter = json.dumps(data, ensure_ascii=False, indent=2)
    return f"---\n{frontmatter}\n---\n\n# {data.get('displayName') or data.get('name') or data.get('subject') or data.get('title') or data.get('entityId')}\n\n## Summary\n\n{summary}\n\n## Relationships\n\nRelationships are represented in the typed frontmatter and generated relationship index.\n\n## Source Information\n\nSee `sourceRefs` in the frontmatter.\n\n## AI Context\n\nNo unsupported inference is published.\n"


def write_entity(entity_type: str, data: dict[str, Any], summary: str = "") -> Path:
    directory, id_field, _ = ENTITY_CONFIG[entity_type]
    entity_id = data[id_field]
    target = ROOT / "entities" / directory / f"{entity_id}.md"
    record = dict(data)
    if entity_type == "person":
        if target.exists() and ("clayEnhanced" not in record or "ToEnhance" not in record):
            existing = frontmatter(target)
            for field in ("clayEnhanced", "ToEnhance"):
                if field not in record and field in existing:
                    record[field] = existing[field]
        record.setdefault("clayEnhanced", None)
        record.setdefault("ToEnhance", None)
        validate_clay_enhanced_date(record["clayEnhanced"])
        validate_to_enhance(record["ToEnhance"])
    temp = target.with_suffix(".md.tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp.write_text(markdown_record(record, summary), encoding="utf-8")
    temp.replace(target)
    return target


def source_entities(excel: Path, olm: Path, imported_at: str) -> list[dict[str, Any]]:
    values = []
    for source_type, path, expected_hash in [
        ("spreadsheet", excel, EXPECTED_EXCEL_HASH),
        ("olm", olm, EXPECTED_OLM_HASH),
    ]:
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise RuntimeError(f"C0 source hash mismatch for {path}: {actual_hash}")
        source_id = stable_id("source", actual_hash)
        values.append({
            "entityType": "source", "sourceId": source_id, "name": path.name,
            "createdAt": imported_at, "updatedAt": imported_at,
            "sourceType": source_type, "originalFilename": path.name,
            "originalPath": str(path), "rawPath": f"raw/{'spreadsheets' if source_type == 'spreadsheet' else 'olm'}/{path.name}",
            "fileSize": path.stat().st_size, "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if source_type == "spreadsheet" else "application/zip",
            "fileHash": actual_hash, "hashAlgorithm": "SHA-256", "importedAt": imported_at,
            "status": "processed", "securityClassification": "private-customer-data",
            "parserVersion": "wiki-pipeline-1.0", "aliases": [], "tags": ["influential-brands"],
            "sourceRefs": [], "confidence": 1.0,
        })
    return values


def preserve_raw(source: Path, destination: Path, expected_hash: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and sha256_file(destination) == expected_hash:
        return
    temp = destination.with_suffix(destination.suffix + ".tmp")
    if temp.exists():
        temp.unlink()
    shutil.copyfile(source, temp)
    if sha256_file(temp) != expected_hash:
        temp.unlink(missing_ok=True)
        raise RuntimeError(f"C0 copied source hash mismatch: {destination}")
    temp.replace(destination)
    destination.chmod(0o444)


def entity_base(entity_type: str, identity: str, source_refs: list[dict[str, Any]]) -> dict[str, Any]:
    timestamp = canonical_timestamp()
    return {"entityType": entity_type, "createdAt": timestamp, "updatedAt": timestamp, "aliases": [], "tags": [], "status": "active", "confidence": 1.0, "sourceRefs": source_refs}


def is_role_mailbox(address: str) -> bool:
    return address.split("@", 1)[0].replace(".", "").replace("-", "").casefold() in ROLE_PREFIXES


def stratified_sample(rows: list[dict[str, Any]], limit: int, bucket) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(bucket(row))].append(row)
    selected: list[dict[str, Any]] = []
    ordered = [groups[key] for key in sorted(groups)]
    while len(selected) < limit and any(ordered):
        for group in ordered:
            if group and len(selected) < limit:
                selected.append(group.pop(0))
    return selected


def ingest_entities(run: str, limit_excel: int | None = None, limit_messages: int | None = None) -> dict[str, Any]:
    excel_input = ROOT / "Inputs" / "spreadsheets" / "contacts.ndjson"
    olm_input = ROOT / "Inputs" / "olm" / "messages.ndjson"
    event_input = ROOT / "Inputs" / "olm" / "calendar-events.ndjson"
    contact_input = ROOT / "Inputs" / "olm" / "contacts.ndjson"
    sources = {record["sourceType"]: record for record in source_entities(DEFAULT_EXCEL, DEFAULT_OLM, canonical_timestamp())}
    source_excel = sources["spreadsheet"]["sourceId"]
    source_olm = sources["olm"]["sourceId"]
    for source in sources.values():
        write_entity("source", source, f"Immutable registered source: `{source['originalFilename']}`.")
    people_by_email: dict[str, dict[str, Any]] = {}
    organisations_by_domain: dict[str, dict[str, Any]] = {}
    entities: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    review: list[dict[str, Any]] = []

    excel_records = list(read_ndjson(excel_input))
    if limit_excel is not None:
        excel_records = stratified_sample(excel_records, limit_excel, lambda row: f"{row['disposition']}|{','.join(sorted(row['issues']))}|{sum(value is not None for key, value in row.items() if key not in {'raw', 'sourceRef'}) // 4}")
    for row in excel_records:
        if row["disposition"] == "quarantined":
            review.append({"type": "excel-row", "sourceRow": row["sourceRow"], "issues": row["issues"]})
            continue
        ref = row["sourceRef"]
        person = row["person"]
        person_key = person["email"] or person["linkedInUrl"] or f"{person['displayName']}|{row['organisation']}"
        person_id = stable_id("person", person_key)
        existing = people_by_email.get(person["email"]) if person["email"] else None
        if existing:
            existing["sourceRefs"].append(ref)
            existing["aliases"] = sorted(set(existing["aliases"] + [person["displayName"]]))
            existing["mentionCount"] = existing.get("mentionCount", 0) + 1
            person_entity = existing
        else:
            person_entity = entity_base("person", person_key, [ref]) | {
                "personId": person_id, "displayName": person["displayName"] or person["email"],
                "primaryEmail": person["email"], "linkedInUrl": person["linkedInUrl"],
                "firstName": person["firstName"], "lastName": person["lastName"], "mentionCount": 1,
            }
            entities["person"][person_id] = person_entity
            if person["email"]:
                people_by_email[person["email"]] = person_entity
        org_id = None
        if row["organisation"]:
            org_key = normalize_text(row["organisation"]).casefold()
            org_id = stable_id("organisation", org_key)
            org = entities["organisation"].get(org_id)
            if not org:
                org = entity_base("organisation", org_key, [ref]) | {"organisationId": org_id, "name": row["organisation"], "domains": [], "industryIds": [], "locationIds": [], "mentionCount": 0}
                entities["organisation"][org_id] = org
            if person.get("email"):
                domain = person["email"].split("@", 1)[1]
                if domain not in {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com"}:
                    if domain not in org["domains"]:
                        org["domains"].append(domain)
                    organisations_by_domain.setdefault(domain, org)
            org["mentionCount"] += 1
            if ref not in org["sourceRefs"]:
                org["sourceRefs"].append(ref)
        links: dict[str, Any] = {}
        for field, entity_type in [("country", "location"), ("industry", "industry"), ("brandCategory", "industry"), ("brand", "brand"), ("function", "organisational-function"), ("marketingSegment", "marketing-segment")]:
            value = row.get(field)
            if not value:
                continue
            key = normalize_text(value).casefold()
            entity_id = stable_id(entity_type, key)
            directory, id_field, name_field = ENTITY_CONFIG[entity_type]
            if entity_id not in entities[entity_type]:
                extra = {"mentionCount": 0}
                if entity_type == "location": extra["locationType"] = "country"
                if entity_type == "marketing-segment": extra |= {"description": None, "membershipRule": "Imported from Excel EDM to", "memberCount": 0}
                entities[entity_type][entity_id] = entity_base(entity_type, key, [ref]) | {id_field: entity_id, name_field: value} | extra
            target = entities[entity_type][entity_id]
            target["mentionCount"] = target.get("mentionCount", 0) + 1
            links[field + "Id"] = entity_id
            if entity_type == "marketing-segment": target["memberCount"] += 1
        title_values = [value for value in [row.get("designation"), row.get("position")] if value]
        if person_entity and org_id and title_values:
            unique_titles = list(dict.fromkeys(title_values))
            appointment_key = f"{person_entity['personId']}|{org_id}|{'|'.join(value.casefold() for value in unique_titles)}"
            appointment_id = stable_id("appointment", appointment_key)
            entities["appointment"][appointment_id] = entity_base("appointment", appointment_key, [ref]) | {
                "appointmentId": appointment_id, "title": unique_titles[0] if len(unique_titles) == 1 else None,
                "titleObservations": unique_titles, "personId": person_entity["personId"], "organisationId": org_id,
                "functionId": links.get("functionId"), "startDate": None, "endDate": None,
                "status": "unknown" if len(unique_titles) > 1 else "current",
            }
            if len(unique_titles) > 1:
                review.append({"type": "appointment-title-conflict", "appointmentId": appointment_id, "values": unique_titles, "sourceRef": ref})
        person_entity["organisationId"] = org_id
        person_entity.update(links)

    messages = list(read_ndjson(olm_input))
    eligible_messages = [message for message in messages if message["eligible"]]
    if limit_messages is not None:
        eligible_messages = stratified_sample(eligible_messages, limit_messages, lambda message: f"{message['account']}|{message['folder']}|attachments:{bool(message['attachments'])}")
    email_by_id: dict[str, dict[str, Any]] = {}
    duplicate_messages = 0
    for message in eligible_messages:
        key = message["canonicalKey"].strip("<>").casefold()
        message_id = stable_id("email-message", key)
        if message_id in email_by_id:
            duplicate_messages += 1
            email_by_id[message_id]["sourceRefs"].append(message["sourceRef"])
            continue
        participants = []
        for role, values in [("sender", message["from"]), ("to", message["to"]), ("cc", message["cc"]), ("bcc", message["bcc"])]:
            for value in values:
                person_id = people_by_email.get(value["email"], {}).get("personId")
                if not person_id and value.get("name") and not is_role_mailbox(value["email"]):
                    person_id = stable_id("person", value["email"])
                    if person_id not in entities["person"]:
                        candidate = entity_base("person", value["email"], [message["sourceRef"]]) | {"personId": person_id, "displayName": value["name"], "primaryEmail": value["email"], "firstName": None, "lastName": None, "linkedInUrl": None, "mentionCount": 0}
                        entities["person"][person_id] = candidate
                        people_by_email[value["email"]] = candidate
                if person_id:
                    entities["person"][person_id]["mentionCount"] = entities["person"][person_id].get("mentionCount", 0) + 1
                role_mailbox = is_role_mailbox(value["email"])
                organisation_id = None
                if role_mailbox:
                    organisation = organisations_by_domain.get(value["email"].split("@", 1)[1])
                    organisation_id = organisation.get("organisationId") if organisation else None
                participants.append({"role": role, "email": value["email"], "displayName": value.get("name"), "personId": person_id, "organisationId": organisation_id, "roleMailbox": role_mailbox})
        email_entity = entity_base("email-message", key, [message["sourceRef"]]) | {
            "emailMessageId": message_id, "subject": message["subject"], "sentAt": message["sentAt"], "receivedAt": message["receivedAt"],
            "direction": "outbound" if message["account"] in {value["email"] for value in message["from"]} else "inbound",
            "account": message["account"], "folder": message["folder"], "messageId": message["messageId"],
            "threadTopic": message["threadTopic"], "threadIndex": message["threadIndex"], "participants": participants,
            "bodyHash": message["bodyHash"], "inputLocator": f"Inputs/olm/messages.ndjson#{message['sourcePath']}",
            "attachments": message["attachments"], "campaignId": None, "outcomes": [],
        }
        entities["email-message"][message_id] = email_entity
        email_by_id[message_id] = email_entity

    for event in read_ndjson(event_input):
        key = event["uuid"] or f"{event['title']}|{event['startAt']}"
        entity_id = stable_id("meeting-event", key)
        entities["meeting-event"][entity_id] = entity_base("meeting-event", key, [event["sourceRef"]]) | {
            "meetingEventId": entity_id, "title": event["title"], "eventType": "meeting",
            "startAt": event["startAt"], "endAt": event["endAt"], "location": event["location"],
            "organiser": None, "participants": event["attendees"], "outcomes": [],
        }
    for contact in read_ndjson(contact_input):
        email_value = contact["emails"][0] if contact["emails"] else None
        if not email_value or email_value in people_by_email:
            continue
        entity_id = stable_id("person", email_value)
        entity = entity_base("person", email_value, [contact["sourceRef"]]) | {"personId": entity_id, "displayName": contact["displayName"] or email_value, "primaryEmail": email_value, "firstName": contact["firstName"], "lastName": None, "linkedInUrl": None, "mentionCount": 1}
        entities["person"][entity_id] = entity
        people_by_email[email_value] = entity

    for entity_type, records in entities.items():
        for record in records.values():
            _, _, name_field = ENTITY_CONFIG[entity_type]
            write_entity(entity_type, record, f"Canonical {entity_type.replace('-', ' ')} record for {record.get(name_field) or record.get('displayName') or record.get('subject') or record.get('title')}.")
    run_dir = ROOT / "runs" / run
    write_ndjson(run_dir / "review-queue.ndjson", review)
    counts = {entity_type: len(records) for entity_type, records in entities.items()}
    counts["source"] = len(sources)
    result = {"runId": run, "entityCounts": counts, "reviewItems": len(review), "eligibleMessagesProcessed": len(eligible_messages), "canonicalEmailMessages": len(entities["email-message"]), "duplicateMessageOccurrences": duplicate_messages, "emailReconciled": len(eligible_messages) == len(entities["email-message"]) + duplicate_messages}
    json_dump(run_dir / "ingestion-summary.json", result)
    return result


def semantic_extract(run: str, limit: int | None = None) -> dict[str, Any]:
    """Screen every eligible message, analyse representative threads in batches, and publish only evidence-gated semantics."""
    command_text = os.environ.get("IB_LLM_COMMAND")
    model = os.environ.get("IB_LLM_MODEL")
    provider = os.environ.get("IB_LLM_PROVIDER")
    if not command_text or not model or not provider:
        raise RuntimeError("C0 cloud semantic extraction requires IB_LLM_COMMAND, IB_LLM_MODEL and IB_LLM_PROVIDER")
    command = shlex.split(command_text)
    if limit is None:
        reset_semantic_state()
    messages = [message for message in read_ndjson(ROOT / "Inputs" / "olm" / "messages.ndjson") if message["eligible"]]
    if limit is not None:
        messages = messages[:limit]
    run_dir = ROOT / "runs" / run
    accepted: list[dict[str, Any]] = []
    accepted_outcomes: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    allowed = {"marketing-campaign", "product-service", "project-initiative", "sales-opportunity", "topic"}
    automated = re.compile(r"(?i)^(read:|return receipt|mail delivery failed|delivery status notification|undelivered mail|returned mail|automatic reply|out of office)")

    def thread_key(subject: str) -> str:
        value = re.sub(r"(?i)^\s*((re|fw|fwd|aw)\s*(\(\d+\))?\s*:\s*)+", "", subject or "")
        return normalize_text(value).casefold()

    threads: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for message in messages:
        threads[thread_key(message.get("subject") or "")].append(message)

    model_items: list[dict[str, Any]] = []
    screened_out = 0
    content_by_locator: dict[str, str] = {}
    for key, thread_messages in sorted(threads.items(), key=lambda item: (-len(item[1]), item[0])):
        subject = normalize_text(thread_messages[0].get("subject"))
        if not subject or automated.search(key):
            screened_out += len(thread_messages)
            continue
        candidates = []
        for message in thread_messages:
            body = message.get("bodyText") or re.sub(r"<[^>]+>", " ", message.get("bodyHtml") or "")
            body = normalize_text(html.unescape(body))
            candidates.append((len(body), message, body))
        _, representative, body = max(candidates, key=lambda value: value[0])
        # Subjects carry most named campaign/product context. A bounded body excerpt adds explicit actions and decisions.
        content = body[:900]
        source_content = subject + "\n" + content
        content_by_locator[representative["sourcePath"]] = source_content
        model_items.append({
            "sourceLocator": representative["sourcePath"],
            "threadMessageCount": len(thread_messages),
            "subject": subject,
            "content": content,
        })

    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    max_chars = int(os.environ.get("IB_SEMANTIC_BATCH_CHARS", "600000"))
    max_items = int(os.environ.get("IB_SEMANTIC_BATCH_ITEMS", "650"))
    for item in model_items:
        item_chars = len(item["subject"]) + len(item["content"])
        if current and (current_chars + item_chars > max_chars or len(current) >= max_items):
            batches.append(current)
            current, current_chars = [], 0
        current.append(item)
        current_chars += item_chars
    if current:
        batches.append(current)

    batch_receipts: list[dict[str, Any]] = []
    cache_dir = run_dir / "semantic-batches"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for batch_number, batch in enumerate(batches, 1):
        request = {
            "task": "Extract only explicit business entities and outcomes with exact evidence text.",
            "allowedEntityTypes": sorted(allowed),
            "allowedOutcomeTypes": ["action", "commitment", "business-decision"],
            "items": batch,
        }
        request_hash = sha256_bytes(json.dumps(request, ensure_ascii=False, sort_keys=True).encode())
        cache_path = cache_dir / f"batch-{batch_number:04d}-{request_hash[:12]}.json"
        if cache_path.exists():
            response = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = True
        else:
            process = subprocess.run(command, input=json.dumps(request, ensure_ascii=False), capture_output=True, text=True, timeout=1500, check=False)
            if process.returncode != 0:
                review.append({"type": "semantic-batch-failure", "batch": batch_number, "itemCount": len(batch), "requestHash": request_hash, "error": (process.stderr or process.stdout)[-2000:]})
                batch_receipts.append({"batch": batch_number, "itemCount": len(batch), "requestHash": request_hash, "passed": False})
                json_dump(run_dir / "semantic-progress.json", {"completedBatches": batch_receipts})
                continue
            try:
                response = json.loads(process.stdout.strip().splitlines()[-1])
            except Exception as error:
                review.append({"type": "semantic-invalid-json", "batch": batch_number, "requestHash": request_hash, "error": str(error)})
                batch_receipts.append({"batch": batch_number, "itemCount": len(batch), "requestHash": request_hash, "passed": False})
                json_dump(run_dir / "semantic-progress.json", {"completedBatches": batch_receipts})
                continue
            json_dump(cache_path, response)
            cached = False
        batch_receipts.append({"batch": batch_number, "itemCount": len(batch), "requestHash": request_hash, "passed": True, "cached": cached, "results": len(response.get("results", []))})
        json_dump(run_dir / "semantic-progress.json", {"completedBatches": batch_receipts})
        for result in response.get("results", []):
            locator = result.get("sourceLocator", "")
            source_content = content_by_locator.get(locator, "")
            ref = source_ref(stable_id("source", EXPECTED_OLM_HASH), locator, "cloud-llm")
            for candidate in result.get("candidates", []):
                evidence = normalize_text(candidate.get("evidenceText"))
                confidence = float(candidate.get("confidence", 0))
                name = normalize_text(candidate.get("name"))
                valid = candidate.get("entityType") in allowed and name and name.casefold() in source_content.casefold() and evidence and evidence in source_content and confidence >= 0.90
                enriched = candidate | {"sourceRef": ref, "evidenceHash": sha256_bytes(evidence.encode()) if evidence else None, "provider": provider, "model": model, "runId": run}
                (accepted if valid else review).append(enriched if valid else {"type": "semantic-candidate-rejected", "candidate": enriched})
            for outcome in result.get("outcomes", []):
                evidence = normalize_text(outcome.get("evidenceText"))
                confidence = float(outcome.get("confidence", 0))
                marker_patterns = {
                    "action": r"(?i)\b(please|could you|can you|need to|needs to|action item|follow up|follow-up|required|kindly)\b",
                    "commitment": r"(?i)\b(i|we)\s+(will|shall|commit|agree to)\b",
                    "business-decision": r"(?i)\b(approved|agreed|decided|confirmed|selected|accepted|rejected|decline|declined)\b",
                }
                outcome_type = outcome.get("outcomeType")
                valid = outcome_type in marker_patterns and evidence and evidence in source_content and confidence >= 0.90 and re.search(marker_patterns[outcome_type], evidence)
                enriched = outcome | {"description": evidence, "sourceRef": ref, "evidenceHash": sha256_bytes(evidence.encode()) if evidence else None, "provider": provider, "model": model, "runId": run}
                (accepted_outcomes if valid else review).append(enriched if valid else {"type": "semantic-outcome-rejected", "outcome": enriched})
    write_ndjson(run_dir / "semantic-candidates.ndjson", accepted)
    write_ndjson(run_dir / "semantic-outcomes.ndjson", accepted_outcomes)
    write_ndjson(run_dir / "semantic-review.ndjson", review)
    published = publish_semantic_candidates(run, accepted, accepted_outcomes)
    summary = {"runId": run, "provider": provider, "model": model, "messagesAttempted": len(messages), "messagesScreened": len(messages), "threadsScreened": len(threads), "threadsSentToModel": len(model_items), "messagesScreenedOutAsAutomated": screened_out, "modelBatches": batch_receipts, "acceptedCandidates": len(accepted), "acceptedOutcomes": len(accepted_outcomes), "publishedEntities": published["publishedEntities"], "publishedOutcomes": published["publishedOutcomes"], "reviewItems": len(review), "evidenceCoverage": 1.0 if accepted or accepted_outcomes else None}
    json_dump(run_dir / "semantic-summary.json", summary)
    return summary


def reset_semantic_state() -> None:
    """Remove generated semantic records and outcomes before a complete, repeatable semantic run."""
    for entity_type in {"marketing-campaign", "product-service", "project-initiative", "sales-opportunity", "topic"}:
        directory = ROOT / "entities" / ENTITY_CONFIG[entity_type][0]
        for path in directory.glob("*.md"):
            if path.name not in SYSTEM_FILES:
                path.unlink()
    for path in (ROOT / "entities" / "email-messages").glob("*.md"):
        if path.name in SYSTEM_FILES:
            continue
        data = frontmatter(path)
        if data.get("outcomes"):
            data["outcomes"] = []
            path.write_text(markdown_record(data, "Canonical email record; semantic outcomes are rebuilt by the approved full extraction run."), encoding="utf-8")


def publish_semantic_candidates(run: str, candidates: list[dict[str, Any]], outcomes: list[dict[str, Any]] | None = None) -> dict[str, int]:
    conditional_types = {"marketing-campaign", "product-service", "project-initiative", "sales-opportunity", "topic"}
    generic_topics = {"draft article", "graphs", "incoming feedback", "linkedin", "monday", "my first heatmap", "performance tab", "standard terms of use", "user behavior", "video brief"}

    def canonical_semantic_name(entity_type: str, value: Any) -> str:
        name = normalize_text(value).replace("’", "'")
        name = re.sub(r"(?i)\bSocial\s*Media\s*Contest\b", "Social Media Contest", name)
        if entity_type == "product-service":
            name = re.sub(r"(?i)\bTop Employers Award\b", "Top Employer Awards", name)
            name = re.sub(r"(?i)\bTop Employer Award\b", "Top Employer Awards", name)
        return normalize_text(name)
    email_by_locator: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in (ROOT / "entities" / "email-messages").glob("*.md"):
        if path.name in SYSTEM_FILES:
            continue
        try:
            data = frontmatter(path)
            for ref in data.get("sourceRefs", []):
                email_by_locator[ref.get("locator", "")] = (path, data)
        except Exception:
            continue
    published_entities = 0
    published_outcomes = 0
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in candidates:
        entity_type = candidate.get("entityType")
        name = canonical_semantic_name(entity_type, candidate.get("name"))
        if entity_type not in conditional_types or not name:
            continue
        if entity_type == "topic" and name.casefold() in generic_topics:
            continue
        candidate = candidate | {"name": name}
        key = (entity_type, name.casefold())
        if key not in grouped:
            grouped[key] = candidate | {"sourceRefs": [candidate["sourceRef"]], "evidenceHashes": [candidate["evidenceHash"]]}
        else:
            if candidate["sourceRef"] not in grouped[key]["sourceRefs"]:
                grouped[key]["sourceRefs"].append(candidate["sourceRef"])
            if candidate["evidenceHash"] not in grouped[key]["evidenceHashes"]:
                grouped[key]["evidenceHashes"].append(candidate["evidenceHash"])
    for candidate in grouped.values():
        entity_type = candidate["entityType"]
        name = canonical_semantic_name(entity_type, candidate["name"])
        _, id_field, name_field = ENTITY_CONFIG[entity_type]
        entity_id = stable_id(entity_type, name)
        ref = candidate["sourceRef"]
        data = entity_base(entity_type, name, candidate["sourceRefs"]) | {id_field: entity_id, name_field: name}
        reserved = {"entityType", id_field, name_field, "createdAt", "updatedAt", "sourceRefs", "confidence", "aliases", "tags"}
        for key, value in candidate.get("attributes", {}).items():
            if key not in reserved:
                data[key] = value
        data["confidence"] = float(candidate["confidence"])
        data["extraction"] = {"provider": candidate["provider"], "model": candidate["model"], "runId": run, "evidenceHashes": candidate["evidenceHashes"]}
        data["relationships"] = [relationship for relationship in candidate.get("relationships", []) if isinstance(relationship, dict) and relationship.get("toId")]
        write_entity(entity_type, data, f"Source-grounded semantic entity extracted with confidence {data['confidence']:.2f}.")
        published_entities += 1
    for outcome in outcomes or []:
        ref = outcome["sourceRef"]
        locator = ref["locator"]
        if locator in email_by_locator:
            path, email_data = email_by_locator[locator]
            existing = email_data.setdefault("outcomes", [])
            record = {
                "outcomeType": outcome["outcomeType"], "description": normalize_text(outcome["description"]),
                "ownerId": None, "dueAt": None, "status": "unknown", "sourceRef": ref,
                "evidenceHash": outcome["evidenceHash"], "confidence": outcome["confidence"],
            }
            if record not in existing:
                existing.append(record)
                published_outcomes += 1
            path.write_text(markdown_record(email_data, f"Canonical email record with {len(existing)} source-grounded business outcomes."), encoding="utf-8")
    return {"publishedEntities": published_entities, "publishedOutcomes": published_outcomes}


def generate_schemas_and_indexes() -> None:
    decision = ROOT / "entities" / "decisions" / "2026-08-08-initial-production-schemas.md"
    if not decision.exists():
        decision.write_text("""---
{"decisionId":"decision-initial-production-schemas-2026-08-08","title":"Approve initial production schemas and ingestion controls","status":"accepted","date":"2026-08-08","affects":["schemas","entity templates","source references","ingestion","privacy"],"aliases":[],"tags":["governance","production-readiness"]}
---

# Approve initial production schemas and ingestion controls

## Decision

Accept the production schemas, typed relationship model, confidence gate, immutable-source policy, deterministic repair protocol and privacy controls defined by the approved Influential Brands ingestion plan.

## Rationale

Production ingestion requires complete templates, machine validation, source traceability and repeatable repair behaviour.
""", encoding="utf-8")
    common = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["entityType", "createdAt", "updatedAt", "aliases", "tags", "confidence", "sourceRefs"],
        "properties": {
            "entityType": {"type": "string"}, "createdAt": {"type": "string"}, "updatedAt": {"type": "string"},
            "aliases": {"type": "array", "items": {"type": "string"}}, "tags": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "sourceRefs": {"type": "array", "items": {"type": "object", "required": ["sourceId", "locator", "method", "evidenceHash"]}},
        },
    }
    schema_dir = ROOT / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    json_dump(schema_dir / "common-record.schema.json", common)
    for entity_type, (_, id_field, name_field) in ENTITY_CONFIG.items():
        schema = json.loads(json.dumps(common))
        schema["title"] = entity_type
        schema["required"] += [id_field, name_field]
        schema["properties"]["entityType"] = {"const": entity_type}
        schema["properties"][id_field] = {"type": "string", "minLength": 1}
        schema["properties"][name_field] = {"type": ["string", "null"]}
        if entity_type == "person":
            schema["properties"]["clayEnhanced"] = clay_enhanced_schema()
            schema["properties"]["ToEnhance"] = to_enhance_schema()
            schema["required"].append("clayEnhanced")
            schema["required"].append("ToEnhance")
        json_dump(schema_dir / f"{entity_type}.schema.json", schema)
    json_dump(schema_dir / "relationship.schema.json", {"type": "object", "required": ["fromId", "relationshipType", "toId", "sourceRefs"], "properties": {"fromId": {"type": "string"}, "relationshipType": {"type": "string"}, "toId": {"type": "string"}, "sourceRefs": common["properties"]["sourceRefs"]}})
    json_dump(schema_dir / "outcome.schema.json", {"type": "object", "required": ["outcomeType", "description", "sourceRef"], "properties": {"outcomeType": {"enum": ["action", "commitment", "business-decision"]}, "description": {"type": "string"}, "sourceRef": {"type": "object"}}})
    registry = """## Production record requirements

All canonical records must contain the approved type-specific ID and name fields plus `createdAt`, `updatedAt`, `status`, `aliases`, `tags`, `confidence`, and `sourceRefs`. Relationships are typed fields compiled into the generated query index. The machine-readable schema under `schemas/` is authoritative.

## Record template

```md
---
{\"entityType\":\"<type>\",\"<idField>\":\"<stable-id>\",\"<nameField>\":\"<name>\",\"createdAt\":\"<SGT timestamp>\",\"updatedAt\":\"<SGT timestamp>\",\"status\":\"active\",\"aliases\":[],\"tags\":[],\"confidence\":1.0,\"sourceRefs\":[]}
---

## Summary

## Relationships

## Source Information

## AI Context
```
"""
    for entity_type, (directory, id_field, name_field) in ENTITY_CONFIG.items():
        index_path = ROOT / "entities" / directory / "index.md"
        text = index_path.read_text(encoding="utf-8")
        entity_registry = registry.replace("<type>", entity_type).replace("<idField>", id_field).replace("<nameField>", name_field)
        if entity_type == "person":
            entity_registry = entity_registry.replace(
                "Relationships are typed fields compiled into the generated query index.",
                "Every Person record must contain `clayEnhanced`: use the latest verified successful Clay enhancement date in `YYYY-MM-DD` format, or `null` when no verified enhancement is recorded. Every Person record must also contain `ToEnhance`: use `true` when its notes require enhancement, `false` when assessed and clear, and `null` when not yet assessed. `ToEnhance` and `clayEnhanced` are independent. Relationships are typed fields compiled into the generated query index.",
            ).replace(
                '\"updatedAt\":\"<SGT timestamp>\",\"status\":\"active\"',
                '\"updatedAt\":\"<SGT timestamp>\",\"clayEnhanced\":null,\"ToEnhance\":null,\"status\":\"active\"',
            )
        text = re.sub(
            r"## (?:Preliminary field registry|Production record requirements).*?(?=## System files)",
            entity_registry + "\n",
            text,
            flags=re.S,
        )
        text = text.replace("last_updated: 2026-08-07", "last_updated: 2026-08-08")
        index_path.write_text(text, encoding="utf-8")
    for directory, subtype, id_field, name_field in [
        ("decisions", "governance-decision", "decisionId", "title"),
        ("search", "query", "queryId", "query"),
    ]:
        index_path = ROOT / "entities" / directory / "index.md"
        text = index_path.read_text(encoding="utf-8")
        operational_registry = registry.replace("<type>", subtype).replace("<idField>", id_field).replace("<nameField>", name_field)
        text = re.sub(r"## Preliminary field registry.*?(?=## System files)", operational_registry + "\n", text, flags=re.S)
        text = text.replace("last_updated: 2026-08-07", "last_updated: 2026-08-08")
        index_path.write_text(text, encoding="utf-8")
    gitignore = ROOT / ".gitignore"
    gitignore.write_text(""".DS_Store
.env
.env.*
!.env.example
node_modules/
.pytest_cache/
**/__pycache__/
*.pyc
build/
dist/
Inputs/**
raw/**
index/**
runs/**
tmp/**
entities/*/*.md
!entities/*/index.md
!entities/*/catalog.md
!entities/*/log.md
!entities/decisions/*.md
""", encoding="utf-8")
    master = ["# Influential Brands Wiki Index", "", "Canonical domains:", ""]
    for entity_type, (directory, _, _) in ENTITY_CONFIG.items():
        master.append(f"- [{entity_type.replace('-', ' ').title()}](entities/{directory}/catalog.md)")
    master += ["", "Operational domains:", "", "- [Search](entities/search/catalog.md)", "- [Governance Decisions](entities/decisions/catalog.md)", "", "Generated query assets live under `index/`; ingestion receipts live under `runs/`."]
    (ROOT / "index.md").write_text("\n".join(master) + "\n", encoding="utf-8")


def frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\s*\n(.*?)\n---", text, flags=re.S)
    if not match:
        raise ValueError("missing-frontmatter")
    return json.loads(match.group(1))


def rebuild() -> dict[str, Any]:
    index_dir = ROOT / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    # Build the SQLite index on local scratch storage, not directly inside the
    # cloud-synced Wiki folder: sync clients and network mounts break SQLite
    # file locking ("disk I/O error") and can capture half-written databases.
    # Override the scratch location with WIKI_TMPDIR when needed.
    scratch = Path(os.environ.get("WIKI_TMPDIR") or tempfile.gettempdir())
    scratch.mkdir(parents=True, exist_ok=True)
    db_temp = scratch / "influential-brands-wiki.sqlite.tmp"
    db_temp.unlink(missing_ok=True)
    connection = sqlite3.connect(db_temp)
    connection.executescript("""
    CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT, path TEXT NOT NULL, data_json TEXT NOT NULL);
    CREATE TABLE aliases (entity_id TEXT, alias TEXT);
    CREATE TABLE email_addresses (entity_id TEXT, email TEXT);
    CREATE TABLE relationships (from_id TEXT, relationship_type TEXT, to_id TEXT, role TEXT, status TEXT, source_id TEXT, locator TEXT);
    CREATE TABLE source_refs (entity_id TEXT, source_id TEXT, locator TEXT, evidence_hash TEXT);
    CREATE TABLE business_outcomes (entity_id TEXT, outcome_type TEXT, description TEXT, owner_id TEXT, due_at TEXT, status TEXT, source_id TEXT, locator TEXT);
    CREATE VIRTUAL TABLE fulltext USING fts5(entity_id, entity_type, name, content);
    """)
    counts: Counter[str] = Counter()
    entity_ids: set[str] = set()
    pending_relationships: list[tuple[Any, ...]] = []
    catalogs: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for entity_type, (directory, id_field, name_field) in ENTITY_CONFIG.items():
        domain_dir = ROOT / "entities" / directory
        for path in sorted(domain_dir.glob("*.md")):
            if path.name in SYSTEM_FILES:
                continue
            try:
                data = frontmatter(path)
            except Exception:
                if directory == "decisions":
                    continue
                raise
            entity_id = data.get(id_field)
            if not entity_id:
                continue
            name = data.get(name_field) or data.get("displayName") or ""
            relative = str(path.relative_to(ROOT))
            entity_ids.add(entity_id)
            counts[entity_type] += 1
            catalogs[directory].append((entity_id, name, relative))
            connection.execute("INSERT INTO entities VALUES (?,?,?,?,?)", (entity_id, entity_type, name, relative, json.dumps(data, ensure_ascii=False)))
            connection.execute("INSERT INTO fulltext VALUES (?,?,?,?)", (entity_id, entity_type, name, path.read_text(encoding="utf-8")[:1000000]))
            for alias in data.get("aliases", []):
                connection.execute("INSERT INTO aliases VALUES (?,?)", (entity_id, alias))
            if data.get("primaryEmail"):
                connection.execute("INSERT INTO email_addresses VALUES (?,?)", (entity_id, data["primaryEmail"]))
            for ref in data.get("sourceRefs", []):
                connection.execute("INSERT INTO source_refs VALUES (?,?,?,?)", (entity_id, ref.get("sourceId"), ref.get("locator"), ref.get("evidenceHash")))
            for key, value in data.items():
                if key in RELATIONSHIP_ID_FIELDS and key != id_field and isinstance(value, str):
                    pending_relationships.append((entity_id, key[:-2], value, None, data.get("status"), None, None))
            for participant in data.get("participants", []):
                if participant.get("personId"):
                    pending_relationships.append((entity_id, "participant", participant["personId"], participant.get("role"), participant.get("status"), None, None))
            for outcome in data.get("outcomes", []):
                ref = outcome.get("sourceRef", {})
                connection.execute("INSERT INTO business_outcomes VALUES (?,?,?,?,?,?,?,?)", (entity_id, outcome.get("outcomeType"), outcome.get("description"), outcome.get("ownerId"), outcome.get("dueAt"), outcome.get("status"), ref.get("sourceId"), ref.get("locator")))
    for directory, id_field, name_field in [("decisions", "decisionId", "title"), ("search", "queryId", "query")]:
        for path in sorted((ROOT / "entities" / directory).glob("*.md")):
            if path.name in SYSTEM_FILES:
                continue
            try:
                data = frontmatter(path)
            except Exception:
                continue
            if data.get(id_field):
                catalogs[directory].append((data[id_field], data.get(name_field, ""), str(path.relative_to(ROOT))))
    broken: list[dict[str, str]] = []
    for relationship in pending_relationships:
        if relationship[2] not in entity_ids:
            broken.append({"fromId": relationship[0], "relationshipType": relationship[1], "toId": relationship[2]})
        else:
            connection.execute("INSERT INTO relationships VALUES (?,?,?,?,?,?,?)", relationship)
    connection.commit()
    connection.close()
    if broken:
        json_dump(index_dir / "broken-relationships.json", broken)
        db_temp.unlink(missing_ok=True)
        raise RuntimeError(f"C0 broken relationships: {len(broken)}")
    (index_dir / "broken-relationships.json").unlink(missing_ok=True)
    # shutil.move, not Path.replace: the scratch dir may be on another filesystem.
    shutil.move(str(db_temp), str(index_dir / "wiki.sqlite"))
    for directory, rows in catalogs.items():
        catalog = ROOT / "entities" / directory / "catalog.md"
        body = ["---", "type: generated-catalog", f"domain: {directory}", f"generatedAt: {now_sgt()}", f"recordCount: {len(rows)}", "---", "", f"# {directory.replace('-', ' ').title()} Catalog", "", "| ID | Name | File |", "|---|---|---|"]
        pipe_escape = "\\|"
        body.extend(f"| {entity_id} | {name.replace('|', pipe_escape)} | [{Path(path).name}](./{Path(path).name}) |" for entity_id, name, path in rows)
        catalog.write_text("\n".join(body) + "\n", encoding="utf-8")
    result = {"entityCounts": dict(counts), "totalEntities": sum(counts.values()), "brokenRelationships": len(broken)}
    json_dump(index_dir / "summary.json", result)
    return result


def validate(scope: str = "all") -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    if scope in {"scaffold", "all"}:
        expected_domains = {config[0] for config in ENTITY_CONFIG.values()} | {"decisions", "search"}
        actual_domains = {path.name for path in (ROOT / "entities").iterdir() if path.is_dir()}
        if actual_domains != expected_domains:
            errors.append({"condition": "C0", "error": "domain-set-mismatch", "missing": sorted(expected_domains - actual_domains), "unexpected": sorted(actual_domains - expected_domains)})
        for domain in sorted(expected_domains):
            domain_dir = ROOT / "entities" / domain
            for system_file in SYSTEM_FILES:
                if not (domain_dir / system_file).exists():
                    errors.append({"condition": "C0", "path": str(domain_dir / system_file), "error": "missing-system-file"})
            index_path = domain_dir / "index.md"
            if index_path.exists() and "Preliminary field registry" in index_path.read_text(encoding="utf-8"):
                errors.append({"condition": "C0", "path": str(index_path), "error": "preliminary-schema-remains"})
        expected_schemas = {f"{entity_type}.schema.json" for entity_type in ENTITY_CONFIG} | {"common-record.schema.json", "relationship.schema.json", "outcome.schema.json"}
        actual_schemas = {path.name for path in (ROOT / "schemas").glob("*.json")}
        if expected_schemas - actual_schemas:
            errors.append({"condition": "C0", "error": "missing-schemas", "missing": sorted(expected_schemas - actual_schemas)})
        ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for private_pattern in ["Inputs/**", "raw/**", "index/**", "runs/**", "tmp/**", "entities/*/*.md"]:
            if private_pattern not in ignore_text:
                errors.append({"condition": "C0", "path": str(ROOT / ".gitignore"), "error": f"missing-private-ignore:{private_pattern}"})
        if not (ROOT / "entities" / "decisions" / "2026-08-08-initial-production-schemas.md").exists():
            errors.append({"condition": "C0", "error": "missing-accepted-schema-decision"})
    if scope in {"inputs", "all"}:
        input_reports = [ROOT / "Inputs" / "spreadsheets" / "quality-report.json", ROOT / "Inputs" / "olm" / "quality-report.json"]
        loaded_reports: dict[str, dict[str, Any]] = {}
        for path in input_reports:
            if not path.exists():
                errors.append({"condition": "C0", "path": str(path), "error": "missing-quality-report"})
                continue
            report = json.loads(path.read_text())
            loaded_reports[path.parent.name] = report
            if not report.get("reconciled"):
                errors.append({"condition": "C0", "path": str(path), "error": "source-counts-not-reconciled"})
        spreadsheet_report = loaded_reports.get("spreadsheets")
        if spreadsheet_report and spreadsheet_report.get("sourceRows") != EXPECTED_EXCEL_ROWS:
            errors.append({"condition": "C0", "error": "excel-row-count-mismatch", "expected": EXPECTED_EXCEL_ROWS, "actual": spreadsheet_report.get("sourceRows")})
        olm_report = loaded_reports.get("olm")
        if olm_report:
            expected_values = {
                "messageXmlCount": EXPECTED_OLM_MESSAGES,
                "eligibleMessages": EXPECTED_ELIGIBLE_MESSAGES,
                "excludedMessages": EXPECTED_EXCLUDED_MESSAGES,
                "attachmentFileCount": EXPECTED_OLM_ATTACHMENTS,
                "calendarEvents": EXPECTED_OLM_EVENTS,
                "contacts": EXPECTED_OLM_CONTACTS,
            }
            for key, expected in expected_values.items():
                if olm_report.get(key) != expected:
                    errors.append({"condition": "C0", "error": f"olm-{key}-mismatch", "expected": expected, "actual": olm_report.get(key)})
            if olm_report.get("messageParseFailures") != 0:
                errors.append({"condition": "C0", "error": "olm-message-parse-failures", "count": olm_report.get("messageParseFailures")})
            deferred = olm_report.get("attachmentDispositions", {}).get("deferred", 0)
            if deferred:
                errors.append({"condition": "C0", "error": "deferred-attachments-remain", "count": deferred})
    if scope in {"entities", "all"}:
        ids: dict[str, str] = {}
        source_ids: set[str] = set()
        for entity_type, (directory, id_field, name_field) in ENTITY_CONFIG.items():
            for path in (ROOT / "entities" / directory).glob("*.md"):
                if path.name in SYSTEM_FILES:
                    continue
                if directory == "decisions":
                    continue
                try:
                    data = frontmatter(path)
                    entity_id = data[id_field]
                    if data.get("entityType") != entity_type:
                        raise ValueError("entity-type-mismatch")
                    if entity_id in ids:
                        raise ValueError(f"duplicate-id:{ids[entity_id]}")
                    ids[entity_id] = str(path)
                    counts[entity_type] += 1
                    if entity_type == "source":
                        source_ids.add(entity_id)
                    if entity_type != "source" and not data.get("sourceRefs"):
                        raise ValueError("missing-sourceRefs")
                    if entity_type == "person" and "clayEnhanced" in data:
                        validate_clay_enhanced_date(data["clayEnhanced"])
                    if entity_type == "person":
                        if "clayEnhanced" not in data:
                            raise ValueError("missing-clayEnhanced")
                        if "ToEnhance" not in data:
                            raise ValueError("missing-ToEnhance")
                        validate_to_enhance(data["ToEnhance"])
                    try:
                        from jsonschema import Draft202012Validator, FormatChecker
                        schema = json.loads((ROOT / "schemas" / f"{entity_type}.schema.json").read_text(encoding="utf-8"))
                        schema_errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data))
                        if schema_errors:
                            raise ValueError(f"schema:{schema_errors[0].message}")
                    except ImportError:
                        raise ValueError("jsonschema-validator-unavailable")
                except Exception as error:
                    errors.append({"condition": "C0", "path": str(path), "error": str(error)})
        for entity_type, (directory, id_field, name_field) in ENTITY_CONFIG.items():
            for path in (ROOT / "entities" / directory).glob("*.md"):
                if path.name in SYSTEM_FILES or directory == "decisions":
                    continue
                try:
                    data = frontmatter(path)
                    for ref in data.get("sourceRefs", []):
                        if ref.get("sourceId") not in source_ids:
                            errors.append({"condition": "C0", "path": str(path), "error": "broken-source-reference", "sourceId": ref.get("sourceId")})
                except Exception:
                    pass
    if scope in {"index", "all"}:
        database = ROOT / "index" / "wiki.sqlite"
        if not database.exists():
            errors.append({"condition": "C0", "path": str(database), "error": "missing-index"})
        else:
            connection = sqlite3.connect(database)
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            broken = connection.execute("SELECT COUNT(*) FROM relationships r LEFT JOIN entities e ON r.to_id=e.id WHERE e.id IS NULL").fetchone()[0]
            connection.close()
            if integrity != "ok" or broken:
                errors.append({"condition": "C0", "error": "index-integrity", "detail": integrity, "brokenRelationships": broken})
    result = {"scope": scope, "passed": not errors, "errors": errors, "warnings": warnings, "entityCounts": dict(counts), "checkedAt": now_sgt()}
    return result


def query(text: str, limit: int = 10) -> list[dict[str, Any]]:
    database = ROOT / "index" / "wiki.sqlite"
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute("SELECT e.id,e.type,e.name,e.path,bm25(fulltext) score FROM fulltext JOIN entities e ON e.id=fulltext.entity_id WHERE fulltext MATCH ? ORDER BY score LIMIT ?", (text, limit)).fetchall()
    except sqlite3.OperationalError:
        pattern = f"%{text}%"
        rows = connection.execute("SELECT id,type,name,path,0 score FROM entities WHERE name LIKE ? LIMIT ?", (pattern, limit)).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def audit(run: str) -> dict[str, Any]:
    validation = validate("all")
    query_tests = {}
    started = dt.datetime.now().timestamp()
    for label, value in {"person": "Tan", "campaign": "campaign", "brand": "brand", "commitment": "commitment", "organisation": "company"}.items():
        query_tests[label] = query(value, 5)
    elapsed = dt.datetime.now().timestamp() - started
    semantic_path = ROOT / "runs" / run / "semantic-summary.json"
    semantic = json.loads(semantic_path.read_text()) if semantic_path.exists() else None
    semantic_complete = bool(
        semantic
        and semantic.get("messagesAttempted") == EXPECTED_ELIGIBLE_MESSAGES
        and semantic.get("messagesScreened") == EXPECTED_ELIGIBLE_MESSAGES
        and semantic.get("threadsSentToModel", 0) > 0
        and all(batch.get("passed") for batch in semantic.get("modelBatches", []))
        and semantic.get("evidenceCoverage") == 1.0
    )
    database = ROOT / "index" / "wiki.sqlite"
    operational: dict[str, Any] = {}
    if database.exists():
        connection = sqlite3.connect(database)
        operational = {
            "databaseIntegrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "canonicalEntities": connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "sourceEntities": connection.execute("SELECT COUNT(*) FROM entities WHERE type='source'").fetchone()[0],
            "sourceReferences": connection.execute("SELECT COUNT(*) FROM source_refs").fetchone()[0],
            "relationships": connection.execute("SELECT COUNT(*) FROM relationships").fetchone()[0],
            "businessOutcomes": connection.execute("SELECT COUNT(*) FROM business_outcomes").fetchone()[0],
            "conditionalEntityCounts": dict(connection.execute("SELECT type,COUNT(*) FROM entities WHERE type IN ('marketing-campaign','product-service','project-initiative','sales-opportunity','topic') GROUP BY type").fetchall()),
        }
        connection.close()
    attachment_report = json.loads((ROOT / "Inputs" / "olm" / "quality-report.json").read_text())
    zero_quarantine = attachment_report.get("attachmentDispositions", {}).get("quarantined", 0) == 0
    operational_passed = bool(
        operational.get("databaseIntegrity") == "ok"
        and operational.get("sourceEntities") == 2
        and operational.get("sourceReferences", 0) >= operational.get("canonicalEntities", 1)
        and operational.get("businessOutcomes", 0) > 0
        and operational.get("conditionalEntityCounts")
        and zero_quarantine
    )
    go = validation["passed"] and elapsed < 2 and semantic_complete and operational_passed
    report = {
        "runId": run, "auditedAt": now_sgt(), "validation": validation,
        "queryTests": {key: len(value) for key, value in query_tests.items()},
        "queryTestDetails": query_tests, "querySeconds": elapsed,
        "semanticSummary": semantic, "semanticComplete": semantic_complete,
        "operationalTests": operational, "operationalTestsPassed": operational_passed,
        "attachmentDispositions": attachment_report.get("attachmentDispositions"),
        "goNoGo": "GO" if go else "NO-GO",
    }
    run_dir = ROOT / "runs" / run
    json_dump(run_dir / "final-audit.json", report)
    markdown = ["# Final Influential Brands Wiki Audit", "", f"- Run: `{run}`", f"- Audited: {report['auditedAt']}", f"- Decision: **{report['goNoGo']}**", f"- Validation passed: {validation['passed']}", f"- Semantic coverage passed: {semantic_complete}", f"- Operational tests passed: {operational_passed}", f"- Query test time: {elapsed:.3f}s", "", "## Entity Counts", ""]
    markdown.extend(f"- {key}: {value}" for key, value in sorted(validation.get("entityCounts", {}).items()))
    markdown += ["", "## Operational Tests", "", "```json", json.dumps(operational, ensure_ascii=False, indent=2), "```", "", "## Errors", "", "```json", json.dumps(validation["errors"], ensure_ascii=False, indent=2), "```"]
    (run_dir / "final-audit.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return report


def append_logs(run: str, action: str, detail: str) -> None:
    entry = f"\n- {now_sgt()} | run `{run}` | {action} | {detail}\n"
    for path in (ROOT / "entities").glob("*/log.md"):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(entry)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["inventory", "productionise", "prepare", "pilot", "semantic", "ingest", "rebuild", "validate", "repair", "audit", "query"])
    parser.add_argument("--run-id", default=run_id())
    parser.add_argument("--scope", choices=["scaffold", "inputs", "entities", "index", "all"], default="all")
    parser.add_argument("--text")
    parser.add_argument("--attachment-limit", type=int)
    args = parser.parse_args()
    run_dir = ROOT / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "inventory":
            output = {"runId": args.run_id, "excel": {"path": str(DEFAULT_EXCEL), "size": DEFAULT_EXCEL.stat().st_size, "sha256": sha256_file(DEFAULT_EXCEL)}, "olm": {"path": str(DEFAULT_OLM), "size": DEFAULT_OLM.stat().st_size, "sha256": sha256_file(DEFAULT_OLM)}, "freeBytes": shutil.disk_usage(ROOT).free}
        elif args.command == "productionise":
            generate_schemas_and_indexes()
            output = {"runId": args.run_id, "productionised": True}
        elif args.command == "prepare":
            sources = source_entities(DEFAULT_EXCEL, DEFAULT_OLM, now_sgt())
            for source in sources:
                raw_path = ROOT / source["rawPath"]
                preserve_raw(Path(source["originalPath"]), raw_path, source["fileHash"])
                write_entity("source", source, f"Immutable source `{source['originalFilename']}`.")
            excel_quality = prepare_excel(DEFAULT_EXCEL, ROOT / "Inputs" / "spreadsheets", sources[0]["sourceId"])
            olm_quality = prepare_olm(DEFAULT_OLM, ROOT / "Inputs" / "olm", sources[1]["sourceId"], args.attachment_limit)
            output = {"runId": args.run_id, "excel": excel_quality, "olm": olm_quality}
        elif args.command == "pilot":
            output = ingest_entities(args.run_id, limit_excel=100, limit_messages=200)
            rebuild_result = rebuild()
            pilot_validation = validate("all")
            output |= {"rebuild": rebuild_result, "validation": pilot_validation}
            if not pilot_validation["passed"]:
                raise RuntimeError("C0 pilot validation failed")
        elif args.command == "semantic":
            output = semantic_extract(args.run_id)
        elif args.command == "ingest":
            output = ingest_entities(args.run_id)
            append_logs(args.run_id, "full-ingest", json.dumps(output["entityCounts"], sort_keys=True))
        elif args.command == "rebuild":
            output = rebuild()
        elif args.command == "validate":
            output = validate(args.scope)
            json_dump(run_dir / "validate-result.json", output)
            if not output["passed"]:
                raise RuntimeError(f"C0 validation failed: {json.dumps(output['errors'], ensure_ascii=False)[:2000]}")
        elif args.command == "repair":
            generate_schemas_and_indexes()
            attachment_repairs = repair_attachments() if (ROOT / "Inputs" / "olm" / "attachments-manifest.ndjson").exists() else {}
            output = {"runId": args.run_id, "repairsAttempted": ["schema-template-regeneration", "targeted-attachment-retry"], "attachmentRepairs": attachment_repairs, "validation": validate(args.scope)}
        elif args.command == "audit":
            output = audit(args.run_id)
            if output["goNoGo"] != "GO":
                raise RuntimeError("C0 final audit is NO-GO")
        else:
            output = {"query": args.text, "results": query(args.text or "")}
        json_dump(run_dir / f"{args.command}-receipt.json", output)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        failure = {"runId": args.run_id, "command": args.command, "failedAt": now_sgt(), "condition": "C0", "error": f"{type(error).__name__}: {error}"}
        json_dump(run_dir / f"{args.command}-failure.json", failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
