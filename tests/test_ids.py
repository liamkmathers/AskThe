import pytest

from askthe.core import ids


def test_ids_are_deterministic_and_nested():
    vid = ids.video_id("iron-snail", "VtBFkFZoaII")
    assert vid == "iron-snail:VtBFkFZoaII"
    assert ids.segment_id(vid, 7) == "iron-snail:VtBFkFZoaII:s0007"
    assert ids.claim_id(vid, 12) == "iron-snail:VtBFkFZoaII:c0012"


def test_entity_ids_normalise_names():
    assert ids.entity_id("iron-snail", "Fjällräven Kånken") == "iron-snail:e:fjallraven-kanken"
    assert ids.entity_id("iron-snail", "L.L.Bean") == "iron-snail:e:l-l-bean"
    eid = ids.entity_id("iron-snail", "Patagonia Retro-X")
    assert ids.version_id(eid, "Vintage, made in USA (1988)") == (
        "iron-snail:e:patagonia-retro-x:v:vintage-made-in-usa-1988"
    )


def test_slugify_rejects_empty_results():
    with pytest.raises(ValueError):
        ids.slugify("!!!")
