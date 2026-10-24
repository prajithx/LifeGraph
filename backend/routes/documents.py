"""Authenticated, owner-scoped document endpoints."""

import sqlite3
import secrets
import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from flask_login import current_user, login_required

from database.db import get_connection
from services.document_service import DocumentValidationError, store_document
from services.reminder_service import (
    generate_notifications,
    list_notifications,
    notification_state,
    validate_metadata,
    application_today,
)

documents_api = Blueprint("documents_api", __name__, url_prefix="/api/documents")

DOCUMENT_ERROR_KEYS = {
    "invalid_filename": "The selected filename is not valid.",
    "unsupported_type": "Only PDF, PNG, JPG, and JPEG files are supported.",
    "too_large": "The file exceeds the 10 MB upload limit.",
    "empty_file": "The selected file is empty.",
    "invalid_contents": "The file contents do not match the selected file type.",
    "missing_file": "Select a document to upload.",
    "store_failed": "The document could not be stored. Please try again.",
    "not_found": "Document not found.",
    "delete_failed": "The document could not be removed.",
    "invalid_metadata": "Check the document name and date/reminder settings.",
}


def _document_error(code, status):
    return jsonify({"error": DOCUMENT_ERROR_KEYS[code], "error_code": code}), status


@documents_api.post("/upload")
@login_required
def upload_document():
    uploaded_file = request.files.get("document")
    if uploaded_file is None:
        return _document_error("missing_file", 400)

    try:
        metadata = validate_metadata(
            request.form.get("document_name"),
            request.form.get("issue_date"),
            request.form.get("expiry_date"),
            json.loads(request.form.get("reminder_intervals", "[]")),
        )
        result = store_document(
            uploaded_file,
            current_app.config["UPLOAD_DIRECTORY"],
            current_app.config["MAX_UPLOAD_SIZE_BYTES"],
        )
        document_id = secrets.token_hex(16)
        with get_connection(current_app.config["DATABASE_PATH"]) as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    id, user_id, original_filename, stored_filename, size_bytes, created_at,
                    display_name, issue_date, expiry_date, reminder_intervals
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    current_user.get_id(),
                    result["filename"],
                    result["stored_filename"],
                    result["size"],
                    datetime.now(timezone.utc).isoformat(),
                    metadata[0],
                    metadata[1],
                    metadata[2],
                    json.dumps(metadata[3]),
                ),
            )
            generate_notifications(
                connection,
                timezone_name=current_app.config["TIMEZONE"],
            )
    except DocumentValidationError as error:
        return jsonify({"error": str(error), "error_code": error.code}), 400
    except (ValueError, json.JSONDecodeError) as error:
        return jsonify({"error": str(error), "error_code": "invalid_metadata"}), 400
    except (OSError, sqlite3.Error):
        if "result" in locals():
            try:
                (Path(current_app.config["UPLOAD_DIRECTORY"]) / result["stored_filename"]).unlink(missing_ok=True)
            except OSError:
                current_app.logger.exception("Could not clean up an unregistered uploaded file.")
        current_app.logger.exception("Could not store uploaded document.")
        return _document_error("store_failed", 500)

    return jsonify(
        {
            "id": document_id,
            "filename": result["filename"],
            "size": result["size"],
            "document_name": metadata[0],
            "issue_date": metadata[1],
            "expiry_date": metadata[2],
            "reminder_intervals": metadata[3],
            "message": "Document stored privately. No text extraction or analysis was performed.",
        }
    ), 201


