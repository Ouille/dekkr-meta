"""Tests des fonctions pures de matching (aucune base requise).

Chaque cas provient d'un morceau réel qui échouait sur une collection de
1105 fichiers. Les expressions régulières en jeu sont délicates : elles doivent
retirer le bruit générique sans effacer ce qui distingue deux versions.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from matcher import normalize, normalize_artist, _artist_score, _tokens  # noqa: E402


class TestNormalize:
    @pytest.mark.parametrize("raw, expected", [
        ("Tempelhof", "tempelhof"),
        ("  Tempelhof  ", "tempelhof"),
        ("01 - Kungsholmen", "kungsholmen"),
        ("03. Kungsholmen", "kungsholmen"),
    ])
    def test_base(self, raw, expected):
        assert normalize(raw) == expected

    @pytest.mark.parametrize("raw", [
        "Weltschmerz (Original Mix)",
        "Weltschmerz Original Mix",
        "Weltschmerz Original_Mix",
        "Weltschmerz - Original Mix",
        "Weltschmerz (Extended Mix)",
        "Weltschmerz Radio Edit",
    ])
    def test_bruit_generique_retire(self, raw):
        """Les mentions génériques disparaissent, avec ou sans parenthèses."""
        assert normalize(raw) == "weltschmerz"

    @pytest.mark.parametrize("raw", [
        "Tempelhof (Joachim Pastor Remix)",
        "Tempelhof Joachim Pastor Remix",
        "Innerbloom (H.O.S.H Remix)",
    ])
    def test_remix_nomme_conserve(self, raw):
        """Un remix nommé distingue une version et doit survivre : l'effacer
        rabattrait le morceau sur l'original, une autre sortie Discogs.
        Les entrées Discogs le portent aussi — les deux côtés se rejoignent."""
        out = normalize(raw)
        assert "remix" in out
        assert out != "tempelhof"

    def test_remix_generique_seul_retire(self):
        """Sans nom d'auteur, « (Remix) » n'apprend rien."""
        assert normalize("Tempelhof (Remix)") == "tempelhof"

    @pytest.mark.parametrize("a, b", [
        ("Rüfüs", "RUFUS"),
        ("Östermalm", "Ostermalm"),
        ("Jesper Dahlbäck", "Jesper Dahlback"),
        ("Sébastien Léger", "Sebastien Leger"),
    ])
    def test_diacritiques_replies(self, a, b):
        """L'index FTS replie les diacritiques ; le score doit faire de même."""
        assert normalize(a) == normalize(b)

    def test_featuring_retire(self):
        assert normalize("Silence feat. Kollmorgen") == "silence"
        assert normalize("Silence (feat. Kollmorgen)") == "silence"

    def test_esperluette_conservee(self):
        assert "&" in normalize("Mr. James Barth & A.D.")

    def test_entree_vide(self):
        assert normalize("") == ""
        assert normalize(None) == ""


class TestArtistScore:
    def test_identique(self):
        assert _artist_score("Gramatik", "gramatik") == 100.0

    @pytest.mark.parametrize("discogs, fichier", [
        ("Niiche", "cari golden niiche"),
        ("Miss NatNat", "wolfgang lohr miss natnat artenvielfalt"),
        ("Doorly", "hauswerks doorly"),
        ("Noisia", "noisia the upbeats"),
    ])
    def test_multi_artistes(self, discogs, fichier):
        """Le fichier liste tous les intervenants, Discogs le principal seul :
        les noms surnuméraires ne doivent pas pénaliser."""
        assert _artist_score(discogs, fichier) == 100.0

    @pytest.mark.parametrize("discogs, fichier", [
        ("Jackie McLean", "marcellus wallace"),
        ("Andy Morris", "adam beyer joseph capriati"),
        ("White Drugs", "le corbusier"),
        ("Blokkmonsta", "township rebellion"),
    ])
    def test_artiste_different_reste_bas(self, discogs, fichier):
        """Ces cas produisaient de faux positifs si l'on baissait le seuil."""
        assert _artist_score(discogs, fichier) < 85

    @pytest.mark.parametrize("court", ["The", "DJ", "A", "Le"])
    def test_candidat_trop_court_non_promu(self, court):
        """Un nom trop banal est contenu partout : sans garde-fou il
        s'apparierait avec n'importe quel artiste."""
        assert _artist_score(court, "the chemical brothers") < 100.0

    @pytest.mark.parametrize("discogs, fichier", [
        ("Yak (19)", "yak"),
        ("PAX (11)", "pax"),
        ("Guz (12)", "guz"),
        ("Culture Shock (2)", "culture shock sub focus"),
        ("Omis (2)", "omis italy"),
    ])
    def test_suffixe_homonymie_ignore(self, discogs, fichier):
        """« (19) » numérote les homonymes chez Discogs : c'est sa
        comptabilité interne, pas le nom de l'artiste. Les chiffres survivant
        au découpage en jetons, le garder faisait chuter le score."""
        assert _artist_score(discogs, fichier) == 100.0

    @pytest.mark.parametrize("discogs, fichier", [
        ("Robert Hood", "moon rocket"),
        ("Reminder", "strinner"),
    ])
    def test_artiste_etranger_sous_le_plancher(self, discogs, fichier):
        """Ces deux-là passaient sur la seule force du titre : un titre
        parfait rapporte 60 des 100 points. Ils doivent rester sous le
        plancher de 70."""
        assert _artist_score(discogs, fichier) < 70


class TestNormalizeArtist:
    def test_suffixe_retire(self):
        assert normalize_artist("Yak (19)") == "yak"
        assert normalize_artist("Culture Shock (2)") == "culture shock"

    def test_parenthese_non_numerique_conservee(self):
        """« (Italy) » vient du fichier et distingue un homonyme :
        contrairement à « (2) », il porte de l'information."""
        assert "italy" in normalize_artist("Omis (Italy)")

    def test_sans_suffixe_inchange(self):
        assert normalize_artist("Daft Punk") == normalize("Daft Punk")


class TestTokens:
    def test_mots_courts_ecartes(self):
        assert "a" not in _tokens("a chemical brother")

    def test_chiffres_conserves(self):
        assert "7" in _tokens("studio 7")
