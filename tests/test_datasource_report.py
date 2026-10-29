from app.routers.catalog import router


def test_center_catalog_exposes_no_datasource_lifecycle_routes():
    paths = {route.path for route in router.routes}
    assert not any(path.startswith("/catalog/datasources") for path in paths)
    assert "/catalog/resources/publish" in paths
