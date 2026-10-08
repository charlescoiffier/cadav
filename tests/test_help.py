from cadav.client.help import binding_label, key_label, render_help, shortcut_rows


def test_key_labels():
    assert key_label("ctrl+n") == "Ctrl+N"
    assert key_label("escape") == "Échap"
    assert key_label("f1") == "F1"
    assert key_label("enter") == "Entrée"
    assert key_label("shift+tab") == "Maj+Tab"
    assert key_label("ctrl+shift+s") == "Ctrl+Maj+S"


def test_binding_labels():
    assert binding_label("f1,ctrl+f") == "F1 ou Ctrl+F"
    assert binding_label("up", "↑↓") == "↑↓"
    assert binding_label("enter,space") == "Entrée ou Espace"


def test_shortcut_rows_keep_one_row_per_description():
    rows = shortcut_rows(
        [
            ("ctrl+s", "Envoyer", None),
            ("escape", "Retour", None),
            ("escape", "Retour", None),  # the same action bound twice
            ("up", "Naviguer", "↑↓"),
            ("down", "", None),  # no description: hidden
            ("f1", "Aide", None),
            ("ctrl+f", "Aide", None),  # two keys for one action
        ]
    )
    assert rows == [("Ctrl+S", "Envoyer"), ("Échap", "Retour"), ("↑↓", "Naviguer"), ("F1 ou Ctrl+F", "Aide")]


def test_render_help_has_every_section():
    text = render_help(
        "Lobby", [("Ctrl+N", "Nouvelle partie")], "0.5.0", "/home/x/.config/cadav/config.json", "", "galaxy",
        muted="grey", accent="pink", secondary="purple",
    ).plain
    for expected in ("Le jeu", "Au clavier", "Raccourcis de cet écran (Lobby)", "Ctrl+N", "Nouvelle partie",
                     "0.5.0", "config.json", "(par défaut)", "galaxy", "Échap ou F1"):
        assert expected in text
    empty = render_help("X", [], "1", "c", "d", "t", muted="grey", accent="pink", secondary="purple").plain
    assert "Aucun raccourci particulier." in empty
