import pytest
from pydantic import ValidationError

from askthe.core import ids
from askthe.core.models import (
    Aspect,
    Basis,
    Claim,
    ClaimKind,
    HeldBy,
    HeldByKind,
    Price,
    PriceType,
    Stance,
)
from tests import factories as f

VID = ids.video_id(f.CREATOR, "vid1")


def test_claim_defaults_to_the_creators_firm_view():
    claim = f.claim(VID)
    assert claim.is_creators_view
    assert claim.certainty == "firm"
    assert not claim.sponsored


def test_reported_view_is_not_the_creators():
    claim = f.claim(VID, held_by=HeldBy(kind=HeldByKind.OTHERS))
    assert not claim.is_creators_view


def test_personal_taste_claim_round_trips_through_json():
    claim = f.claim(
        VID,
        kind=ClaimKind.PREFERENCE,
        aspect=Aspect.LOOKS,
        stance=Stance.POSITIVE,
        basis=Basis.PERSONAL_TASTE,
        he_wears_it=True,
        price=Price(
            amount=64,
            amount_max=80,
            currency="USD",
            type=PriceType.SALE,
            as_said="retails for $80, I paid 64",
        ),
    )
    assert Claim.model_validate_json(claim.model_dump_json()) == claim


def test_sponsorship_claims_must_be_marked_sponsored():
    with pytest.raises(ValidationError, match="sponsored"):
        f.claim(VID, kind=ClaimKind.SPONSORSHIP)
    assert f.claim(VID, kind=ClaimKind.SPONSORSHIP, sponsored=True).sponsored


def test_claim_needs_a_quote_and_a_segment():
    with pytest.raises(ValidationError):
        f.claim(VID, quote="")
    with pytest.raises(ValidationError):
        f.claim(VID, segment_ids=[])


def test_time_ranges_must_be_ordered():
    with pytest.raises(ValidationError):
        f.claim(VID, start_s=20, end_s=10)
    with pytest.raises(ValidationError):
        f.segment(VID, start_s=20, end_s=10)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        f.claim(VID, mood="happy")


def test_creator_slug_must_be_url_safe():
    with pytest.raises(ValidationError):
        f.creator(slug="Iron Snail")
