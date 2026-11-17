import httpx
import pytest

from scripts.remote_admin_smoke import cleanup_test_asset


async def test_absent_inventory_and_fresh_asset_path_do_not_delete_anything():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/admin/Files":
            return httpx.Response(200, json={"data": [{"hash": "b" * 64}]})
        return httpx.Response(404)

    async with httpx.AsyncClient(
        base_url="https://ctf.test", transport=httpx.MockTransport(handler)
    ) as client:
        result = await cleanup_test_asset(client, "a" * 64, "test-run")
    assert result["attachmentAbsent"] is True
    assert all(request.method == "GET" for request in requests)
    assert requests[-1].headers["cache-control"] == "no-cache"
    assert requests[-1].url.path.startswith("/assets/" + "a" * 64 + "/cleanup-test-run-")


@pytest.mark.parametrize("delete_status", [200, 404])
async def test_cleanup_verifies_absence_after_delete_or_already_deleted(delete_status):
    deleted = False
    requests = []

    def handler(request):
        nonlocal deleted
        requests.append(request)
        if request.method == "DELETE":
            deleted = True
            return httpx.Response(delete_status)
        if request.url.path == "/api/admin/Files":
            return httpx.Response(200, json={"data": [] if deleted else [{"hash": "a" * 64}]})
        return httpx.Response(404)

    async with httpx.AsyncClient(
        base_url="https://ctf.test", transport=httpx.MockTransport(handler)
    ) as client:
        assert (await cleanup_test_asset(client, "a" * 64, "run"))["attachmentInventoryAbsent"]
    assert [request.url.path for request in requests if request.method == "DELETE"] == [
        "/api/assets/" + "a" * 64
    ]


async def test_orphan_file_is_not_reported_as_cleaned():
    def handler(request):
        if request.url.path == "/api/admin/Files":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, content=b"file still exists")

    async with httpx.AsyncClient(
        base_url="https://ctf.test", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(AssertionError, match="origin storage"):
            await cleanup_test_asset(client, "a" * 64, "run")
