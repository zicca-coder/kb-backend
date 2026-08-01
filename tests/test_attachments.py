import base64
from typing import Any, AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_openclaw_client
from app.core.errors import OpenClawConnectionError
from app.core.settings import settings
from app.models.message_attachment import MessageAttachment
from app.models.user_agent import UserAgent
from app.schemas.openclaw import (
    AgentProvisionResult,
    AgentRuntimeEnsureReadyResult,
    OpenClawChatResult,
)

REGISTER_URL = "/api/auth/register"
LOGIN_URL = "/api/auth/login"
PASSWORD = "Kb@123456"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
PDF_MINIMAL = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _text_pdf(text: str) -> bytes:
    escaped = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\n".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R "
            b"/Resources << /Font << /F1 4 0 R >> >> "
            b"/MediaBox [0 0 612 792] /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"endstream"
        ),
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


class RecordingOpenClawClient:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.chat_content_parts: list[list[dict[str, Any]] | None] = []
        self.responses_content_parts: list[list[dict[str, Any]]] = []

    async def provision_agent(
        self,
        *,
        external_user_id: int | str,
    ) -> AgentProvisionResult:
        return AgentProvisionResult(agent_id=f"web-user-{external_user_id}")

    async def ensure_agent_runtime_ready(
        self,
        *,
        agent_id: str,
    ) -> AgentRuntimeEnsureReadyResult:
        return AgentRuntimeEnsureReadyResult(
            ok=True,
            agentId=agent_id,
            ready=True,
            refreshed=True,
            retryAfterMs=0,
        )

    async def chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
        session_key: str | None = None,
        content_parts: list[dict[str, Any]] | None = None,
    ) -> OpenClawChatResult:
        self.chat_content_parts.append(content_parts)
        if self.exc is not None:
            raise self.exc
        return OpenClawChatResult(answer="附件回答")

    async def stream_chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
        session_key: str | None = None,
        content_parts: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        self.chat_content_parts.append(content_parts)
        yield "附件回答"

    async def responses_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        content_parts: list[dict[str, Any]],
        session_key: str | None = None,
    ) -> OpenClawChatResult:
        self.responses_content_parts.append(content_parts)
        if self.exc is not None:
            raise self.exc
        return OpenClawChatResult(answer="文件回答")

    async def stream_responses_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        content_parts: list[dict[str, Any]],
        session_key: str | None = None,
    ) -> AsyncIterator[str]:
        self.responses_content_parts.append(content_parts)
        yield "文件回答"


