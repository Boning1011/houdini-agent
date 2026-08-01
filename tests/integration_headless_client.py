"""Client-side contract checks for a disposable hython bridge."""

import json
import sys

from bridge.client import HoudiniClient


def main(port):
    client = HoudiniClient(port=port, timeout=10)
    status = client.status()
    assert status["bridge_protocol"] >= 2
    assert status["capabilities"]["jobs"]
    assert not status["capabilities"]["ui"]

    execution = client.exec(
        "base = 8\ndef compute():\n    return base + 5",
        return_expr="compute()",
        detailed=True,
    )
    assert execution["result"] == 13
    assert execution["receipt"]["operation"]["success"]

    first = client.observe_scene("/obj", depth=1)
    mutation = client.exec(
        "hou.node('/obj').createNode('geo', 'agent_contract_probe')",
        observe=[{"path": "/obj", "depth": 1}],
        detailed=True,
    )
    assert mutation["receipt"]["observed"][0]["diff"]["has_changes"]
    second = client.observe_scene(
        "/obj", depth=1, since=first["token"], include_nodes=False
    )
    assert "/obj/agent_contract_probe" in second["diff"]["added"]
    current = client.observe_scene("/obj", depth=1)
    session_id = current["nodes"]["/obj/agent_contract_probe"]["session_id"]
    assert client.node_by_session_id(session_id) == "/obj/agent_contract_probe"

    artifact = client.evaluate("{'data': list(range(2000))}", artifact_threshold=64)
    restored = client.read_artifact_all(artifact)
    assert restored["data"][-1] == 1999

    job = client.start_job("import time\ntime.sleep(0.2)\n21 * 2")
    final = client.wait_job(job, timeout=10, poll_interval=0.05)
    assert final["state"] == "succeeded"
    assert final["result"]["result"] == 42
    assert final["result"]["receipt"]["operation"]["success"]

    print(json.dumps({
        "houdini_version": status["houdini_version"],
        "python_version": status["python_version"],
        "capabilities": status["capabilities"],
        "scene_diff": second["diff"],
        "job_state": final["state"],
        "artifact_size": artifact["size"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(int(sys.argv[1]))
