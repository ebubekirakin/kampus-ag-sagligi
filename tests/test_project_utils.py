"""Bina ve kat ayrıştırmasının iki modülde aynı sonucu verdiğini doğrular."""

import unittest

from project_utils import parse_building_floor


class TestParseBuildingFloor(unittest.TestCase):
    def test_known_floor_is_extracted(self):
        self.assertEqual(
            parse_building_floor("Mühendislik B Blok 2. kat Derslik koridoru"),
            ("Mühendislik B Blok", "2. Kat"),
        )

    def test_building_names_with_multiple_words_are_preserved(self):
        self.assertEqual(
            parse_building_floor("Öğrenci İşleri Giriş Kat"),
            ("Öğrenci İşleri", "Giriş Kat"),
        )
        self.assertEqual(
            parse_building_floor("Yemekhane Zemin Kat"),
            ("Yemekhane", "Zemin Kat"),
        )

    def test_unknown_floor_has_consistent_default(self):
        self.assertEqual(parse_building_floor("Kampüs alanı"), ("Kampüs", "Bilinmiyor"))
        self.assertEqual(parse_building_floor(""), ("Bilinmiyor", "Bilinmiyor"))


if __name__ == "__main__":
    unittest.main()
