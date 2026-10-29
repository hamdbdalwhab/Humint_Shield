"""Authenticated downloads for the defensive documentation."""
from __future__ import annotations


async def test_playbook_download(client, auth_headers) -> None:
    """The admin can download the full defensive playbook."""
    response = await client.get("/api/v1/security/playbook", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert "text/markdown" in response.headers["content-type"]
    assert "DEFENSIVE_PLAYBOOK.md" in response.headers["content-disposition"]
    body = response.text
    assert "Sigma" in body
    assert "Incident Response" in body
    assert "Attack Surface Reduction" in body


async def test_usb_guide_download(client, auth_headers) -> None:
    """The safe USB-drop guide is available from the dashboard."""
    response = await client.get("/api/v1/security/usb-guide", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert "text/markdown" in response.headers["content-type"]
    assert "README_USB.md" in response.headers["content-disposition"]
    body = response.text
    assert "راتب_الشهر_القادم" in body
    assert "لا يحتوي" in body


async def test_security_docs_require_authentication(client) -> None:
    """The documents are not public."""
    response = await client.get("/api/v1/security/playbook")
    assert response.status_code == 401
