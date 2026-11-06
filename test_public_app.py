"""Publishing checks; all sample data are synthetic and kept in memory."""

import ast
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

import numpy as np
from streamlit.testing.v1 import AppTest

import app


def synthetic_batch_ui():
    from io import BytesIO
    from unittest.mock import patch

    import app
    import numpy as np

    def upload(label, **kwargs):
        if label == "Upload metadata (CSV or Excel)":
            metadata = BytesIO(
                b"ID,Ixx,Ixx/Cy,Alternative Ixx/Cy,CMy[mm],CMx[mm],Genotype,Age,Sex\n"
                b"1234,0.1,0.2,0.25,2,3,Control,6,F\n"
            )
            metadata.name = "synthetic_metadata.csv"
            return metadata
        if label != "Upload CSV files":
            return None
        displacement = np.linspace(0, 0.8, 401)
        force = np.where(displacement <= .4, 80 * displacement, 32 + 16 * (displacement - .4))
        force[displacement > .7] = 36.8 - 100 * (displacement[displacement > .7] - .7)
        rows = ["export", "", "", ",1234"] + [""] * 6
        rows += [f",{x},{y}" for x, y in zip(displacement, force)]
        sample = BytesIO("\n".join(rows).encode())
        sample.name = "synthetic_1234.csv"
        return [sample]

    # Exercise exports without creating any document artifacts.
    with patch.object(app.st, "file_uploader", side_effect=upload), \
            patch.object(app, "dataframe_to_xlsx_bytes", return_value=b"test-xlsx"), \
            patch.object(app, "generate_results_report_pdf", return_value=b"test-pdf"), \
            patch.object(app, "narrative_text_to_doc_bytes", return_value=b"test-doc"), \
            patch.object(app, "figure_to_bytes", return_value=b"test-png"):
        app.main()


class PublishingTests(TestCase):
    def tearDown(self):
        app.plt.close("all")

    def test_result_downloads_are_in_memory_and_do_not_rerun(self):
        with patch.object(app.st, "download_button") as download, \
                patch.object(Path, "write_bytes", side_effect=AssertionError("Shared disk write")):
            app.result_download("Summary", "results.csv", b"session-one", "text/csv")
            app.result_download("Summary", "results.csv", b"session-two", "text/csv")
        self.assertEqual([call.kwargs["data"] for call in download.call_args_list],
                         [b"session-one", b"session-two"])
        self.assertTrue(all(call.kwargs["on_click"] == "ignore" for call in download.call_args_list))

    def test_shared_static_exports_cannot_be_created(self):
        tree = ast.parse(Path(app.__file__).read_text())
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertNotIn("write_static_download_file", functions)
        self.assertNotIn("static_download_link", functions)
        self.assertFalse(any(isinstance(node, ast.Attribute) and node.attr == "write_bytes"
                             for node in ast.walk(tree)))
        config = Path(__file__).parent / ".streamlit" / "config.toml"
        self.assertIn("enableStaticServing = false", config.read_text())
        self.assertFalse((Path(__file__).parent / "static").exists())

    def test_reset_is_session_local(self):
        state = {"batch_id": 3, "processed_data": ["session-one"], "upload": b"sample"}
        with patch.object(app.st, "session_state", state), \
                patch.object(app.st, "rerun"), \
                patch.object(app.st.cache_data, "clear") as data_clear, \
                patch.object(app.st.cache_resource, "clear") as resource_clear:
            app.reset_application_state()
        self.assertEqual(state, {"batch_id": 4, "app_state_version": app.APP_STATE_VERSION})
        data_clear.assert_not_called()
        resource_clear.assert_not_called()

    def test_all_test_modes_start(self):
        at = AppTest.from_file(str(Path(app.__file__))).run()
        self.assertFalse(at.exception)
        self.assertEqual([tab.label for tab in at.tabs], ["Bone bending", "Tendon tensile test"])
        self.assertEqual(at.session_state["bending_test_type"], app.THREE_POINT)
        at.get("button_group")[0].set_value([app.FOUR_POINT]).run()
        self.assertFalse(at.exception)
        self.assertIn("Loading span L (mm)", [item.label for item in at.number_input])

    def test_fixture_equations_including_crosshead_displacement(self):
        for geometry, expected in [
            (app.BendingGeometry(app.THREE_POINT, 10), .06),
            (app.BendingGeometry(app.FOUR_POINT, 10, 4, app.MIDSPAN), 12 / 264),
            (app.BendingGeometry(app.FOUR_POINT, 10, 4, app.LOADING_POINTS), 6 / 108),
        ]:
            np.testing.assert_allclose(geometry.strain_per_displacement(.5), expected)
            self.assertAlmostEqual(geometry.moment_per_force_mm,
                                   (10 - geometry.effective_loading_span_mm) / 4)

    def test_synthetic_batch_reaches_session_downloads(self):
        at = AppTest.from_function(synthetic_batch_ui, default_timeout=30).run()
        self.assertFalse(at.exception)
        at.get("button_group")[0].set_value([app.THREE_POINT])
        next(button for button in at.button if button.label == "Run batch processing").click().run()
        self.assertFalse(at.exception)
        processed = at.session_state["processed_data"]
        self.assertEqual(len(processed), 1)
        self.assertFalse(processed[0].error)
        self.assertTrue(np.isfinite(processed[0].ultimate_stress_mpa))
        labels = [button.label for button in at.get("download_button")]
        for label in ["Corrected data CSV", "Summary CSV", "Summary Excel", "Group averages CSV", "Methods DOC"]:
            self.assertIn(label, labels)
        self.assertFalse((Path(app.__file__).parent / "static").exists())

    def test_geometry_mapping_changes_require_recalculation(self):
        at = AppTest.from_function(synthetic_batch_ui, default_timeout=30).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key="material_ixx_column").value, "Ixx")
        self.assertEqual(at.selectbox(key="material_ixx_cy_column").value, "Ixx/Cy")
        for key in ("material_ixx_column", "material_ixx_cy_column"):
            self.assertNotIn("CMy[mm]", at.selectbox(key=key).options)
            self.assertNotIn("CMx[mm]", at.selectbox(key=key).options)
        at.get("button_group")[0].set_value([app.THREE_POINT])
        next(button for button in at.button if button.label == "Run batch processing").click().run()
        self.assertFalse(at.exception)
        specimen = at.session_state["processed_data"][0]
        self.assertAlmostEqual(specimen.section_modulus_mm3, .2)
        self.assertAlmostEqual(specimen.c_mm, .5)
        at.get("button_group")[0].set_value([app.THREE_POINT])
        at.selectbox(key="material_ixx_cy_column").set_value("Alternative Ixx/Cy").run()
        self.assertFalse(at.exception)
        self.assertIsNone(at.session_state["processed_data"])
        self.assertTrue(at.session_state["material_inputs_changed"])


if __name__ == "__main__":
    main()
