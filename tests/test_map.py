"""Tests for the Centre Finder's explicit unavailable state."""

import os
import tempfile
import unittest

import support  # noqa: F401
from app import create_app


class CentreFinderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": os.path.join(self.temp_dir.name, "test.db"),
                "UPLOAD_DIRECTORY": os.path.join(self.temp_dir.name, "uploads"),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_public_page_explains_missing_service_specific_centre_sources(self):
        response = self.client.get("/map")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('data-i18n="map.disclaimer"', page)
        self.assertIn('data-i18n="map.configuration"', page)
        self.assertIn("https://www.tnesevai.tn.gov.in/", page)
        self.assertIn("https://tngis.tn.gov.in/data.html", page)
        self.assertIn("As checked on 22 October 2026", page)
        self.assertNotIn("https://tnega.tn.gov.in/csclocation", page)
        self.assertNotIn("https://tngis.tn.gov.in/apps.html", page)
        self.assertIn('rel="noopener noreferrer"', page)
        self.assertNotIn("<form", page)
        self.assertNotIn("data-centre-result", page)
        self.assertNotIn("data-map", page)

    def test_centre_finder_does_not_expose_private_user_data(self):
        response = self.client.get("/map")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("document-list", response.get_data(as_text=True))
