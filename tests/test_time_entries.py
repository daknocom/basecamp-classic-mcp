import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import server


def entry(hours, entry_id="7"):
    return ET.fromstring(
        f"<time-entry><id>{entry_id}</id><project-id>1</project-id>"
        f"<person-id>2</person-id><date>2026-11-16</date>"
        f"<hours>{hours}</hours><description>Adjustment</description></time-entry>"
    )


class TimeEntryTests(unittest.TestCase):
    @patch("server._send", return_value=(entry(-1.5), {}))
    @patch("server._paged", return_value=([], False))
    def test_signed_hours_are_sent_without_changing_sign(self, paged, send):
        for hours in (-1.5, 1.5):
            with self.subTest(hours=hours):
                result = server.create_time_entry(
                    1, "2026-11-16", hours, "Adjustment", person_id=2
                )
                payload = ET.fromstring(send.call_args.args[2])
                self.assertEqual(float(payload.findtext("hours")), hours)
                self.assertEqual(payload.findtext("person-id"), "2")
                self.assertFalse(result["duplicate"])

    @patch("server._send")
    @patch("server._paged")
    def test_invalid_hours_do_not_contact_basecamp(self, paged, send):
        for hours in (0, -0.0, float("nan"), float("inf"), float("-inf")):
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                server.create_time_entry(1, "2026-11-16", hours, "Adjustment")
        paged.assert_not_called()
        send.assert_not_called()

    @patch("server._send")
    @patch("server._paged", return_value=([entry(-1.5)], False))
    def test_negative_duplicate_is_not_created_again(self, paged, send):
        result = server.create_time_entry(
            1, "2026-11-16", -1.5, "Adjustment", person_id=2
        )
        self.assertTrue(result["duplicate"])
        send.assert_not_called()

    @patch("server._send", return_value=(entry(-1.5), {}))
    @patch("server._paged", return_value=([entry(1.5)], False))
    def test_positive_entry_does_not_block_negative_adjustment(self, paged, send):
        result = server.create_time_entry(1, "2026-11-16", -1.5, "Adjustment")
        self.assertFalse(result["duplicate"])
        send.assert_called_once()

    @patch("server._paged", return_value=([entry(2), entry(-1.5, "8")], False))
    def test_report_subtracts_negative_hours(self, paged):
        result = server.list_time_entries(project_id=1)
        self.assertEqual(result["total_hours"], 0.5)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["entries"][1]["hours"], "-1.5")


if __name__ == "__main__":
    unittest.main()
