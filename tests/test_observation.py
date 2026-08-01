import unittest

from tests._fake_hou import install

install()

from bridge.handlers.scene import _diff_snapshots


class ObservationDiffTests(unittest.TestCase):
    def test_add_remove_change_and_rename(self):
        before = {
            "/obj/a": {"session_id": 10, "type": "geo", "parms": {"tx": 1}},
            "/obj/remove": {"session_id": 11, "type": "geo"},
            "/obj/change": {"session_id": 12, "type": "geo", "parms": {"tx": 0}},
        }
        after = {
            "/obj/renamed": {"session_id": 10, "type": "geo", "parms": {"tx": 1}},
            "/obj/add": {"session_id": 13, "type": "geo"},
            "/obj/change": {"session_id": 12, "type": "geo", "parms": {"tx": 2}},
        }
        diff = _diff_snapshots(before, after)
        self.assertEqual(diff["added"], ["/obj/add"])
        self.assertEqual(diff["removed"], ["/obj/remove"])
        self.assertEqual(diff["renamed"][0]["from"], "/obj/a")
        self.assertEqual(diff["renamed"][0]["to"], "/obj/renamed")
        self.assertEqual(diff["changed"][0]["fields"], ["parms"])
        self.assertTrue(diff["has_changes"])

    def test_identical_snapshots(self):
        state = {"/obj/a": {"session_id": 1, "type": "geo"}}
        diff = _diff_snapshots(state, dict(state))
        self.assertFalse(diff["has_changes"])


if __name__ == "__main__":
    unittest.main()
