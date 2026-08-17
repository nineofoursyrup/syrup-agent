"""DingTalk gateway — message your laptop from DingTalk (钉钉).

Setup (5 minutes, free, no public URL needed):
  1. Go to https://open-dev.dingtalk.com → 创建应用 → "企业内部应用"
  2. Add the "机器人" (bot) capability to the app, and enable "Stream 模式"
     under 消息推送 (Message Push) — this is what lets your laptop receive
     messages over an outbound websocket, the same trick Telegram's
     long-polling uses to avoid a public URL or webhook.
  3. Copy the Client ID (AppKey) and Client Secret (AppSecret) from
     凭证与基础信息 into .env:
       DINGTALK_CLIENT_ID=...
       DINGTALK_CLIENT_SECRET=...
  4. Set DINGTALK_ALLOWED_USER to your numeric staffId (find it via the
     bot's first unauthorized message, which prints the sender's staffId
     to the terminal) so ONLY you can talk to your Syrup. Comma-separate
     for several people. LEAVING THIS UNSET MEANS ANYONE IN YOUR
     ORGANIZATION WHO FINDS THE BOT CAN USE IT.
  5. In a group chat, the bot only sees messages where it is @-mentioned
     (DingTalk enforces this at the platform level, same as Discord's
     require-mention default) — this is not configurable per-app.
  6. make dingtalk

Stream mode: your laptop opens an outbound websocket to DingTalk's servers
and receives messages over it — no inbound port, no ngrok, no webhook config.
This is why Stream mode (not the older HTTP callback mode) is used here.
"""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

from syrup.app import Syrup
from syrup.gateway.cli import _observer
from syrup.gateway.runner import GatewayAgentRunner, run_gateway_turn
from syrup.integrations import IntegrationState, IntegrationStatus


def _allowed_ids() -> set[str]:
    return {p.strip() for p in os.getenv("DINGTALK_ALLOWED_USER", "").split(",") if p.strip()}


def posture() -> str:
    ids = _allowed_ids()
    who = (f"{len(ids)} allowlisted user(s)" if ids else
           "ANYONE in your DingTalk org who finds this bot — set DINGTALK_ALLOWED_USER to lock it")
    home = os.getenv("DINGTALK_HOME", "").strip() or ".syrup — YOUR personal memory"
    return (f"  reachable by: {who}\n"
            f"  memory:       {home}")


def should_answer(*, sender_staff_id: str, allowed: set[str]) -> bool:
    """The whole access policy, as one pure function so it can be tested
    without a DingTalk connection. Group @-mention gating is already
    enforced by the DingTalk platform before this bot ever sees the
    message, so the only decision left here is the user allowlist — empty
    means everyone in the org, matching Telegram's and Discord's default."""
    return not allowed or sender_staff_id in allowed


def _build_agent():
    """The agent behind the bot. DINGTALK_HOME gives it a memory of its own,
    mirroring DISCORD_HOME and FEISHU_HOME. This matters more here than on a
    one-to-one channel like Telegram: DingTalk is org-wide, an empty allowlist
    means every colleague who finds the bot can talk to it, and without a home
    of its own every one of those turns is answered out of YOUR .syrup — the
    difference between 'a bot in my org' and 'my private assistant, exposed'."""
    home = os.getenv("DINGTALK_HOME", "").strip()
    if not home:
        return Syrup()
    from syrup.config import load_settings

    settings = load_settings()
    settings.home = Path(home)
    settings.ensure_home()
    return Syrup(settings=settings)


def _new_runner() -> GatewayAgentRunner:
    return GatewayAgentRunner(
        _build_agent, session_id="dingtalk", source="dingtalk", observer=_observer
    )


