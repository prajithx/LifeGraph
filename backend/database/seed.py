"""Helpers for reading explicitly marked demo JSON data."""

import json
from pathlib import Path

import sqlite3

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_demo_json(filename):
    with (DATA_DIR / filename).open(encoding="utf-8") as data_file:
        return json.load(data_file)


def seed_services(connection: sqlite3.Connection):
    catalogue = load_demo_json("services.json")
    for service in catalogue["services"]:
        connection.execute(
            """
            INSERT OR IGNORE INTO services (
                id, name, purpose, requirements_json, source_url,
                verification_status, last_verified, is_demo, category,
                responsible_authority, requirement_verification_status,
                checklist_metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                service["id"],
                service["name"],
                service["purpose"],
                json.dumps(service["requirements"]),
                service["source_url"],
                service["verification_status"],
                service["last_verified"],
                service.get("category", "Tamil Nadu e-Sevai Certificates"),
                service.get("responsible_authority", ""),
                service.get(
                    "requirement_verification_status",
                    service["verification_status"],
                ),
                json.dumps(service.get("checklist_metadata", {})),
            ),
        )
        connection.execute(
            """
            UPDATE services
            SET category = ?, responsible_authority = ?
            WHERE id = ? AND responsible_authority = ''
            """,
            (
                service.get("category", "Tamil Nadu e-Sevai Certificates"),
                service.get("responsible_authority", ""),
                service["id"],
            ),
        )
    for service in catalogue["services"]:
        if not service.get("checklist_metadata"):
            continue
        connection.execute(
            """
            UPDATE services
            SET requirements_json = ?, source_url = ?, verification_status = ?,
                last_verified = ?, requirement_verification_status = ?,
                checklist_metadata_json = ?
            WHERE id = ? AND requirements_json = '[]'
                AND requirement_verification_status = 'needs_verification'
            """,
            (
                json.dumps(service["requirements"]),
                service["source_url"],
                service["verification_status"],
                service["last_verified"],
                service["requirement_verification_status"],
                json.dumps(service["checklist_metadata"]),
                service["id"],
            ),
        )
        if service.get("requirement_verification_status") != "verified":
            continue
        connection.execute(
            """
            UPDATE services
            SET requirements_json = ?, source_url = ?, responsible_authority = ?,
                verification_status = ?, last_verified = ?,
                requirement_verification_status = ?, checklist_metadata_json = ?
            WHERE id = ? AND is_demo = 1 AND requirements_json = ?
               OR (
                    id = ? AND is_demo = 1
                    AND source_url = 'https://tnesevai.tn.gov.in/Pages/ServiceList.aspx'
                    AND checklist_metadata_json LIKE '%Tamil Nadu e-Sevai Services Offered%'
               )
            """,
            (
                json.dumps(service["requirements"]),
                service["source_url"],
                service.get("responsible_authority", ""),
                service["verification_status"],
                service["last_verified"],
                service["requirement_verification_status"],
                json.dumps(service["checklist_metadata"]),
                service["id"],
                json.dumps(service["requirements"]),
                service["id"],
            ),
        )
    for service in catalogue["services"]:
        connection.execute(
            """
            UPDATE services
            SET source_url = ?
            WHERE id = ? AND source_url = ?
            """,
            (
                catalogue["catalogue_source"],
                service["id"],
                "https://tnesevai.tn.gov.in/Pages/EsevaiServiceList.aspx",
            ),
        )
    connection.execute(
        """
        UPDATE services
        SET source_url = ?
        WHERE source_url = ?
          AND verification_status = 'needs_verification'
          AND requirements_json = '[]'
        """,
        (
            catalogue["catalogue_source"],
            "https://www.tnesevai.tn.gov.in/Pages/ServiceList.aspx",
        ),
    )
