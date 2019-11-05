# Reddit Reposter
[nanobot](https://github.com/nev3rfail/telegram-nanobot) plugin which can send posts from reddit to chat.

https://t.me/reddit_reposter_bot -- bot in action
### Supported features:
* Ignore users
* Ignore subreddits
* Ignore spoilers
* Ignore NSFW content
* Supports images
* Supports gifs
* Supports videos (without audio, to implement audio we actually need to reencode DASH video to mp4 which will consume server resources)
* Supports long text posts with image preview (text will be cut and `Read more` link will appear)
* Supports link posts (post preview pic, post name and `Read more` link)
* Does not supports posts with huge gifs. I can't get filesize without actually downloading file, so I filter video variants by resolution, and sometimes gif is so long it does not fit to api
* Switch post source on the fly (get posts from users or from subreddit or from /r/all)
* If in chat room, bot will change reddit urls to actual posts
* Supports login with reddit api so you can use your personal /best feed as source


## Usage:
* Download or clone this repo
* Copy config.json.sample to reddit.json
* Add bot token to reddit.json
* Go to [Reddit App Preferences](https://ssl.reddit.com/prefs/apps/) and register new web app
* Paste app id and app secret to bot config file
  * If you want to user login feature you need to `pip install fernet`. Fernet is lightweight fast cryptographic library
  * run `echo "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" | python3` to generate encryption secret
  * copy your secret to `internal_secret` field in config
  * put redirect_uri in your config file. It must be valid url with port 60321 (will be configurable in future)
  * run `python3 ./standalone/reddit_token.py --config=reddit.json`
* Download or clone [nanobot](https://github.com/nev3rfail/telegram-nanobot) and [pyTelegramBotApi fork](https://github.com/nev3rfail/pyTelegramBotApi)
* Copy directory contents to telegram-nanobot
* run with `cd telegram-nanobot && python3 ./__init__.py --config=reddit.json`
