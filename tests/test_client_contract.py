import unittest

from bridge.client import HoudiniClient


class RecordingClient(HoudiniClient):
    def __init__(self):
        self.calls = []
        self.responses = {}

    def _post(self, path, body):
        self.calls.append((path, body))
        return self.responses.get(path, {"success": True, "result": {}})


class ClientContractTests(unittest.TestCase):
    def test_exec_exposes_generic_options(self):
        client = RecordingClient()
        client.responses["/exec"] = {
            "success": True,
            "result": 5,
            "receipt": {"id": "r"},
        }
        result = client.exec(
            "value = 5",
            return_expr="value",
            observe=["/obj"],
            artifact_threshold=10,
            detailed=True,
        )
        self.assertEqual(result["result"], 5)
        path, body = client.calls[-1]
        self.assertEqual(path, "/exec")
        self.assertEqual(body["return_expr"], "value")
        self.assertEqual(body["observe"], ["/obj"])

    def test_observe_scene_uses_token(self):
        client = RecordingClient()
        client.responses["/scene_observe"] = {
            "success": True,
            "result": {"token": "new", "diff": {"has_changes": False}},
        }
        result = client.observe_scene("/obj", since="old", include_nodes=False)
        self.assertEqual(result["token"], "new")
        self.assertEqual(client.calls[-1][1]["since"], "old")

    def test_capture_is_discoverable_alias(self):
        client = RecordingClient()
        client.responses["/screenshot"] = {
            "success": True,
            "result": {"target": "NetworkEditor"},
        }
        result = client.capture("network_editor")
        self.assertEqual(result["target"], "NetworkEditor")
        self.assertEqual(client.calls[-1][1]["target"], "network_editor")

    def test_job_methods_use_stable_id(self):
        client = RecordingClient()
        client.responses["/job/start"] = {
            "success": True,
            "result": {"id": "job", "state": "queued"},
        }
        job = client.start_job("3 + 4")
        self.assertEqual(job["id"], "job")
        client.responses["/job/status"] = {
            "success": True,
            "result": {"id": "job", "state": "succeeded", "result": 7},
        }
        self.assertEqual(client.job_status(job)["state"], "succeeded")


if __name__ == "__main__":
    unittest.main()
