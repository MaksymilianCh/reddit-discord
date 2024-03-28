import argparse
import logging
import os
from logging.handlers import RotatingFileHandler

import requests
import toml
from discord_webhook import DiscordWebhook
from yt_dlp import YoutubeDL


class Translator:
    def __init__(self, config):
        self.API_ENDPOINT = config["translator"]["api_endpoint"]
        self.LANG = config["translator"]["lang"]
        self.ENGINE = config["translator"]["engine"]

    def translate(self, text):
        params = {"engine": self.ENGINE, "to": self.LANG, "text": text}
        response = requests.get(self.API_ENDPOINT, params=params)

        if response.status_code == 200:
            return response.json().get("translated_text")
        else:
            return None


class VideoProcessor:
    def __init__(self, config):
        self.HEADER = {"User-agent": config["video_processor"]["user_agent"]}
        self.SUBREDDIT = config["video_processor"]["subreddit"]
        self.WEBHOOK_URL = config["video_processor"]["webhook_url"]
        self.TRANSLATION_WARNING = config["translator"]["translation_warning"]
        self.DELETE_AFTER = config["video_processor"]["delete_after"]

    def parse(self, data):
        name = data["name"]
        logging.info(f"Processing: {name}")
        url = data["url_overridden_by_dest"]
        filename = f"{name}.mp4"

        ydlp_args = {
            "outtmpl": filename,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        }

        try:
            with YoutubeDL(ydlp_args) as ydl:
                ydl.download(url)
        except Exception as e:
            logging.error(f"Failed to download video: {e}")
            return

        original = data["title"]
        translator = Translator(config)
        translation = translator.translate(original)
        if translation is None:
            logging.error("Failed to translate video description")
            return

        if not original:
            webhook = DiscordWebhook(
                url=self.WEBHOOK_URL,
            )
            with open(filename, "rb") as f:
                webhook.add_file(file=f.read(), filename=filename)
            webhook.execute()

        else:
            webhook = DiscordWebhook(
                url=self.WEBHOOK_URL,
                content=f"{original}\n{self.TRANSLATION_WARNING}: {translation}\n<{url}>",
            )
            with open(filename, "rb") as f:
                webhook.add_file(file=f.read(), filename=filename)
            webhook.execute()

        with open("name", "w+") as file:
            file.write(name)

        if self.DELETE_AFTER:
            os.remove(filename)


class Runner:
    def __init__(self, config):
        self.HEADER = {"User-agent": config["video_processor"]["user_agent"]}
        self.SUBREDDIT = config["video_processor"]["subreddit"]

    def run(self):
        anchor = ""
        if os.path.exists("name"):
            with open("name", "r") as file:
                anchor = file.read()
        node = f"?before={anchor}"

        try:
            response = requests.get(
                f"https://www.reddit.com{self.SUBREDDIT}.json{node}",
                headers=self.HEADER,
            )
            response.raise_for_status()
            children = response.json()["data"]["children"]

            for child in reversed(children):
                data = child["data"]
                if data["stickied"] or not data["is_video"]:
                    continue
                VideoProcessor(config).parse(data)
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch Reddit data: {e}")


# you can use this script in some workflow, just export ENV variables
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env",
        action="store_true",
        help="Use environment variables instead of toml.config",
    )
    return parser.parse_args()


def load_config(env_mode):
    return (
        {
            "translator": {
                "api_endpoint": os.environ.get("API_ENDPOINT"),
                "lang": os.environ.get("LANG"),
                "engine": os.environ.get("ENGINE"),
                "translation_warning": os.environ.get("TRANSLATION_WARNING"),
            },
            "video_processor": {
                "user_agent": os.environ.get("USER_AGENT"),
                "subreddit": os.environ.get("SUBREDDIT"),
                "webhook_url": os.environ.get("WEBHOOK_URL"),
                "delete_after": os.environ.get("DELETE_AFTER"),
            },
        }
        if env_mode
        else toml.load("config.toml")
    )


def configure_logging():
    log_file = "app.log"
    log_file_size = 10 * 1024 * 1024  # 10 megabytes

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    file_handler = RotatingFileHandler(log_file, maxBytes=log_file_size, backupCount=1)
    file_handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(file_handler)

    logging.getLogger("discord_webhook").setLevel(logging.ERROR)
    logging.getLogger("yt_dlp").setLevel(logging.ERROR)


if __name__ == "__main__":
    args = parse_args()
    config = load_config(args.env)

    configure_logging()

    runner = Runner(config)
    runner.run()