def _install_openclaw_client(
    client: TestClient,
    openclaw_client: RecordingOpenClawClient,
) -> None:
    client.app.dependency_overrides[get_openclaw_client] = (
        lambda: openclaw_client
    )


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(
    client: TestClient,
    *,
    username: str,
    phone: str,
) -> dict[str, object]:
    response = client.post(
        REGISTER_URL,
        json={
            "username": username,
            "password": PASSWORD,
            "display_name": username,
            "phone": phone,
            "email": f"{username}@example.com",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def _login(client: TestClient, *, username: str) -> str:
    response = client.post(
        LOGIN_URL,
        json={"account": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


def _stored_agent(db_session: Session, user_id: str) -> UserAgent:
    return db_session.execute(
        select(UserAgent).where(UserAgent.user_id == int(user_id))
    ).scalar_one()


def _set_agent(db_session: Session, user_id: str, *, agent_id: str) -> None:
    user_agent = _stored_agent(db_session, user_id)
    user_agent.agent_id = agent_id
    user_agent.provision_status = "ready"
    db_session.commit()


def _create_ready_user(
    client: TestClient,
    db_session: Session,
    *,
    username: str,
    phone: str,
) -> tuple[dict[str, object], str]:
    user = _register(client, username=username, phone=phone)
    _set_agent(db_session, str(user["id"]), agent_id=f"agent-{username}")
    return user, _login(client, username=username)


def _create_conversation(client: TestClient, token: str) -> str:
    response = client.post("/api/conversations", headers=_authorization(token), json={})
    assert response.status_code == 200
    return response.json()["data"]["id"]


def _upload(
    client: TestClient,
    *,
    token: str,
    filename: str,
    content: bytes,
    content_type: str,
    conversation_id: str | None = None,
):
    data = {}
    if conversation_id is not None:
        data["conversation_id"] = conversation_id
    return client.post(
        "/api/attachments",
        headers=_authorization(token),
        files={"file": (filename, content, content_type)},
        data=data,
    )


def test_upload_attachment_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/attachments",
        files={"file": ("image.png", PNG_1X1, "image/png")},
    )

    assert response.status_code == 401


def test_upload_query_content_and_delete_image(
    client: TestClient,
    db_session: Session,
) -> None:
    _user, token = _create_ready_user(
        client,
        db_session,
        username="att_image",
        phone="13700137001",
    )

    uploaded = _upload(
        client,
        token=token,
        filename="error.png",
        content=PNG_1X1,
        content_type="image/png",
    )

    assert uploaded.status_code == 200
    data = uploaded.json()["data"]
    attachment_id = data["attachment_id"]
    assert data["filename"] == "error.png"
    assert data["content_type"] == "image/png"
    assert data["category"] == "image"
    assert data["status"] == "ready"
    assert data["preview_url"] == f"/api/attachments/{attachment_id}/content"

    detail = client.get(
        f"/api/attachments/{attachment_id}",
        headers=_authorization(token),
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["attachment_id"] == attachment_id

    content = client.get(
        f"/api/attachments/{attachment_id}/content",
        headers=_authorization(token),
    )
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/png")
    assert content.content == PNG_1X1

    deleted = client.delete(
        f"/api/attachments/{attachment_id}",
        headers=_authorization(token),
    )
    assert deleted.status_code == 200
    assert (
        client.get(
            f"/api/attachments/{attachment_id}",
            headers=_authorization(token),
        ).status_code
        == 404
    )


def test_upload_pdf_and_reject_invalid_files(
    client: TestClient,
    db_session: Session,
) -> None:
    _user, token = _create_ready_user(
        client,
        db_session,
        username="att_pdf",
        phone="13700137002",
    )

    pdf = _upload(
        client,
        token=token,
        filename="report.pdf",
        content=PDF_MINIMAL,
        content_type="application/pdf",
    )
    assert pdf.status_code == 200
    assert pdf.json()["data"]["category"] == "document"

    unsupported = _upload(
        client,
        token=token,
        filename="macro.docx",
        content=b"PK\x03\x04fake",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert unsupported.status_code == 415

    mismatch = _upload(
        client,
        token=token,
        filename="fake.png",
        content=b"MZ executable",
        content_type="image/png",
    )
    assert mismatch.status_code == 415

    empty = _upload(
        client,
        token=token,
        filename="empty.txt",
        content=b"",
        content_type="text/plain",
    )
    assert empty.status_code == 400


def test_attachment_access_is_user_scoped(
    client: TestClient,
    db_session: Session,
) -> None:
    _user_a, token_a = _create_ready_user(
        client,
        db_session,
        username="att_owner",
        phone="13700137003",
    )
    _user_b, token_b = _create_ready_user(
        client,
        db_session,
        username="att_other",
        phone="13700137004",
    )
    uploaded = _upload(
        client,
        token=token_a,
        filename="note.txt",
        content=b"hello",
        content_type="text/plain",
    )
    attachment_id = uploaded.json()["data"]["attachment_id"]

    assert (
        client.get(
            f"/api/attachments/{attachment_id}",
            headers=_authorization(token_b),
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/chat",
            headers=_authorization(token_b),
            json={"message": "越权", "attachment_ids": [attachment_id]},
        ).status_code
        == 404
    )


def test_chat_with_image_persists_attachment_and_history(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    _user, token = _create_ready_user(
        client,
        db_session,
        username="att_chat",
        phone="13700137005",
    )
    conversation_id = _create_conversation(client, token)
    uploaded = _upload(
        client,
        token=token,
        filename="screenshot.png",
        content=PNG_1X1,
        content_type="image/png",
        conversation_id=conversation_id,
    )
    attachment_id = uploaded.json()["data"]["attachment_id"]

    response = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={
            "conversation_id": conversation_id,
            "message": "请分析",
            "attachment_ids": [attachment_id],
        },
    )

    assert response.status_code == 200
    assert openclaw_client.chat_content_parts
    parts = openclaw_client.chat_content_parts[0]
    assert parts is not None
    assert parts[0] == {"type": "text", "text": "请分析"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")

    db_session.expire_all()
    links = db_session.execute(select(MessageAttachment)).scalars().all()
    assert [(link.attachment_id, link.sort_order) for link in links] == [
        (attachment_id, 0)
    ]

    history = client.get(
        f"/api/conversations/{conversation_id}/messages",
        headers=_authorization(token),
    )
    assert history.status_code == 200
    user_message = history.json()["data"]["items"][0]
    assert user_message["attachments"][0]["attachment_id"] == attachment_id
    assert history.json()["data"]["items"][1]["attachments"] == []

    linked_delete = client.delete(
        f"/api/attachments/{attachment_id}",
        headers=_authorization(token),
    )
    assert linked_delete.status_code == 409


def test_chat_accepts_attachment_without_text_and_rejects_empty_payload(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    _user, token = _create_ready_user(
        client,
        db_session,
        username="att_only",
        phone="13700137006",
    )
    uploaded = _upload(
        client,
        token=token,
        filename="data.json",
        content=b'{"ok": true}',
        content_type="application/json",
    )
    attachment_id = uploaded.json()["data"]["attachment_id"]

    only_attachment = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={"message": "", "attachment_ids": [attachment_id]},
    )
    assert only_attachment.status_code == 200
    assert openclaw_client.responses_content_parts == []
    parts = openclaw_client.chat_content_parts[0]
    assert parts is not None
    assert parts[0]["type"] == "text"
    assert "附件文件名：data.json" in parts[0]["text"]
    assert '{"ok": true}' in parts[0]["text"]

    empty = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={"message": "", "attachment_ids": []},
    )
    assert empty.status_code == 400


def test_chat_with_pdf_extracts_text_for_chat_completions(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "attachment_pdf_text_min_chars", 1)
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    _user, token = _create_ready_user(
        client,
        db_session,
        username="att_pdf_chat",
        phone="13700137009",
    )
    uploaded = _upload(
        client,
        token=token,
        filename="route.pdf",
        content=_text_pdf("PDF attachment route text"),
        content_type="application/pdf",
    )
    attachment_id = uploaded.json()["data"]["attachment_id"]

    response = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={
            "message": "这个 PDF 里是什么",
            "attachment_ids": [attachment_id],
        },
    )

    assert response.status_code == 200
    assert openclaw_client.responses_content_parts == []
    parts = openclaw_client.chat_content_parts[0]
    assert parts is not None
    assert parts[0] == {
        "type": "text",
        "text": "这个 PDF 里是什么",
    }
    assert parts[1]["type"] == "text"
    assert "附件文件名：route.pdf" in parts[1]["text"]
    assert "附件类型：PDF" in parts[1]["text"]
    assert "PDF attachment route text" in parts[1]["text"]
    assert len(parts) == 2


def test_chat_with_short_pdf_text_renders_pages_as_images(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "attachment_pdf_text_min_chars", 1000)
    monkeypatch.setattr(settings, "attachment_pdf_render_max_pages", 1)
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    _user, token = _create_ready_user(
        client,
        db_session,
        username="att_pdf_image_fallback",
        phone="13700137011",
    )
    uploaded = _upload(
        client,
        token=token,
        filename="short.pdf",
        content=_text_pdf("short"),
        content_type="application/pdf",
    )
    attachment_id = uploaded.json()["data"]["attachment_id"]

    response = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={
            "message": "这个 PDF 里是什么",
            "attachment_ids": [attachment_id],
        },
    )

    assert response.status_code == 200
    assert openclaw_client.responses_content_parts == []
    parts = openclaw_client.chat_content_parts[0]
    assert parts is not None
    assert parts[1]["type"] == "text"
    assert "已将 PDF 前几页渲染为图片一并发送" in parts[1]["text"]
    assert parts[2]["type"] == "image_url"
    assert parts[2]["image_url"]["url"].startswith("data:image/png;base64,")


def test_file_only_text_chat_uses_inline_prompt(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    _user, token = _create_ready_user(
        client,
        db_session,
        username="att_file_only_prompt",
        phone="13700137010",
    )
    uploaded = _upload(
        client,
        token=token,
        filename="note.txt",
        content=b"hello file",
        content_type="text/plain",
    )
    attachment_id = uploaded.json()["data"]["attachment_id"]

    response = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={"message": "", "attachment_ids": [attachment_id]},
    )

    assert response.status_code == 200
    assert openclaw_client.responses_content_parts == []
    parts = openclaw_client.chat_content_parts[0]
    assert parts[0] == {
        "type": "text",
        "text": (
            "\n\n附件文件名：note.txt\n"
            "附件内容：\n```txt\nhello file\n```"
        ),
    }


def test_chat_rejects_attachment_limits(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    _user, token = _create_ready_user(
        client,
        db_session,
        username="att_limits",
        phone="13700137007",
    )
    too_many = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={
            "message": "limits",
            "attachment_ids": ["a", "b", "c", "d", "e"],
        },
    )
    assert too_many.status_code == 400

    monkeypatch.setattr(settings, "attachment_total_max_size", 5)
    first = _upload(
        client,
        token=token,
        filename="a.txt",
        content=b"1234",
        content_type="text/plain",
    ).json()["data"]["attachment_id"]
    second = _upload(
        client,
        token=token,
        filename="b.txt",
        content=b"5678",
        content_type="text/plain",
    ).json()["data"]["attachment_id"]
    too_large = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={"message": "limits", "attachment_ids": [first, second]},
    )
    assert too_large.status_code == 413


def test_upload_failure_and_openclaw_failure_are_safe(
    client: TestClient,
    db_session: Session,
    fake_storage_service,
) -> None:
    _user, token = _create_ready_user(
        client,
        db_session,
        username="att_failures",
        phone="13700137008",
    )
    fake_storage_service.fail_put = True
    failed_upload = _upload(
        client,
        token=token,
        filename="fail.txt",
        content=b"hello",
        content_type="text/plain",
    )
    assert failed_upload.status_code == 503
    fake_storage_service.fail_put = False

    uploaded = _upload(
        client,
        token=token,
        filename="ok.txt",
        content=b"hello",
        content_type="text/plain",
    )
    attachment_id = uploaded.json()["data"]["attachment_id"]
    openclaw_client = RecordingOpenClawClient(
        exc=OpenClawConnectionError("internal secret"),
    )
    _install_openclaw_client(client, openclaw_client)
    failed_chat = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={"message": "hello", "attachment_ids": [attachment_id]},
    )
    assert failed_chat.status_code == 503
    assert "internal secret" not in failed_chat.text
