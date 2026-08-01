import unittest

from tests._fake_hou import install

install()

from bridge.handlers.exec import _execute_code, _extract_last_expr


class ExecutionTests(unittest.TestCase):
    def test_last_expression_and_semicolon(self):
        setup, expression = _extract_last_expr("value = 4; value * 3")
        namespace = {}
        exec(setup, namespace)
        self.assertEqual(eval(expression, namespace), 12)

    def test_function_uses_shared_namespace(self):
        report = _execute_code(
            "base = 7\ndef compute():\n    return base + 5\ncompute()"
        )
        self.assertTrue(report["success"])
        self.assertEqual(report["result"], 12)
        self.assertIn("receipt", report)
        self.assertIn("elapsed", report)

    def test_explicit_return_and_streams(self):
        report = _execute_code(
            "import sys\nprint('out')\nprint('err', file=sys.stderr)\nanswer = 42",
            return_expr="answer",
        )
        self.assertEqual(report["result"], 42)
        self.assertEqual(report["output"].strip(), "out")
        self.assertEqual(report["stderr"].strip(), "err")

    def test_error_is_structured(self):
        report = _execute_code("raise ValueError('broken')")
        self.assertFalse(report["success"])
        self.assertIn("ValueError: broken", report["error"])

    def test_large_result_becomes_artifact(self):
        report = _execute_code("'x' * 1000", artifact_threshold=10)
        self.assertTrue(report["success"])
        self.assertIn("$artifact", report["result"])


if __name__ == "__main__":
    unittest.main()