@documents_api.get("")
@login_required
def list_documents():
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        rows = connection.execute(
            """
            SELECT id, original_filename, size_bytes, created_at,
                   display_name, issue_date, expiry_date, reminder_intervals
            FROM documents
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (current_user.get_id(),),
        ).fetchall()
    return jsonify(
        {
            "documents": [
                {
                    "id": row["id"],
                    "filename": row["original_filename"],
                    "size": row["size_bytes"],
                    "created_at": row["created_at"],
                    "document_name": row["display_name"],
                    "issue_date": row["issue_date"],
                    "expiry_date": row["expiry_date"],
                    "reminder_intervals": json.loads(row["reminder_intervals"] or "[]"),
                }
                for row in rows
            ]
        }
    )


@documents_api.get("/<document_id>")
@login_required
def download_document(document_id):
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        row = connection.execute(
            """
            SELECT original_filename, stored_filename
            FROM documents
            WHERE id = ? AND user_id = ?
            """,
            (document_id, current_user.get_id()),
        ).fetchone()
    if row is None:
        return _document_error("not_found", 404)
    return send_from_directory(
        current_app.config["UPLOAD_DIRECTORY"],
        row["stored_filename"],
        as_attachment=True,
        download_name=row["original_filename"],
    )


@documents_api.put("/<document_id>")
@login_required
def update_document_metadata(document_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON document metadata update is required."}), 405
    try:
        metadata = validate_metadata(
            payload.get("document_name"),
            payload.get("issue_date"),
            payload.get("expiry_date"),
            payload.get("reminder_intervals", []),
        )
    except ValueError as error:
        return jsonify({"error": str(error), "error_code": "invalid_metadata"}), 400
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        row = connection.execute(
            "SELECT id FROM documents WHERE id = ? AND user_id = ?",
            (document_id, current_user.get_id()),
        ).fetchone()
        if row is None:
            return _document_error("not_found", 404)
        connection.execute("DELETE FROM notifications WHERE document_id = ?", (document_id,))
        connection.execute(
            """
            UPDATE documents
            SET display_name = ?, issue_date = ?, expiry_date = ?, reminder_intervals = ?
            WHERE id = ? AND user_id = ?
            """,
            (*metadata[:3], json.dumps(metadata[3]), document_id, current_user.get_id()),
        )
        generate_notifications(connection, timezone_name=current_app.config["TIMEZONE"])
    return jsonify({
        "id": document_id,
        "document_name": metadata[0],
        "issue_date": metadata[1],
        "expiry_date": metadata[2],
        "reminder_intervals": metadata[3],
    })


@documents_api.delete("/<document_id>")
@login_required
def delete_document(document_id):
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        row = connection.execute(
            """
            SELECT stored_filename
            FROM documents
            WHERE id = ? AND user_id = ?
            """,
            (document_id, current_user.get_id()),
        ).fetchone()
        if row is None:
            return _document_error("not_found", 404)
        file_path = Path(current_app.config["UPLOAD_DIRECTORY"]) / row["stored_filename"]
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.exception("Could not remove uploaded document.")
            return _document_error("delete_failed", 500)
        connection.execute(
            "DELETE FROM documents WHERE id = ? AND user_id = ?",
            (document_id, current_user.get_id()),
        )
    return jsonify({"deleted": True})


@documents_api.get("/notifications")
@login_required
def get_notifications():
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        generate_notifications(connection, timezone_name=current_app.config["TIMEZONE"])
        today = application_today(current_app.config["TIMEZONE"])
        rows = list_notifications(connection, current_user.get_id(), today)
    return jsonify({
        "timezone": current_app.config["TIMEZONE"],
        "today": today.isoformat(),
        "notifications": [
            {
                "id": row["id"],
                "document_id": row["document_id"],
                "document_name": row["document_name"],
                "due_date": row["due_date"],
                "reminder_interval": row["reminder_interval"],
                "state": notification_state(row["due_date"], today),
            }
            for row in rows
        ],
    })


@documents_api.patch("/notifications/<int:notification_id>")
@login_required
def update_notification(notification_id):
    payload = request.get_json(silent=True)
    status = payload.get("status") if isinstance(payload, dict) else None
    if status not in {"read", "dismissed"}:
        return jsonify({"error": "Notification status must be read or dismissed."}), 400
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        cursor = connection.execute(
            """
            UPDATE notifications SET status = ?
            WHERE id = ? AND user_id = ?
            """,
            (status, notification_id, current_user.get_id()),
        )
    if cursor.rowcount == 0:
        return jsonify({"error": "Notification not found."}), 404
    return jsonify({"id": notification_id, "status": status})
