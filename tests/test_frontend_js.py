import os
import unittest


class FrontendJsTest(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.getcwd()
        self.app_js_path = os.path.join(self.repo_root, 'assets', 'js', 'app.js')
        self.template_path = os.path.join(self.repo_root, 'assets', 'html', 'template.html')

    def test_new_viewer_display_code_is_used(self):
        # Ensure the front-end uses the new three-cad-viewer API (no legacy CadViewer compatibility).
        self.assertTrue(os.path.exists(self.app_js_path), f"Missing {self.app_js_path}")
        with open(self.app_js_path, 'r', encoding='utf-8') as f:
            js = f.read()

        # 1) Use named imports for new API and use local self-hosted module (no @latest, no CDN)
        self.assertIn("import { Viewer, Display }", js)
        self.assertIn("/assets/js/vendor/three-cad-viewer.esm.js", js)
        self.assertNotIn("three-cad-viewer@latest", js)
        self.assertNotIn("https://unpkg.com/three-cad-viewer", js)

        # 2) No legacy compatibility helpers or CadViewer constructor anywhere
        for legacy in [
            "resolveCadViewer",
            "CadViewer",
            "mod.CadViewer",
            "mod.default && mod.default.CadViewer",
            "ThreeCadViewer",
        ]:
            self.assertNotIn(legacy, js)

        # 3) Expect modern Display/Viewer creation and options blocks
        self.assertIn("new Display(", js)
        self.assertIn("new Viewer(", js)
        self.assertIn("defaultDisplayOptions", js)
        self.assertIn("defaultRenderOptions", js)
        self.assertIn("defaultViewerOptions", js)

        # 4) edgeColor is allowed in new render options (matches the official skeleton)
        self.assertIn("edgeColor:", js)

        # 5) Basic load helpers should use new viewer methods if present but may fallback gracefully
        for method in ["addModelUrl", "loadModelFromUrl", "loadUrl", "loadModel", "openUrl"]:
            self.assertIn(method, js)

        # 6) DOMContentLoaded wiring present
        self.assertIn("document.addEventListener('DOMContentLoaded', initWorkCards)", js)

        # 7) Avoid noisy console.log and no client-console bridge remnants
        self.assertNotIn("console.log(", js)
        self.assertNotIn("/__console", js)
        self.assertNotIn("setupConsoleBridge", js)

        # 8) Template should modulepreload the local self-hosted ESM (no CDN, no @latest)
        self.assertTrue(os.path.exists(self.template_path), f"Missing {self.template_path}")
        with open(self.template_path, 'r', encoding='utf-8') as tf:
            tpl = tf.read()
        self.assertIn("/assets/js/vendor/three-cad-viewer.esm.js", tpl)
        # CSS should be loaded from vendor folder as well
        self.assertIn("/assets/css/vendor/three-cad-viewer.css", tpl)
        self.assertNotIn("three-cad-viewer@latest", tpl)
        self.assertNotIn("https://unpkg.com/three-cad-viewer", tpl)


if __name__ == '__main__':
    unittest.main()
