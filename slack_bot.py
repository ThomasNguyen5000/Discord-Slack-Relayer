from typing import Any, TYPE_CHECKING
import os
import asyncio
import sys
import logging

from slack_bolt import BoltContext
from slack_bolt.app.async_app import AsyncApp
from slack_sdk import WebClient
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

import config
from pipe import recv_discord_msg, send_slack_msg

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from typing import Callable


# Logging stdout and stderr to a file
# Taken from https://stackoverflow.com/a/31688396
class LoggerWriter:
    def __init__(self, writer: 'Callable[[Any], None]'):
        # self.level is really like using log.debug(message)
        # at least in my case
        self.writer = writer

    def write(self, message: str):
        # if statement reduces the amount of newlines that are
        # printed to the logger
        if message != '\n':
            self.writer(message)

    def flush(self):
        # create a flush method so things can be flushed when
        # the system wants to. Not sure if simply 'printing'
        # sys.stderr is the correct way to do it, but it seemed
        # to work properly for me.
        self.writer(sys.stderr)

# All the async code was kinda taken from this Github issue.
# https://github.com/slackapi/bolt-python/issues/592#issuecomment-1042368085
async def run_app(
    pipe: 'Connection',
    bot_tokens: dict[str, str],
    signing_secret: str,
    socket_token: str
) -> None:
    
    # Log output to file.
    root: logging.Logger = logging.getLogger()
    root.setLevel(logging.DEBUG)

    handler = logging.FileHandler(filename="slack.log", encoding="utf-8", mode="w")
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
    handler.setFormatter(formatter)
    
    root.addHandler(handler)
    sys.stdout = LoggerWriter(logging.info)
    sys.stderr = LoggerWriter(logging.debug)
    
    CLIENTS = {
        config.SLACK_TOKEN_ENV_VARS[bot_name]: WebClient(token=bot_tokens[bot_name])
        for bot_name in bot_tokens
    }

    # MAIN_CLIENT: WebClient = iter(CLIENTS.values()).__next__()

    app = AsyncApp(
        token=os.environ.get("MAIN_SLACK_TOKEN"),
        signing_secret=signing_secret
    )

    @app.event("message")  # type: ignore
    async def receive_messages( # type: ignore
        message: dict[str, Any], context: BoltContext,
        payload: dict[str, Any]
    ) -> None:  
        # If it is from one of the bots then don't relay to Discord.
        if "bot_id" in payload:
            return
        
        if "subtype" in message:
            return

        # Possibly make it able to deal with attachments.
        send_slack_msg(pipe, {
            "content": message['text'],
            "sender_id": context.user_id, # type: ignore
            "channel_id": context.channel_id or ""
        })

    handler = AsyncSocketModeHandler(
        app, socket_token
    )

    asyncio.create_task(poll_msg(pipe, CLIENTS))

    await handler.start_async()


# The background task.
# Poll for messages and relay to Slack basically.
async def poll_msg(pipe: 'Connection', clients: dict[int, WebClient]) -> None:
    while True:
        await asyncio.sleep(2)
        # Relevant Slack API docs
        # https://slack.dev/python-slack-sdk/web/index.html#messaging

        if (msg := recv_discord_msg(pipe)) is not None:
            if len(msg["content"]) == 0:
                continue
            # assert len(msg['content']) < MAX_SLACK_MSG_LEN
            clients[msg['sender_id']].chat_postMessage(  # type: ignore
                channel=config.DISCORD_CHANNEL_MAP[msg['channel_id']],
                text=msg['content']
            )