def _build_handler(runner: GatewayAgentRunner | None = None):
    """Build the ChatbotHandler subclass. Shared by the standalone gateway
    and the background client `syrup dashboard` starts."""
    import dingtalk_stream

    allowed = _allowed_ids()
    runner = runner or _new_runner()

    class Handler(dingtalk_stream.ChatbotHandler):
        async def process(self, callback):
            incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
            text = (incoming.text.content or "").strip() if incoming.text else ""
            sender = incoming.sender_staff_id or incoming.sender_id or ""

            if not text:
                return dingtalk_stream.AckMessage.STATUS_OK, "OK"
            if not should_answer(sender_staff_id=sender, allowed=allowed):
                self.logger.info("(dingtalk) rejected message from %s (not allowed)", sender)
                return dingtalk_stream.AckMessage.STATUS_OK, "OK"

            async def send(reply_text: str) -> None:
                self.reply_text(reply_text, incoming)

            await run_gateway_turn(runner, text, send)
            return dingtalk_stream.AckMessage.STATUS_OK, "OK"

    return Handler()


def _build_client(runner: GatewayAgentRunner | None = None):
    import dingtalk_stream

    client_id = os.getenv("DINGTALK_CLIENT_ID", "")
    client_secret = os.getenv("DINGTALK_CLIENT_SECRET", "")
    credential = dingtalk_stream.Credential(client_id, client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC, _build_handler(runner)
    )
    return client


def main() -> None:
    try:
        import dingtalk_stream  # noqa: F401
    except ImportError:
        raise SystemExit("DingTalk extra not installed: pip install 'syrup-agent[dingtalk]'")

    client_id = os.getenv("DINGTALK_CLIENT_ID", "")
    client_secret = os.getenv("DINGTALK_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise SystemExit(
            "Set DINGTALK_CLIENT_ID and DINGTALK_CLIENT_SECRET in .env "
            "(create an internal app with a bot at https://open-dev.dingtalk.com). "
            "See syrup/gateway/dingtalk.py docstring for setup instructions."
        )
    runner = _new_runner()
    try:
        client = _build_client(runner)
        print("Syrup is listening on DingTalk. Ctrl-C to stop.")
        print(posture())
        client.start_forever()
    finally:
        runner.close()


class DingTalkHandle:
    def __init__(self, client, loop, thread, runner: GatewayAgentRunner) -> None:
        self.client, self.loop, self.thread, self.runner = client, loop, thread, runner

    def stop(self) -> None:
        try:
            if self.thread.is_alive() and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self.client.stop(), self.loop).result(timeout=10)
                self.loop.call_soon_threadsafe(self.loop.stop)
            if self.thread.is_alive():
                self.thread.join(timeout=10)
        finally:
            self.runner.close()

    def status(self) -> IntegrationStatus:
        if not self.thread.is_alive():
            return IntegrationStatus(IntegrationState.ERROR, "gateway stopped unexpectedly")
        if error := self.runner.error_status:
            return IntegrationStatus(IntegrationState.ERROR, error)
        return IntegrationStatus(IntegrationState.CONNECTED)


def start_in_background() -> DingTalkHandle | None:
    """Start the DingTalk stream client on a daemon thread — so `syrup
    dashboard` runs the browser cockpit AND DingTalk from one command.
    Returns None (quietly) if credentials aren't set or the extra isn't
    installed. Never raises: a gateway problem must not take down the
    dashboard."""
    client_id = os.getenv("DINGTALK_CLIENT_ID", "")
    client_secret = os.getenv("DINGTALK_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None
    try:
        import dingtalk_stream  # noqa: F401
    except ImportError:
        print("(dingtalk) DINGTALK_CLIENT_ID is set but the extra isn't installed — "
              "pip install 'syrup-agent[dingtalk]'")
        return None

    print("(dingtalk) starting:")
    print(posture())

    runner = _new_runner()
    try:
        client = _build_client(runner)
    except Exception:
        runner.close()
        raise

    loop = asyncio.new_event_loop()

    def run() -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(client.start())
        except Exception as exc:
            print(f"(dingtalk) background client stopped: {exc}")

    thread = threading.Thread(target=run, daemon=True, name="dingtalk-stream")
    thread.start()
    return DingTalkHandle(client, loop, thread, runner)


if __name__ == "__main__":
    main()
