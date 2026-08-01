import os
import unittest

from bridge import artifacts


class ArtifactTests(unittest.TestCase):
    def test_small_values_stay_inline(self):
        self.assertEqual(artifacts.externalize({"value": 3}, threshold=100), {"value": 3})

    def test_large_json_round_trip(self):
        value = {"items": list(range(200))}
        descriptor = artifacts.externalize(value, threshold=32)
        self.assertTrue(artifacts.is_descriptor(descriptor))
        self.assertEqual(descriptor["kind"], "json")

        pieces = []
        offset = 0
        while True:
            chunk = artifacts.read(descriptor["$artifact"], offset=offset, limit=17)
            pieces.append(chunk["content"])
            if chunk["eof"]:
                break
            self.assertGreater(chunk["next_offset"], offset)
            offset = chunk["next_offset"]
        import json
        self.assertEqual(json.loads("".join(pieces)), value)

    def test_utf8_chunk_boundaries_are_lossless(self):
        value = "河流 attribute " * 20
        descriptor = artifacts.create(value)
        pieces = []
        offset = 0
        while True:
            chunk = artifacts.read(descriptor["$artifact"], offset=offset, limit=1)
            pieces.append(chunk["content"])
            if chunk["eof"]:
                break
            offset = chunk["next_offset"]
        self.assertEqual("".join(pieces), value)
        self.assertTrue(os.path.isfile(descriptor["path"]))

    def test_binary_round_trip(self):
        value = bytes(range(256))
        descriptor = artifacts.create(value)
        chunk = artifacts.read(descriptor["$artifact"], limit=512)
        import base64
        self.assertEqual(base64.b64decode(chunk["content"]), value)


if __name__ == "__main__":
    unittest.main()
