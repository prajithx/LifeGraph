"""Queries and maps service catalogue records stored in SQLite."""

import json
import sqlite3
from contextlib import closing


def _connect(database_path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def _service_from_row(row):
    requirements = json.loads(row["requirements_json"])
    checklist_metadata = json.loads(
        row["checklist_metadata_json"]
        if "checklist_metadata_json" in row.keys()
        else "{}"
    )
    requirements_source_url = checklist_metadata.get("requirements_source_url")
    official_application_url = checklist_metadata.get(
        "official_application_url", row["source_url"]
    )
    return {
        "id": row["id"],
        "name": row["name"],
        "purpose": row["purpose"],
        "description": row["purpose"],
        "requirements": requirements,
        "source_url": row["source_url"],
        "official_application_url": official_application_url,
        "official_portal_url": official_application_url,
        "requirements_source_url": requirements_source_url,
        "category": row["category"],
        "responsible_authority": row["responsible_authority"],
        "verification_status": row["requirement_verification_status"],
        "requirement_verification_status": row["requirement_verification_status"],
        "last_verified": row["last_verified"],
        "checklist_metadata": checklist_metadata,
        "is_demo": bool(row["is_demo"]),
    }


def list_services(database_path, query=""):
    with closing(_connect(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT * FROM services
            WHERE name LIKE ? OR purpose LIKE ? OR category LIKE ?
                OR responsible_authority LIKE ?
            ORDER BY name COLLATE NOCASE
            """,
            (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"),
        ).fetchall()
    return [_service_from_row(row) for row in rows]


def get_service(database_path, service_id):
    with closing(_connect(database_path)) as connection:
        row = connection.execute(
            "SELECT * FROM services WHERE id = ?", (service_id,)
        ).fetchone()
    return _service_from_row(row) if row is not None else None