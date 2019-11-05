#!/usr/bin/env python3
#encoding: UTF-8
import os
import sys

sys.path.append(os.getcwd())
import argparse
from base64 import b64encode
import helpers.bot
import helpers.db
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from urllib.parse import urlparse, parse_qs
from cryptography.fernet import Fernet
import json


import sys
import time
import urllib.parse
import urllib.request

class S(BaseHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        self._set_headers()
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        state = None
        code = None
        if 'state' in qs and len(qs['state']):
            state = qs['state'][0]
            if 'code' in qs:
                code = qs['code'][0]

        if state and code:
            try:
                chat_id = Fernet(reddit_config['internal_secret'].encode()).decrypt(state.encode()).decode('utf-8')
            except Exception as e:
                print(e)
                self.wfile.write("<html><body><h1>nope</h1></body></html>".encode())
                return
            chat = get_chat(chat_id)
            if not chat:
                self.wfile.write("<html><body><h1>no such chat</h1></body></html>".encode())
                print("no such chat")
                return

            try:
                response = get_token(code)
                if 'error' in response:
                    print(json.dumps(response))
                    raise SyntaxError(json.dumps(response))
            except Exception as e:
                print(e)
                self.wfile.write("<html><body><h1>cannot authorize with this code, are you sure you didnt use it before?</h1></body></html>".encode())
                return

            try:
                test = do_request("https://oauth.reddit.com/api/v1/me", None, [('Authorization', 'bearer ' + response['access_token'])]);
            except Exception as e:
                print(e)
                self.wfile.write("<html><body><h1>cannot get account information</h1></body></html>".encode())
                return


            set_settings(chat_id, {
                         'token': response['access_token'],
                         'refresh_token': response['refresh_token'],
                         'created': int(time.time()),
                         'ttl': response['expires_in']
                         })


            bot.send_message(chat_id, "Hello, {username}! You can vote posts now.\nAlso you can set bot to show your personal feed by sending `!set source /best`".format(username=test['name']), parse_mode="Markdown")

            db.commit()


            self.wfile.write("<html><body><h1>yup</h1></body></html>".encode())
        else:
            self.wfile.write("<html><body><h1>nope</h1></body></html>".encode())





def run(server_class=HTTPServer, handler_class=S, port=60321):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print('Starting httpd...')
    httpd.serve_forever()


if __name__ != "__main__":
    print('this is executable')
    exit()



parser = argparse.ArgumentParser()
parser.add_argument('--config', help='Relative path to bot\'s configuration file. Defaults to config.json inside workdir.', default="config.json")
cmdline = parser.parse_args()
bot_path = os.path.dirname(os.path.abspath(__file__))
"""We use patched pytelegrambotapi here
with sendAnimation
and video previews
and fancy user-controller loop
and other things
"""

with open(os.getcwd() + '/' + cmdline.config) as json_file:
    config = json.loads(json_file.read())

global reddit_config
reddit_config = config['plugin_config']['reddit']


"""Initialize database"""
if "database" in config:
    try:

        autocommit = False
        db = helpers.db.instance(config['database'], autocommit)
    except Exception as e:
        print("Cannot initialize database:", e)

bot = helpers.bot.instance(token=config['telegram_token'], threaded=False)
from plugins.gatekeeper import get_chat
from plugins.gatekeeper import set_settings

def do_request(url, params=None, token=None):
    opener = urllib.request.build_opener()
    authstr = b64encode((reddit_config['id'] + ':' + reddit_config['secret']).encode("utf-8")).decode('utf-8')
    opener.addheaders = [
        ('User-Agent', 'telegram:reddit_reposter_bot:2.0b (by /u/nev3rfail)'),
        ]
    if token:
        opener.addheaders = opener.addheaders + token
    else:
        opener.addheaders.append(('Authorization', 'Basic ' + authstr))

    response = opener.open(url, urllib.parse.urlencode(params).encode("utf-8") if params is not None else None, timeout=5)
    rmsg = response.read()
    return json.loads(rmsg)



def get_token(code):
    return do_request('https://www.reddit.com/api/v1/access_token', {'grant_type':'authorization_code', 'redirect_uri':reddit_config['redirect_uri'], 'code':code})


run()



#print(get_token(code))
#_user_id = 'id_1'
#get_token(_user_id)

#rusers[_user_id]['code'] = 'jEpvnjAAjsE_FvLWrHlwcsiYQ90'
#get_token(_user_id)
#pass
#do_request('https://www.reddit.com/api/v1/access_token', {'grant_type':'client_credentials'})
