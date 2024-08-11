import os
from multiprocessing import Process, Pipe
import asyncio
from time import sleep

from dotenv import load_dotenv
from discord_bot import run_bot
from pipe import recv_discord_msg, recv_slack_msg
from slack_bot import run_app

import config


class Runner:
    def __init__(self) -> None:
        # These were supposed to be for message queues
        # Apparently these are no longer needed? IDK need more load testing to
        # determine that.
        self._discord_to_slack_msg = []
        self._slack_to_discord_msg = []

        # Discord bot token
        if (token := os.environ.get("DISCORD_TOKEN")) is not None:
            self._DISCORD_TOKEN = token
        else:
            raise ValueError("No discord token provided")

        self._SLACK_PEOPLE_TOKEN_MAP: dict[str, str] = {}

        for name in config.SLACK_TOKEN_ENV_VARS:
            if (mapped_name := os.environ.get(name)) is not None:
                self._SLACK_PEOPLE_TOKEN_MAP[name] = mapped_name
            else:
                raise ValueError(f"No valid mapped name provided for {name}")

        # Slack bot signing secret
        if (signing_secret := os.environ.get("SLACK_SIGNING_SECRET")) is not None:
            self._SLACK_SIGNING_SECRET = signing_secret
        else:
            raise ValueError("No slack signing secret provided")

        # Slack bot socket token
        if (socket_token := os.environ.get("SLACK_SOCKET_TOKEN")) is not None:
            self._SLACK_SOCKET_TOKEN = socket_token
        else:
            raise ValueError("No socket token provided")

        # Pipe for IPC between main and the Discord bot.
        self.DISCORD_PIPE, self.CHILD_DISCORD_PIPE = Pipe()
        # I don't think is even needed but just leave it here for now.
        # self.DISCORD_BOT = init_bot(child_discord_pipe)

        # Pipe for IPC between main and the Slack bot.
        self.SLACK_PIPE, self.CHILD_SLACK_PIPE = Pipe()

    def start(self) -> None:
        # Use multiprocess to create 2 processes, 1 for Slack and 1 for 
        # Discord.
        discord = Process(target=self.run_discord_bot, args=())
        slack = Process(target=self.run_slack_bot, args=())
        discord.start()
        slack.start()

        # Poll messages from Discord then relay to Slack and vice versa.
        # Not sure if message queues should be used, need more load testing.

        # Also for now I just send the raw messages over, we prob need more
        # information than just the raw messages (sender, attachments, etc...)
        while True:
            sleep(1)
            if (discord_msg := recv_discord_msg(self.DISCORD_PIPE)) is not None:
                self.SLACK_PIPE.send(discord_msg)
            if (slack_msg := recv_slack_msg(self.SLACK_PIPE)) is not None:
                self.DISCORD_PIPE.send(slack_msg)

    def run_discord_bot(self) -> None:
        run_bot(self._DISCORD_TOKEN, self.CHILD_DISCORD_PIPE)

    def run_slack_bot(self) -> None:
        asyncio.run(run_app(
            self.CHILD_SLACK_PIPE,
            self._SLACK_PEOPLE_TOKEN_MAP,
            self._SLACK_SIGNING_SECRET,
            self._SLACK_SOCKET_TOKEN
        ))


if __name__ == "__main__":
    load_dotenv()
    runner = Runner()
    runner.start()
