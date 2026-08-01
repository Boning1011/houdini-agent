import unittest

from bridge import jobs


class JobRegistryTests(unittest.TestCase):
    def setUp(self):
        with jobs._lock:
            jobs._jobs.clear()

    def test_success_lifecycle(self):
        record = jobs.create("test")
        self.assertTrue(jobs.mark_running(record["id"]))
        jobs.finish(record["id"], {"result": 3}, success=True)
        final = jobs.get(record["id"])
        self.assertEqual(final["state"], "succeeded")
        self.assertEqual(final["result"]["result"], 3)

    def test_queued_cancel_is_effective(self):
        record = jobs.create("cancel")
        result = jobs.request_cancel(record["id"])
        self.assertTrue(result["effective"])
        self.assertEqual(jobs.get(record["id"])["state"], "cancelled")
        self.assertFalse(jobs.mark_running(record["id"]))

    def test_running_cancel_is_cooperative(self):
        record = jobs.create("running")
        jobs.mark_running(record["id"])
        result = jobs.request_cancel(record["id"])
        self.assertFalse(result["effective"])
        self.assertTrue(jobs.is_cancel_requested(record["id"]))

    def test_history_pruning_skips_active_jobs(self):
        old_limit = jobs._MAX_JOBS
        jobs._MAX_JOBS = 2
        try:
            active = jobs.create("active")
            jobs.mark_running(active["id"])
            finished = jobs.create("finished")
            jobs.finish(finished["id"], {}, success=True)
            newest = jobs.create("newest")

            ids = [record["id"] for record in jobs.list_jobs()]
            self.assertEqual(ids, [active["id"], newest["id"]])
        finally:
            jobs._MAX_JOBS = old_limit


if __name__ == "__main__":
    unittest.main()
