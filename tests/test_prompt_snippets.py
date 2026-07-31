from __future__ import annotations

import hashlib
from uuid import uuid4


async def _workspace(client, name: str = "Prompt library") -> dict:
    response = await client.post("/api/workspaces", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def test_prompt_snippet_crud_deduplicates_and_records_usage(client) -> None:
    workspace = await _workspace(client)
    path = f"/api/workspaces/{workspace['id']}/prompt-snippets"
    content = "Review the current diff and list only actionable regressions."

    created = await client.post(path, json={"content": f"\n{content}\n"})
    duplicate = await client.post(path, json={"content": content})

    assert created.status_code == 201, created.text
    assert duplicate.status_code == 201, duplicate.text
    prompt = created.json()
    assert duplicate.json()["id"] == prompt["id"]
    assert prompt["workspace_id"] == workspace["id"]
    assert prompt["content"] == content
    assert prompt["content_sha256"] == hashlib.sha256(content.encode()).hexdigest()
    assert prompt["use_count"] == 0
    assert prompt["last_used_at"] is None

    listed = await client.get(path)
    assert listed.status_code == 200, listed.text
    assert listed.json()["schema_version"] == "prompt_snippet_list.v1"
    assert [item["id"] for item in listed.json()["prompts"]] == [prompt["id"]]

    usage = await client.post(
        f"{path}/usage",
        json={"prompt_ids": [prompt["id"], prompt["id"], str(uuid4())]},
    )
    assert usage.status_code == 200, usage.text
    assert usage.json()["updated"] == 1

    used = (await client.get(path)).json()["prompts"][0]
    assert used["use_count"] == 1
    assert used["last_used_at"] is not None

    deleted = await client.delete(f"{path}/{prompt['id']}")
    assert deleted.status_code == 204, deleted.text
    assert (await client.get(path)).json()["prompts"] == []


async def test_prompt_snippets_are_workspace_scoped_and_validate_content(client) -> None:
    first = await _workspace(client, "First prompt project")
    second = await _workspace(client, "Second prompt project")
    first_path = f"/api/workspaces/{first['id']}/prompt-snippets"
    second_path = f"/api/workspaces/{second['id']}/prompt-snippets"

    blank = await client.post(first_path, json={"content": " \n\t "})
    too_large = await client.post(first_path, json={"content": "x" * 20_001})
    assert blank.status_code == 422
    assert too_large.status_code == 422

    created = await client.post(first_path, json={"content": "First workspace only"})
    assert created.status_code == 201, created.text
    prompt_id = created.json()["id"]
    assert (await client.get(second_path)).json()["prompts"] == []

    wrong_workspace_delete = await client.delete(f"{second_path}/{prompt_id}")
    assert wrong_workspace_delete.status_code == 404
    assert len((await client.get(first_path)).json()["prompts"]) == 1


async def test_workspace_delete_removes_prompt_snippets(client) -> None:
    workspace = await _workspace(client, "Disposable prompt project")
    workspace_id = workspace["id"]
    prompt_path = f"/api/workspaces/{workspace_id}/prompt-snippets"
    assert (await client.post(prompt_path, json={"content": "Temporary prompt"})).status_code == 201

    archived = await client.patch(
        f"/api/workspaces/{workspace_id}",
        json={"status": "archived"},
    )
    assert archived.status_code == 200, archived.text
    deleted = await client.delete(
        f"/api/workspaces/{workspace_id}",
        params={"confirm_name": "Disposable prompt project"},
    )
    assert deleted.status_code == 204, deleted.text
