"""The center consumes the DR catalog contract, not an independently edited schema."""
from pathlib import Path
import pytest
from app.schemas.catalog import ResourcePublish
from test_catalog_resource_binding import _body, _column

def test_catalog_standard_snapshot_matches_canonical_dr():
    root = Path(__file__).resolve().parents[2]
    for name in ('metadata.py', 'standard.py'):
        assert (root/'backend/app/resource_standard'/name).read_text() == (root/'cnt-services/data-resource/data_resource/domain'/name).read_text()

@pytest.mark.parametrize('patch', [
    {'contact_information': 'abcdefghijk'},
    {'time_range': '2026-12-01至2026-01-01'},
    {'theme_code': 'ZI'},
    {'data_modalities': ['not-a-standard-code']},
    {'annotation_info': {'status': 'none', 'types': ['classification']}},
])
def test_center_enforces_dr_metadata(patch):
    value = _body([_column()]).model_dump()
    with pytest.raises(ValueError):
        ResourcePublish(**{**value, **patch})
