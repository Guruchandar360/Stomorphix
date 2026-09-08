import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.analyzer import normalize_polygon, write_count_csv
from app.batch_jobs import batch_manager
from app.explainer import deterministic_explanation


class CountingOutputTests(unittest.TestCase):
    def test_polygon_validation_preserves_detection_geometry(self):
        points = np.array([[10.2, 10.1], [30.4, 10.2], [30.1, 30.3], [10.0, 30.2]])

        normalized, label_position = normalize_polygon(points)

        self.assertEqual(normalized.tolist(), [[10, 10], [30, 10], [30, 30], [10, 30]])
        self.assertEqual(label_position, (20, 20))

    def test_count_report_contains_only_filename_and_count(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "count.csv"
            write_count_csv(report, "sample.jpg", 12)

            with report.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(rows, [{"filename": "sample.jpg", "stomata_count": "12"}])

    def test_batch_summary_contains_only_count_statistics(self):
        summary = batch_manager._build_summary(
            [{"stomata_count": 3}, {"stomata_count": 5}],
            failed=1,
        )

        self.assertEqual(
            summary,
            {
                "completed_images": 2,
                "failed_images": 1,
                "total_stomata": 8,
                "avg_stomata_per_image": 4.0,
            },
        )

    def test_fallback_explanation_reports_only_count_context(self):
        explanation = deterministic_explanation(
            {
                "stomata_count": 8,
                "confidence": 0.5,
                "iou": 0.3,
                "magnification": 40,
                "summary": {"stomata_count": 8},
            }
        )

        self.assertIn("detected 8 stomata", explanation)
        self.assertNotIn("area", explanation.lower())
        self.assertNotIn("length", explanation.lower())
        self.assertNotIn("width", explanation.lower())


if __name__ == "__main__":
    unittest.main()
