"""Tests for private, constrained document uploads."""

import io
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import date
from contextlib import contextmanager
from unittest.mock import patch

import support  # noqa: F401
from app import create_app
from database.db import get_connection
from werkzeug.datastructures import FileStorage
from services.document_service import DocumentValidationError, store_document
from services.reminder_service import generate_notifications, notification_state


class DocumentUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.upload_directory = os.path.join(self.temp_dir.name, "uploads")
        database_path = os.path.join(self.temp_dir.name, "test.db")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": database_path,
                "UPLOAD_DIRECTORY": self.upload_directory,
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.client = self.app.test_client()
        self.max_upload_size = self.app.config["MAX_UPLOAD_SIZE_BYTES"]
        signup = self.client.get("/signup")
        token = re.search(
            r'name="csrf_token" value="([^"]+)"',
            signup.get_data(as_text=True),
        ).group(1)
        self.client.post(
            "/signup",
            data={
                "csrf_token": token,
                "full_name": "Document Owner",
                "email": "documents@example.com",
                "password": "long secure test password",
                "confirm_password": "long secure test password",
            },
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_accepts_supported_formats_and_stores_them_privately(self):
        examples = (
            ("sample.pdf", b"%PDF-1.7 sample"),
            ("sample.png", b"\x89PNG\r\n\x1a\nsample"),
            ("sample.jpg", b"\xff\xd8\xffsample"),
            ("sample.jpeg", b"\xff\xd8\xffsample"),
            ("ஆவணம்.pdf", b"%PDF-1.7 Tamil filename"),
            ("../outside.pdf", b"%PDF-1.7 path traversal check"),
        )

        for filename, contents in examples:
            with self.subTest(filename=filename):
                response = self.client.post(
                    "/api/documents/upload",
                    data={"document": (io.BytesIO(contents), filename)},
                    content_type="multipart/form-data",
                )
                self.assertEqual(response.status_code, 201)
                result = response.get_json()
                expected_name = os.path.basename(filename.replace("\\", "/"))
                self.assertEqual(result["filename"], expected_name)
                self.assertEqual(result["size"], len(contents))
                self.assertIn("No text extraction", result["message"])
                stored_files = os.listdir(self.upload_directory)
                self.assertEqual(len(stored_files), 1)
                self.assertNotIn("..", stored_files[0])
                self.assertNotEqual(stored_files[0], filename)
                with open(os.path.join(self.upload_directory, stored_files[0]), "rb") as stored_file:
                    self.assertEqual(stored_file.read(), contents)
                self.assertEqual(
                    self.client.get(f"/uploads/{stored_files[0]}").status_code,
                    404,
                )
                os.remove(os.path.join(self.upload_directory, stored_files[0]))

    def test_rejects_unsupported_or_mislabelled_file_types(self):
        for filename, contents in (
            ("notes.txt", b"%PDF-1.7"),
            ("fake.pdf", b"not a PDF"),
        ):
            with self.subTest(filename=filename):
                response = self.client.post(
                    "/api/documents/upload",
                    data={"document": (io.BytesIO(contents), filename)},
                    content_type="multipart/form-data",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())
                expected_code = "unsupported_type" if filename.endswith(".txt") else "invalid_contents"
                self.assertEqual(response.get_json()["error_code"], expected_code)
                self.assertTrue(response.get_json()["error"])
        self.assertFalse(os.path.exists(self.upload_directory))

    def test_rejects_oversized_empty_and_missing_uploads(self):
        self.assertEqual(self.max_upload_size, 10 * 1024 * 1024)
        self.app.config["MAX_UPLOAD_SIZE_BYTES"] = 32
        oversized = b"%PDF-" + b"x" * 32
        response = self.client.post(
            "/api/documents/upload",
            data={"document": (io.BytesIO(oversized), "large.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("10 MB", response.get_json()["error"])

        self.app.config["MAX_CONTENT_LENGTH"] = 1024
        request_too_large = b"x" * 2048
        response = self.client.post(
            "/api/documents/upload",
            data={"document": (io.BytesIO(request_too_large), "request-too-large.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("10 MB", response.get_json()["error"])

        empty_response = self.client.post(
            "/api/documents/upload",
            data={"document": (io.BytesIO(b""), "empty.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(empty_response.status_code, 400)
        self.assertIn("empty", empty_response.get_json()["error"].lower())
        self.assertEqual(self.client.post("/api/documents/upload").status_code, 400)

    def test_owner_can_list_download_and_delete_uploaded_document(self):
        contents = b"%PDF-1.7 synthetic document lifecycle"
        response = self.client.post(
            "/api/documents/upload",
            data={"document": (io.BytesIO(contents), r"..\..\private\sample.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        uploaded = response.get_json()

        listed = self.client.get("/api/documents")
        self.assertEqual(listed.status_code, 200)
        listed_documents = listed.get_json()["documents"]
        self.assertEqual(len(listed_documents), 1)
        self.assertEqual(listed_documents[0]["id"], uploaded["id"])
        self.assertEqual(listed_documents[0]["filename"], "sample.pdf")
        self.assertEqual(listed_documents[0]["size"], len(contents))
        self.assertTrue(listed_documents[0]["created_at"])

        download = self.client.get(f"/api/documents/{uploaded['id']}")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, contents)
        self.assertIn("attachment", download.headers["Content-Disposition"].lower())
        self.assertIn("sample.pdf", download.headers["Content-Disposition"])
        download.close()

        stored_files = os.listdir(self.upload_directory)
        self.assertEqual(len(stored_files), 1)
        stored_path = os.path.join(self.upload_directory, stored_files[0])
        self.assertTrue(os.path.isfile(stored_path))
        with get_connection(self.app.config["DATABASE_PATH"]) as connection:
            record = connection.execute(
                "SELECT user_id, stored_filename FROM documents WHERE id = ?",
                (uploaded["id"],),
            ).fetchone()
            owner = connection.execute(
                "SELECT id FROM users WHERE email = ?",
                ("documents@example.com",),
            ).fetchone()
            self.assertIsNotNone(record)
            self.assertIsNotNone(owner)
            self.assertEqual(record["user_id"], owner["id"])
            self.assertEqual(record["stored_filename"], stored_files[0])
        self.assertEqual(
            self.client.get(f"/static/{stored_files[0]}").status_code,
            404,
        )

        deleted = self.client.delete(f"/api/documents/{uploaded['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.get_json(), {"deleted": True})
        self.assertEqual(self.client.get("/api/documents").get_json()["documents"], [])
        self.assertEqual(self.client.get(f"/api/documents/{uploaded['id']}").status_code, 404)
        self.assertFalse(os.path.exists(stored_path))

    def test_database_failure_after_file_write_cleans_up_upload(self):
        @contextmanager
        def fail_database(_database_path):
            raise sqlite3.OperationalError("synthetic database failure")
            yield

        with patch("routes.documents.get_connection", side_effect=fail_database):
            response = self.client.post(
                "/api/documents/upload",
                data={"document": (io.BytesIO(b"%PDF-1.7 synthetic"), "sample.pdf")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 500)
        self.assertIn("could not be stored", response.get_json()["error"].lower())
        self.assertEqual(os.listdir(self.upload_directory), [])
        with get_connection(self.app.config["DATABASE_PATH"]) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                0,
            )

    def test_metadata_reminders_are_idempotent_and_editable(self):
        response = self.client.post(
            "/api/documents/upload",
            data={
                "document": (io.BytesIO(b"%PDF-1.7 dated"), "dated.pdf"),
                "document_name": "Passport",
                "issue_date": "2025-01-01",
                "expiry_date": "2025-02-01",
                "reminder_intervals": "[30, 7, 0]",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        document = response.get_json()
        self.assertEqual(document["reminder_intervals"], [30, 7, 0])

        no_expiry = self.client.post(
            "/api/documents/upload",
            data={"document": (io.BytesIO(b"%PDF-1.7 no date"), "no-date.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(no_expiry.status_code, 201)
        self.assertEqual(no_expiry.get_json()["expiry_date"], None)

        with get_connection(self.app.config["DATABASE_PATH"]) as connection:
            user_id = connection.execute(
                "SELECT id FROM users WHERE email = ?", ("documents@example.com",)
            ).fetchone()["id"]
            inserted = generate_notifications(
                connection, today=date(2025, 2, 1), timezone_name="Asia/Kolkata"
            )
            duplicate = generate_notifications(
                connection, today=date(2025, 2, 1), timezone_name="Asia/Kolkata"
            )
            self.assertEqual(inserted, 0)
            self.assertEqual(duplicate, 0)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (user_id,)
                ).fetchone()[0],
                3,
            )

        reminders = self.client.get("/api/documents/notifications").get_json()
        self.assertEqual(reminders["timezone"], "Asia/Kolkata")
        self.assertEqual(len(reminders["notifications"]), 3)

        updated = self.client.put(
            f"/api/documents/{document['id']}",
            json={
                "document_name": "Renewed Passport",
                "issue_date": None,
                "expiry_date": None,
                "reminder_intervals": [],
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertIsNone(updated.get_json()["expiry_date"])
        with get_connection(self.app.config["DATABASE_PATH"]) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM notifications WHERE document_id = ?",
                    (document["id"],),
                ).fetchone()[0],
                0,
            )

    def test_reminder_states_and_document_delete_cascade(self):
        with get_connection(self.app.config["DATABASE_PATH"]) as connection:
            user_id = connection.execute(
                "SELECT id FROM users WHERE email = ?", ("documents@example.com",)
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO documents (
                    id, user_id, original_filename, stored_filename, size_bytes, created_at,
                    display_name, expiry_date, reminder_intervals
                ) VALUES ('future', ?, 'future.pdf', 'future.pdf', 5, '2025-01-01',
                          'Future', '2025-03-01', '[0]')
                """,
                (user_id,),
            )
            generate_notifications(connection, today=date(2025, 2, 1))
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM notifications WHERE document_id = 'future'"
                ).fetchone()[0],
                0,
            )
            generate_notifications(connection, today=date(2025, 3, 1))
        self.assertEqual(
            notification_state("2025-03-01", date(2025, 3, 1)),
            "due_today",
        )
        self.assertEqual(
            notification_state("2025-03-02", date(2025, 3, 1)),
            "upcoming",
        )
        self.assertEqual(
            notification_state("2025-02-28", date(2025, 3, 1)),
            "overdue",
        )
        with get_connection(self.app.config["DATABASE_PATH"]) as connection:
            connection.execute("DELETE FROM documents WHERE id = 'future'")
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM notifications WHERE document_id = 'future'"
                ).fetchone()[0],
                0,
            )

    def test_document_service_enforces_the_configured_ten_megabyte_limit(self):
        contents = b"%PDF-" + b"x" * self.max_upload_size
        uploaded_file = FileStorage(
            stream=io.BytesIO(contents),
            filename="large.pdf",
        )

        with self.assertRaisesRegex(DocumentValidationError, "10 MB"):
            store_document(
                uploaded_file,
                self.upload_directory,
                self.max_upload_size,
            )
        self.assertFalse(os.path.exists(self.upload_directory))


if __name__ == "__main__":
    unittest.main()
