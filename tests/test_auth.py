"""Authentication, CSRF, migration, and per-user isolation tests."""

import glob
import io
import os
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from argon2 import extract_parameters

import support  # noqa: F401
from app import create_app
from database.db import get_connection, initialize_database


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "lifegraph.db")
        self.upload_directory = os.path.join(self.temp_dir.name, "private-files")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": self.database_path,
                "UPLOAD_DIRECTORY": self.upload_directory,
                "WTF_CSRF_ENABLED": True,
                "RATELIMIT_STORAGE_URI": "memory://",
                "SESSION_COOKIE_SECURE": True,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _csrf(self, client, path="/login"):
        response = client.get(path)
        match = re.search(
            r'(?:name="csrf_token" value="|name="csrf-token" content=")([^"]+)',
            response.get_data(as_text=True),
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def _signup(self, client, email, full_name="Test Person", password="correct horse battery staple"):
        token = self._csrf(client, "/signup")
        return client.post(
            "/signup",
            data={
                "csrf_token": token,
                "full_name": full_name,
                "email": email,
                "password": password,
                "confirm_password": password,
            },
            follow_redirects=False,
        )

    def _login(self, client, email, password, next_url=None):
        token = self._csrf(client)
        return client.post(
            "/login" + (f"?next={next_url}" if next_url else ""),
            data={"csrf_token": token, "email": email, "password": password},
            follow_redirects=False,
        )

    def _upload(self, client, filename, content):
        token = self._csrf(client, "/dashboard")
        return client.post(
            "/api/documents/upload",
            data={"document": (io.BytesIO(content), filename)},
            headers={"X-CSRFToken": token},
            content_type="multipart/form-data",
        )

    def test_signup_hashes_password_and_rejects_duplicate_email(self):
        response = self._signup(self.client, "Person@example.com")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")
        cookie = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Secure", cookie)

        with closing(sqlite3.connect(self.database_path)) as connection:
            password_hash = connection.execute(
                "SELECT password_hash FROM users"
            ).fetchone()[0]
        self.assertTrue(password_hash.startswith("$argon2id$"))
        self.assertEqual(extract_parameters(password_hash).type.name, "ID")

        duplicate_client = self.app.test_client()
        duplicate = self._signup(
            duplicate_client,
            "person@EXAMPLE.com",
            full_name="Duplicate",
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn(b"already exists", duplicate.data)

    def test_signup_rejects_invalid_server_side_inputs(self):
        token = self._csrf(self.client, "/signup")
        invalid_forms = (
            {
                "full_name": "",
                "email": "person@example.com",
                "password": "correct horse battery staple",
                "confirm_password": "correct horse battery staple",
            },
            {
                "full_name": "Person",
                "email": "not-an-email",
                "password": "correct horse battery staple",
                "confirm_password": "correct horse battery staple",
            },
            {
                "full_name": "Person",
                "email": "person@example.com",
                "password": "too short",
                "confirm_password": "too short",
            },
            {
                "full_name": "Person",
                "email": "person@example.com",
                "password": "correct horse battery staple",
                "confirm_password": "different secure password",
            },
        )
        for form in invalid_forms:
            with self.subTest(form=form):
                response = self.client.post("/signup", data={"csrf_token": token, **form})
                self.assertEqual(response.status_code, 400)
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM users").fetchone()[0], 0)

    def test_invalid_login_logout_and_private_page_redirects(self):
        self._signup(self.client, "person@example.com")
        self.client.post(
            "/logout",
            data={"csrf_token": self._csrf(self.client, "/dashboard")},
        )
        invalid = self._login(self.client, "person@example.com", "incorrect")
        self.assertEqual(invalid.status_code, 401)
        self.assertIn(b"Invalid email or password", invalid.data)
        self.assertIn(b'data-i18n="auth.errorInvalidCredentials"', invalid.data)

        for path in (
            "/dashboard",
            "/service",
            "/checklist",
            "/static/dashboard.html",
            "/static/checklist.html",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response.headers["Location"])
        self.assertEqual(self.client.get("/static/service.html").status_code, 404)

        self.assertEqual(self.client.get("/service?service=tn-residence-certificate").status_code, 302)
        self.assertIn(
            "/login?next=/service?service%3Dtn-residence-certificate",
            self.client.get("/service?service=tn-residence-certificate").headers["Location"],
        )
        self.assertEqual(self.client.get("/api/services").status_code, 401)
        self.assertEqual(self.client.get("/static/dashboard.html").status_code, 302)
        login = self._login(
            self.client,
            "person@example.com",
            "correct horse battery staple",
            "%2Fservice%3Fservice%3Dtn-residence-certificate",
        )
        self.assertEqual(
            login.headers["Location"],
            "/service?service=tn-residence-certificate",
        )
        self.client.post(
            "/logout",
            data={"csrf_token": self._csrf(self.client, "/dashboard")},
        )
        unsafe_login = self._login(
            self.client,
            "person@example.com",
            "correct horse battery staple",
            "https://attacker.example",
        )
        self.assertEqual(unsafe_login.headers["Location"], "/dashboard")
        self.assertEqual(self.client.get("/service").status_code, 200)
        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Test Person", dashboard.data)
        token = self._csrf(self.client, "/dashboard")
        logout = self.client.post("/logout", data={"csrf_token": token})
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 302)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        for path in (
            "/api/documents",
            "/api/checklists/tn-residence-certificate",
            "/api/services",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_private_apis_require_authentication(self):
        checks = (
            ("GET", "/api/services"),
            ("GET", "/api/services/tn-residence-certificate"),
            ("GET", "/api/services/tn-residence-certificate/checklist"),
            ("GET", "/api/documents"),
            ("GET", "/api/documents/unknown-id"),
            ("GET", "/api/checklists/tn-residence-certificate"),
            ("GET", "/api/auth/me"),
            ("DELETE", "/api/documents/unknown-id"),
            ("PUT", "/api/checklists/tn-residence-certificate"),
        )
        for method, path in checks:
            with self.subTest(path=path):
                response = self.client.open(path, method=method)
                self.assertEqual(response.status_code, 401)
                self.assertIn("error", response.get_json())
        upload = self.client.post(
            "/api/documents/upload",
            data={"document": (io.BytesIO(b"%PDF-1.7 sample"), "sample.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 401)

    def test_login_is_rate_limited(self):
        for attempt in range(5):
            response = self._login(
                self.client,
                "nobody@example.com",
                f"incorrect-{attempt}",
            )
            self.assertEqual(response.status_code, 401)
        blocked = self._login(self.client, "nobody@example.com", "incorrect")
        self.assertEqual(blocked.status_code, 429)

    def test_csrf_is_required_for_authenticated_state_changes(self):
        self._signup(self.client, "csrf@example.com")
        rejected = self.client.post(
            "/api/documents/upload",
            data={"document": (io.BytesIO(b"%PDF-1.7 sample"), "sample.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(os.path.exists(self.upload_directory))

    def test_documents_and_checklist_progress_are_isolated_between_users(self):
        alice = self.app.test_client()
        bob = self.app.test_client()
        self._signup(alice, "alice@example.com", "Alice")
        self._signup(bob, "bob@example.com", "Bob")
        self.assertEqual(alice.get("/api/auth/me").get_json()["email"], "alice@example.com")
        self.assertEqual(bob.get("/api/auth/me").get_json()["email"], "bob@example.com")

        alice_upload = self._upload(alice, "alice.pdf", b"%PDF-1.7 alice")
        bob_upload = self._upload(bob, "bob.pdf", b"%PDF-1.7 bob")
        self.assertEqual(alice_upload.status_code, 201)
        self.assertEqual(bob_upload.status_code, 201)
        alice_document = alice_upload.get_json()
        bob_document = bob_upload.get_json()
        self.assertNotEqual(alice_document["id"], bob_document["id"])
        self.assertEqual(
            [item["filename"] for item in alice.get("/api/documents").get_json()["documents"]],
            ["alice.pdf"],
        )
        self.assertEqual(
            [item["filename"] for item in bob.get("/api/documents").get_json()["documents"]],
            ["bob.pdf"],
        )

        alice_file = alice.get(f"/api/documents/{alice_document['id']}")
        self.assertEqual(alice_file.status_code, 200)
        self.assertEqual(alice_file.data, b"%PDF-1.7 alice")
        alice_file.close()
        self.assertEqual(
            bob.get(f"/api/documents/{alice_document['id']}").status_code,
            404,
        )
        bob_file_list = bob.get("/api/documents").get_json()["documents"]
        self.assertNotIn(alice_document["id"], {item["id"] for item in bob_file_list})
        self.assertEqual(
            bob.put(
                f"/api/documents/{alice_document['id']}",
                headers={"X-CSRFToken": self._csrf(bob, "/dashboard")},
            ).status_code,
            405,
        )
        self.assertEqual(
            bob.delete(
                f"/api/documents/{alice_document['id']}",
                headers={"X-CSRFToken": self._csrf(bob, "/dashboard")},
            ).status_code,
            404,
        )
        owner_can_still_read = alice.get(f"/api/documents/{alice_document['id']}")
        self.assertEqual(owner_can_still_read.status_code, 200)
        owner_can_still_read.close()
        bob_file = bob.get(f"/api/documents/{bob_document['id']}")
        self.assertEqual(bob_file.status_code, 200)
        self.assertEqual(bob_file.data, b"%PDF-1.7 bob")
        bob_file.close()

        service_id = "tn-residence-certificate"
        progress_path = f"/api/checklists/{service_id}"
        self.assertEqual(
            alice.get(progress_path).get_json()["reminders"],
            [False, False],
        )
        update_token = self._csrf(alice, "/checklist")
        with get_connection(self.database_path) as connection:
            alice_user_id = connection.execute(
                "SELECT id FROM users WHERE email = ?",
                ("alice@example.com",),
            ).fetchone()["id"]
        updated = alice.put(
            progress_path,
            json={
                "kind": "reminder",
                "index": 0,
                "checked": True,
                "user_id": alice_user_id,
            },
            headers={"X-CSRFToken": update_token},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(alice.get(progress_path).get_json()["reminders"], [True, False])
        self.assertEqual(bob.get(progress_path).get_json()["reminders"], [False, False])
        bob_update = bob.put(
            progress_path,
            json={
                "kind": "reminder",
                "index": 1,
                "checked": True,
                "user_id": alice_user_id,
            },
            headers={"X-CSRFToken": self._csrf(bob, "/checklist")},
        )
        self.assertEqual(bob_update.status_code, 200)
        self.assertEqual(alice.get(progress_path).get_json()["reminders"], [True, False])
        self.assertEqual(bob.get(progress_path).get_json()["reminders"], [False, True])
        malformed = alice.put(
            progress_path,
            json={"kind": {}, "index": 0, "checked": True},
            headers={"X-CSRFToken": update_token},
        )
        self.assertEqual(malformed.status_code, 400)

        self.assertEqual(
            alice.delete(
                f"/api/documents/{alice_document['id']}",
                headers={"X-CSRFToken": self._csrf(alice, "/dashboard")},
            ).status_code,
            200,
        )
        self.assertEqual(alice.get(f"/api/documents/{alice_document['id']}").status_code, 404)

    def test_checklist_progress_can_be_toggled_and_persists_after_relogin(self):
        self._signup(self.client, "checklist-owner@example.com", "Checklist Owner")
        service_id = "tn-residence-certificate"
        progress_path = f"/api/checklists/{service_id}"

        with get_connection(self.database_path) as connection:
            connection.execute(
                """
                UPDATE services
                SET requirements_json = ?, requirement_verification_status = 'needs_verification'
                WHERE id = ?
                """,
                ('["Synthetic checklist item"]', service_id),
            )

        initial = self.client.get(progress_path)
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.get_json()["requirements"], [False])
        self.assertEqual(initial.get_json()["reminders"], [False, False])

        csrf_token = self._csrf(self.client, "/checklist")
        completed = self.client.put(
            progress_path,
            json={"kind": "requirement", "index": 0, "checked": True},
            headers={"X-CSRFToken": csrf_token},
        )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(
            self.client.get(progress_path).get_json()["requirements"],
            [True],
        )

        unchecked = self.client.put(
            progress_path,
            json={"kind": "requirement", "index": 0, "checked": False},
            headers={"X-CSRFToken": csrf_token},
        )
        self.assertEqual(unchecked.status_code, 200)
        self.assertEqual(
            self.client.get(progress_path).get_json()["requirements"],
            [False],
        )

        reminder = self.client.put(
            progress_path,
            json={"kind": "reminder", "index": 1, "checked": True},
            headers={"X-CSRFToken": csrf_token},
        )
        self.assertEqual(reminder.status_code, 200)
        self.assertEqual(
            self.client.post(
                "/logout",
                data={"csrf_token": self._csrf(self.client, "/dashboard")},
            ).status_code,
            302,
        )
        self.assertEqual(self.client.get(progress_path).status_code, 401)

        login = self._login(
            self.client,
            "checklist-owner@example.com",
            "correct horse battery staple",
        )
        self.assertEqual(login.status_code, 302)
        persisted = self.client.get(progress_path)
        self.assertEqual(persisted.status_code, 200)
        self.assertEqual(persisted.get_json()["requirements"], [False])
        self.assertEqual(persisted.get_json()["reminders"], [False, True])

    def test_official_checklist_progress_is_preserved_by_database_reinitialization(self):
        self._signup(self.client, "official-checklist@example.com", "Checklist Owner")
        service_id = "tn-community-certificate"
        progress_path = f"/api/checklists/{service_id}"
        checklist = self.client.get(
            f"/api/services/{service_id}/checklist"
        ).get_json()
        self.assertEqual(checklist["requirement_verification_status"], "verified")
        self.assertGreater(len(checklist["requirements"]), 0)

        completed = self.client.put(
            progress_path,
            json={"kind": "requirement", "index": 0, "checked": True},
            headers={"X-CSRFToken": self._csrf(self.client, "/checklist")},
        )
        self.assertEqual(completed.status_code, 200)
        with get_connection(self.database_path) as connection:
            connection.execute(
                """
                UPDATE services
                SET source_url = ?
                WHERE id = ?
                """,
                (
                    "https://tnesevai.tn.gov.in/Pages/EsevaiServiceList.aspx",
                    service_id,
                ),
            )
        initialize_database(self.database_path)
        self.assertEqual(
            self.client.get(f"/api/services/{service_id}").get_json()["source_url"],
            "https://www.tnesevai.tn.gov.in/Citizen/FAQ.html",
        )
        self.assertEqual(
            self.client.get(progress_path).get_json()["requirements"][0],
            True,
        )

        self.client.post(
            "/logout",
            data={"csrf_token": self._csrf(self.client, "/dashboard")},
        )
        login = self._login(
            self.client,
            "official-checklist@example.com",
            "correct horse battery staple",
        )
        self.assertEqual(login.status_code, 302)
        self.assertEqual(
            self.client.get(progress_path).get_json()["requirements"][0],
            True,
        )

    def test_password_reset_uses_one_time_email_token_and_revokes_sessions(self):
        self.app.config.update(
            MAIL_SERVER="smtp.example.test",
            MAIL_PORT=587,
            MAIL_DEFAULT_SENDER="noreply@example.test",
            PUBLIC_BASE_URL="https://lifegraph.example.test",
        )
        self._signup(self.client, "reset@example.com")
        with patch("routes.auth.smtplib.SMTP") as smtp:
            response = self.client.post(
                "/forgot-password",
                data={
                    "csrf_token": self._csrf(self.client, "/forgot-password"),
                    "email": "reset@example.com",
                },
            )
        self.assertEqual(response.status_code, 302)
        body = smtp.return_value.__enter__.return_value.send_message.call_args.args[0].get_content()
        token_match = re.search(r"/reset-password/([A-Za-z0-9_-]+)", body)
        self.assertIsNotNone(token_match)
        token = token_match.group(1)
        reset_path = f"/reset-password/{token}"
        reset_page = self.client.get(reset_path)
        self.assertEqual(reset_page.status_code, 200)
        response = self.client.post(
            reset_path,
            data={
                "csrf_token": self._csrf(self.client, reset_path),
                "password": "a brand new secure password",
                "confirm_password": "a brand new secure password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 302)
        self.assertEqual(self._login(self.client, "reset@example.com", "correct horse battery staple").status_code, 401)
        self.assertEqual(self._login(self.client, "reset@example.com", "a brand new secure password").status_code, 302)
        self.assertEqual(self.client.get(reset_path).status_code, 400)

    def test_database_migration_creates_a_prechange_backup(self):
        legacy_path = os.path.join(self.temp_dir.name, "legacy.db")
        with closing(sqlite3.connect(legacy_path)) as connection:
            with connection:
                connection.execute("CREATE TABLE legacy_data (value TEXT)")
                connection.execute("INSERT INTO legacy_data VALUES ('preserved')")
        initialize_database(legacy_path)
        backups = glob.glob(f"{legacy_path}.pre-auth-*.bak")
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as backup:
            self.assertEqual(
                backup.execute("SELECT value FROM legacy_data").fetchone()[0],
                "preserved",
            )
        with closing(sqlite3.connect(legacy_path)) as migrated:
            self.assertEqual(migrated.execute("SELECT value FROM legacy_data").fetchone()[0], "preserved")
            self.assertIsNotNone(
                migrated.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
                ).fetchone()
            )


if __name__ == "__main__":
    unittest.main()
