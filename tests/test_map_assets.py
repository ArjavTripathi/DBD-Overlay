from dbd_overlay.core.catalog import load_maps
from dbd_overlay.features.map_overlay.assets import MapImages

CAT = load_maps()


def make(tmp_path, files):
    for f in files:
        p = tmp_path / "maps" / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    return MapImages(tmp_path, CAT)


def test_loose_names_resolve(tmp_path):
    imgs = make(tmp_path, [
        "Autohaven Wreckers/Azarov’s Resting Place.webp",   # curly apostrophe
        "Coldwind Farm/Rancid Abbatoir.webp",               # typo
        "Red Forest/Temple of Purgation.webp",              # missing 'The'
        "Sleepless District/Tricksters Delusion.webp",      # missing apostrophe
        "The MacMillan Estate/Ironworks Of Misery.png",     # case
        "Léry's Memorial Institute/Treatment Theatre.jpg",  # accent in folder
    ])
    for name in ["Azarov's Resting Place", "Rancid Abattoir", "The Temple of Purgation",
                 "Trickster's Delusion", "Ironworks of Misery", "Treatment Theatre"]:
        assert imgs.find(CAT.find_map(name)) is not None, name


def test_similar_names_in_same_realm_not_confused(tmp_path):
    imgs = make(tmp_path, ["Raccoon City/Raccoon City Police Station East Wing.webp"])
    assert imgs.find(CAT.find_map("Raccoon City Police Station West Wing")) is None


def test_missing_and_unused(tmp_path):
    imgs = make(tmp_path, ["Backwater Swamp/The Pale Rose.png", "Backwater Swamp/notes.txt", "Junk/Nope.png"])
    missing, unused = imgs.report()
    assert CAT.find_map("The Pale Rose") not in missing
    assert CAT.find_map("Grim Pantry") in missing
    assert [p.name for p in unused] == ["Nope.png"]


def test_no_assets_dir(tmp_path):
    assert MapImages(tmp_path / "nope", CAT).find(CAT.find_map("The Pale Rose")) is None
