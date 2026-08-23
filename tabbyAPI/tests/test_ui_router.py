import unittest

from ui.router import UI_PREFIX, legacy_router, router


class UiRoutePrefixTests(unittest.TestCase):
    def test_ui_lives_under_v1(self):
        self.assertEqual(UI_PREFIX, "/v1/ui")
        self.assertEqual(router.prefix, "/v1/ui")

    def test_routes_include_login_and_assets(self):
        paths = {route.path for route in router.routes}
        self.assertIn("/v1/ui/login", paths)
        self.assertIn("/v1/ui/", paths)
        self.assertIn("/v1/ui/assets/{name}", paths)
        self.assertIn("/v1/ui/auth/login", paths)
        self.assertIn("/v1/ui/gallery/file/{name}", paths)

    def test_legacy_ui_redirect_routes_exist(self):
        paths = {route.path for route in legacy_router.routes}
        self.assertIn("/ui", paths)
        self.assertIn("/ui/", paths)
        self.assertIn("/ui/{rest:path}", paths)


if __name__ == "__main__":
    unittest.main()
