"""Feishu / Lark gateway — message your laptop from Feishu (飞书).

Setup (5 minutes, free, no public URL needed):
  1. Go to https://open.feishu.cn/app → 创建企业自建应用
  2. Add the "机器人" (bot) capability under 应用功能
  3. Under 事件与回调 → 事件订阅, set the subscription method to
     "使用长连接接收事件" (receive events over a long connection) — this is
     what lets your laptop receive messages over an outbound websocket, the
     same trick Telegram's long-polling uses to avoid a public URL or
     webhook. Subscribe to the "接收消息" (im.message.receive_v1) event.
  4. Copy the App ID and App Secret from 凭证与基础信息 into .env:
       FEISHU_APP_ID=...
       FEISHU_APP_SECRET=...
  5. Publish the app (发布) so it can actually receive events — an
     unpublished app's long connection never fires.
  6. Set FEISHU_ALLOWED_USER to your open_id (find it via the bot's first
     unauthorized message, which prints the sender's open_id to the
     terminal) so ONLY you can talk to your Syrup. Comma-separate for
     several people. LEAVING THIS UNSET MEANS ANYONE WHO CAN MESSAGE THE
     BOT CAN USE IT.
  7. In a group chat, the bot only answers when @-mentioned — add it to a
     group and @ it to try.
  8. make feishu

Known limitation: the official lark-oapi SDK runs its websocket client on
one shared, module-global event loop with no public stop() method — a
`syrup dashboard` config reload can ask it to disconnect (best effort) but
cannot guarantee a clean restart the way Telegram/Discord/WhatsApp can. If
Feishu shows an error status after changing FEISHU_APP_ID, restart the
`syrup dashboard` process.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path

from syrup.gateway.cli import _observer
from syrup.integrations import IntegrationState, IntegrationStatus

_MENTION = re.compile(r"@_user_\d+\s*")


def _allowed_ids() -> set[str]:
    return {p.strip() for p in os.getenv("FEISHU_ALLOWED_USER", "").split(",") if p.strip()}


def posture() -> str:
    ids = _allowed_ids()
    who = (f"{len(ids)} allowlisted user(s)" if ids else
           "ANYONE who can message this bot — set FEISHU_ALLOWED_USER to lock it")
    home = os.getenv("FEISHU_HOME", "").strip() or ".syrup — YOUR personal memory"
    return (f"  reachable by: {who}\n"
            f"  memory:       {home}")


def should_answer(*, is_group: bool, mentioned: bool, sender_open_id: str, allowed: set[str]) -> bool:
    """The whole access policy, as one pure function so it can be tested
    without a Feishu connection. Deny is the default at every branch,
    mirroring discord.py's should_answer.

    Private (p2p) chats are answered unless an allowlist exists and
    excludes the sender. Group chats are answered only when the bot was
    @-mentioned AND the sender passes the allowlist — Feishu has no
    platform-level mention gate like DingTalk, so this app enforces it."""
    if allowed and sender_open_id not in allowed:
        return False
    if is_group:
        return mentioned
    return True


def _clean_text(content_json: str) -> str:
    """Parse a text message's JSON `content` field and drop the '@_user_N'
    mention placeholders Feishu inserts ahead of the real text."""
    try:
        text = json.loads(content_json).get("text", "")
    except (TypeError, ValueError):
        return ""
    return _MENTION.sub("", text).strip()


def _build_agent():
    """The agent behind the bot. FEISHU_HOME gives it a memory of its own,
    mirroring DISCORD_HOME — the difference between 'a bot in my org' and
    'my private assistant, exposed'."""
    from syrup.app import Syrup

    home = os.getenv("FEISHU_HOME", "").strip()
    if not home:
        return Syrup()
    from syrup.config import load_settings

    settings = load_settings()
    settings.home = Path(home)
    settings.ensure_home()
    return Syrup(settings=settings)


def _build_event_handler(reply_client, allowed: set[str]):
    """Build the event dispatcher. Feishu's ws handlers are plain sync
    functions (not coroutines), so this uses one Syrup instance behind a
    lock — the same shape as whatsapp.py — rather than the async
    GatewayAgentRunner telegram.py/discord.py use."""
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

    syrup = _build_agent()
    syrup.session.session_id = "feishu"
    syrup_lock = threading.Lock()

    def _reply(message_id: str, text: str) -> None:
        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(json.dumps({"text": text}))
                .msg_type("text")
                .uuid(str(uuid.uuid4()))
                .build()
            )
            .build()
        )
        response = reply_client.im.v1.message.reply(request)
        if not response.success():
            print(f"(feishu) send failed: code={response.code} msg={response.msg}")

    def on_message(data) -> None:
        message = data.event.message
        sender = data.event.sender
        content = message.content or ""
        text = _clean_text(content)
        if not text or message.message_type != "text":
            return

        sender_open_id = (sender.sender_id.open_id if sender and sender.sender_id else "") or ""
        is_group = message.chat_type == "group"
        mentioned = bool(message.mentions)

        if not should_answer(
            is_group=is_group, mentioned=mentioned,
            sender_open_id=sender_open_id, allowed=allowed,
        ):
            print(f"(feishu) rejected message from {sender_open_id} (not allowed)")
            return

        print(f"you › [{sender_open_id}] {text}")
        with syrup_lock:
            result = syrup.respond(text, observer=_observer, source="feishu")
        print(f"syrup › {result.reply}")
        _reply(message.message_id, result.reply or "(no reply)")

    return (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )


def _build_client():
    import lark_oapi as lark

    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    allowed = _allowed_ids()

    reply_client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
    event_handler = _build_event_handler(reply_client, allowed)
    return lark.ws.Client(
        app_id, app_secret, event_handler=event_handler, log_level=lark.LogLevel.WARNING
    )


def main() -> None:
    try:
        import lark_oapi  # noqa: F401
    except ImportError:
        raise SystemExit("Feishu extra not installed: pip install 'syrup-agent[feishu]'")

    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise SystemExit(
            "Set FEISHU_APP_ID and FEISHU_APP_SECRET in .env "
            "(create a self-built app with a bot at https://open.feishu.cn/app). "
            "See syrup/gateway/feishu.py docstring for setup instructions."
        )
    client = _build_client()
    print("Syrup is listening on Feishu. Ctrl-C to stop.")
    print(posture())
    client.start()


class FeishuHandle:
    def __init__(self, client, thread: threading.Thread) -> None:
        self.client, self.thread = client, thread

    def stop(self) -> None:
        # lark-oapi's ws.Client exposes no public stop() — best-effort
        # disconnect on its shared module-level loop. See the module
        # docstring's "Known limitation" note.
        try:
            import asyncio

            import lark_oapi.ws.client as ws_module

            if self.thread.is_alive() and ws_module.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.client._disconnect(), ws_module.loop  # noqa: SLF001
                ).result(timeout=10)
        except Exception as exc:  # noqa: BLE001 — best effort only
            print(f"(feishu) disconnect was not clean: {exc}")
        if self.thread.is_alive():
            self.thread.join(timeout=5)

    def status(self) -> IntegrationStatus:
        if not self.thread.is_alive():
            return IntegrationStatus(IntegrationState.ERROR, "gateway stopped unexpectedly")
        return IntegrationStatus(IntegrationState.CONNECTED)


def start_in_background() -> FeishuHandle | None:
    """Start the Feishu long-connection client on a daemon thread — so
    `syrup dashboard` runs the browser cockpit AND Feishu from one command.
    Returns None (quietly) if credentials aren't set or the extra isn't
    installed. Never raises: a gateway problem must not take down the
    dashboard."""
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        return None
    try:
        import lark_oapi  # noqa: F401
    except ImportError:
        print("(feishu) FEISHU_APP_ID is set but the extra isn't installed — "
              "pip install 'syrup-agent[feishu]'")
        return None

    print("(feishu) starting:")
    print(posture())

    client = _build_client()

    def run() -> None:
        try:
            client.start()
        except Exception as exc:  # noqa: BLE001 — isolate the dashboard from bot errors
            print(f"(feishu) background client stopped: {exc}")

    thread = threading.Thread(target=run, daemon=True, name="feishu-ws")
    thread.start()
    return FeishuHandle(client, thread)


if __name__ == "__main__":
    main()
