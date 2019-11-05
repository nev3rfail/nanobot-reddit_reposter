#encoding: UTF-8
# -*- coding: utf-8 -*-
from base64 import b64encode
from collections import namedtuple
from cryptography.fernet import Fernet
from gatekeeper import get_chat
from gatekeeper import get_setting
from gatekeeper import set_setting
from gatekeeper import set_settings
import helpers.bot
import helpers.db
from html import unescape
from io import BytesIO
import json
import re
from telebot import types
import time
import urllib.parse
from urllib.parse import unquote
import urllib.request

system_tokendata = {
    'token':None,
    'ttl':3600,
    'created':0
}

def request_url(url, params=None, token=[]):
    opener = urllib.request.build_opener()
    authstr = b64encode((reddit_config['id'] + ':' + reddit_config['secret']).encode("utf-8")).decode('utf-8')
    opener.addheaders = [
        ('User-Agent', 'telegram:reddit_reposter_bot:3.0b (by /u/nev3rfail)'),
        ]
    if token:
        opener.addheaders = opener.addheaders + token
    else:
        opener.addheaders.append(('Authorization', 'Basic ' + authstr))

    print(opener.addheaders)
    try:
        response = opener.open(url, urllib.parse.urlencode(params).encode("utf-8") if params is not None else None, timeout=5)
    except UnicodeDecodeError:
        response = opener.open(urllib.parse.quote(url).replace('%3A', ':'), urllib.parse.urlencode(params).encode("utf-8") if params is not None else None, timeout=5)



    if reddit_config['debug']:
        print(response.info())
    rmsg = response.read()
    if reddit_config['debug']:
        print(rmsg)
    return json.loads(rmsg)

def get_token():
    response = request_url('https://www.reddit.com/api/v1/access_token', {'grant_type':'client_credentials'})
    if 'error' in response:
        print('Cannot get anonymous token, exiting.')
        exit(1)
    system_tokendata['token'] = response['access_token']
    system_tokendata['ttl'] = response['expires_in']
    system_tokendata['created'] = int(time.time())
    return system_tokendata['token']

def refresh_token(chat_id, rtoken):
    response = request_url('https://www.reddit.com/api/v1/access_token', {'grant_type':'refresh_token', 'refresh_token':rtoken})
    if 'error' in response:
        print('Cannot get token for ' + str(chat_id) + ', using system token.')
        return system_tokendata['token']
    #print(response)
    set_settings(chat_id, {
                 'token': response['access_token'],
                 #'refresh_token': response['refresh_token'],
                 'created': int(time.time()),
                 'ttl': response['expires_in']
                 })
    return response['access_token']





def tokenstuff(chat_id):
    chat = get_chat(chat_id)
    settings = chat['settings']
    if settings['token'] is None:
        if system_tokendata['token'] is None:
            return get_token()
        else:
            if int(time.time()) < system_tokendata['created'] + system_tokendata['ttl']:
                return system_tokendata['token']
            else:
                return get_token()

        pass
    else:
        #if token is present and is fresh
        if int(time.time()) < settings['created'] + settings['ttl']:
            return settings['token']
        else:
            return refresh_token(chat_id, settings['refresh_token'])


class RedditPool:

    def __init__(self):
        self.pool = {}
        self.now_refilling = []
        self.storeunit = namedtuple("item", "data created")
        '''
        pool format is key => ['data' => [], 'created' => int]
        '''

    def get_key(self, url, chat_id):
        return str(chat_id) + ': ' + re.sub("&after=(.*)$", "", re.sub("\?after=(.*)$", "", url))


    def get_posts(self, url, chat_id, moar=False):
        now = int(time.time())
        key = self.get_key(url, chat_id)
        print("\nKey is", key)
        if key not in self.pool:
            print("Key not in pool, fillinng it.")
            self.refill(url, chat_id)
            return self.pool[key].data

        refill = False
        #if key not in self.pool or 'created' not in self.pool[key]:
        #    print "Key has no 'created' field"
        #    refill = True
        #if key not in self.pool or 'created' not in self.pool[key] or now > self.pool[key]['created'] + settings['pool_ttl']:
        if self.pool[key].created > 0 and now > self.pool[key].created + reddit_config['pool_ttl']:
            #print "ttl revalidation. ttl is", str(settings['pool_ttl']) + "; time is", str(int(time.time())) + ";", " created is", str(self.pool[key]['created']) + "; created+ttl: ", self.pool[key]['created'] + settings['pool_ttl']
            print("TTL revalidation, cache+" + str(reddit_config['pool_ttl']) + " is older than now for a", now-self.pool[key].created + reddit_config['pool_ttl'], "s.")
            refill = True
        if refill:
            self.refill(url, chat_id)

        if not refill and moar:
            self.append(url, chat_id)

        return self.pool[key].data

    def do_request(self, url, chat_id, full_response=False):
        print("Reaching ", url)

        token = tokenstuff(chat_id)
        try:
            stack = request_url(url, None, [('Authorization', 'bearer ' + token)])

        except Exception as e:
            print("Cannot retrieve posts:", e)
            stack = {"data":{"children":[]}}
        if full_response:
            return stack
        else:
            return stack['data']['children']

    def refill(self, url, chat_id):
        key = self.get_key(url, chat_id)
        if key not in self.now_refilling:
            self.now_refilling.append(key)
            print("Refilling " + key + "...")
            if key not in self.pool:
                self.pool[key] = self.storeunit(data=[], created=0)
            self.pool[key] = self.pool[key]._replace(data=self.do_request(url, chat_id), created=int(time.time()))
            self.now_refilling.remove(key)
        else:
            print(url, "is already refilling.")


    def append(self, url, chat_id):
        key = self.get_key(url, chat_id)
        print("appending ", key)
        if key not in self.pool:
            return self.refill(url, chat_id)
        #print self.pool[key]
        self.pool[key]._replace(data=self.pool[key].data.extend(self.do_request(url, chat_id)), created=int(time.time()))
        #self.pool[key]['data'].extend(self.do_request(url))
        #self.pool[key]['data']['created'] = int(time.time())


pool = RedditPool()

db = helpers.db.instance()
bot = helpers.bot.instance()

__plugin_name__ = "Reddit API"

def register(listen=True, config={}, ** kwargs):
    db.query("""
CREATE TABLE IF NOT EXISTS `read_posts` (
        `id`    INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE,
        `chat_id`       INTEGER,
        `post`  TEXT,
        `date_added`    TEXT
);
""")
    global reddit_config

    reddit_config = config

    if 'debug' in kwargs:
        reddit_config['debug'] = kwargs['debug']
    else:
        reddit_config['debug'] = False
    get_token()
    if listen:

        @bot.channel_post_handler(regexp='^!set ')
        @bot.message_handler(regexp='^!set ')
        def setting(message):
            chat = get_chat(message.chat.id)
            if message.from_user.id != chat['settings']['admin_id']:
                #bot.send_message(message.chat.id, unset())
                return
            segs = (message.text or message.caption or '').split(" ")
            if len(segs) >= 2:
                action = segs[1]
                if len(segs) >= 3:
                    param = segs[2]
                else:
                    param = ""
                if action == "nsfw":
                    if param == "on":
                        set_setting(message.chat.id, "nsfw", True)
                        bot.send_message(message.chat.id, "NSFW now set to on.")
                    else:
                        set_setting(message.chat.id, "nsfw", False)
                        bot.send_message(message.chat.id, "NSFW now set to off.")
                elif action == "spoilers":
                    if param == "on":
                        set_setting(message.chat.id, "spoilers", True)
                        bot.send_message(message.chat.id, "Spoilers now set to on.")
                    else:
                        set_setting(message.chat.id, "spoilers", False)
                        bot.send_message(message.chat.id, "Spoilers now set to off.")
                elif action == "source":
                    if len(param):
                        prev_source = chat['settings']['source']
                        if "/u/" in param:
                            username = re.match('^/u/(?P<username>.+?)$', param)
                            if username:
                                param = "/user/" + username.group('username') + "/submitted"
                            else:
                                bot.send_message(message.chat.id, "Invalid source?")
                                return

                        if prev_source == param:
                            bot.send_message(message.chat.id, "Source is already {}".format(param))
                        else:
                            set_setting(message.chat.id, "source", param)
                            set_setting(message.chat.id, "prev_source", prev_source)
                            bot.send_message(message.chat.id, "New message source is {}".format(param))
                elif message.chat.id == config["god_id"]:
                    bot.send_message(message.chat.id, "Hi, god.")
                    if action == "debug":
                        if param == "on":
                            set_setting(message.chat.id, "debug", True)
                        else:
                            set_setting(message.chat.id, "debug", False)
                else:
                    bot.send_message(message.chat.id, "Undefined action.")

        @bot.channel_post_handler(regexp='^!ignore ')
        @bot.message_handler(regexp='^!ignore ')
        def ignore(message):

            segs = message.text.split(" ")
            if len(segs) >= 2:
                segs.pop(0)
                items = segs

            if len(items):

                ignore_list = message.chat.gatekeeper_chat_data['settings']['ignored']
                ignore_list.extend(items)
                ignore_list = list(set(ignore_list))
                set_setting(message.chat.id, "ignored", ignore_list)
            else:
                bot.send_message(message.chat.id, "Syntax error.")

        @bot.channel_post_handler(regexp='^!unignore ')
        @bot.message_handler(regexp='^!unignore ')
        def unignore(message):

            segs = message.text.split(" ")
            if len(segs) >= 2:
                segs.pop(0)
                items = segs

            if len(items):
                ignore_list = message.chat.gatekeeper_chat_data['settings']['ignored']
                for item in items:
                    if item in ignore_list:
                        ignore_list.remove(item)
                ignore_list = list(set(ignore_list))
                set_setting(message.chat.id, "ignored", ignore_list)
            else:
                bot.send_message(message.chat.id, "Syntax error.")

        @bot.channel_post_handler(func=lambda m: m.text == "!stat")
        @bot.message_handler(func=lambda m: m.text == "!stat")
        def stat(message):
            chat = message.chat.gatekeeper_chat_data

            msg = """
Your settings:
    NSFW is {nsfw},
    Spoilers is {spoilers},
    Posts source is {source},
    Read posts count is {read_posts_count},
    Logged in: {logged_in}
Ignored subreddits/users:
    {ignore_list}
            """.format(read_posts_count=read_posts_count(chat['id']), logged_in=chat['settings']['token'] is not None, ignore_list="\n    ".join(chat['settings']['ignored']), ** chat['settings'])
            bot.send_message(message.chat.id, msg)

        @bot.message_handler(func=lambda m: m.text in reddit_config['trigger'])
        @bot.channel_post_handler(func=lambda m: m.text in reddit_config['trigger'])
        @bot.message_handler(regexp="^One more and I'm going to sleep$")
        @bot.channel_post_handler(regexp="^One more and I'm going to sleep$")
        def handle_dot(message, iteration=0):
            post = get_post(message.chat.gatekeeper_chat_data)
            if post:
                memorize(message.chat.id, post['name'])
                try:
                    file_type, media, body = compose_post(post)
                    how_to_send, what_to_send = compose_message(body=body, media_type=file_type, media=media, chat_id=message.chat.id)



                    res = []
                    res.append(types.InlineKeyboardButton("🔺", callback_data=json.dumps({'post':post['name'], 'do':"upvote"})))
                    res.append(types.InlineKeyboardButton("🔻", callback_data=json.dumps({'post':post['name'], 'do':"downvote"})))
                    res.append(types.InlineKeyboardButton("➕", callback_data=json.dumps({'post':post['name'], 'do':"more_options"})))
                    #res.append(types.InlineKeyboardButton("iga", callback_data=json.dumps({'author':post['author_fullname'], 'do':"ignore_au"})))
                    #res.append(types.InlineKeyboardButton("subs", callback_data=json.dumps({'subreddit':post['subreddit_id'], 'do':"sub_p"})))
                    #res.append(types.InlineKeyboardButton("suba", callback_data=json.dumps({'author':post['author_fullname'], 'do':"sub_a"})))
                    markup = types.InlineKeyboardMarkup(row_width=len(res))
                    markup.add(*res)
                    what_to_send['reply_markup'] = markup
                    how_to_send['function'](parse_mode="Markdown", ** what_to_send)
                except Exception as e:
                    print(e)
                    #return
                    if iteration <= 5:
                        if iteration > 2:
                            time.sleep(iteration)
                        bot.send_message(message.chat.id, "For some reason I failed to deliver https://reddit.com" + post['permalink'] + "\nHere, take another one:", disable_web_page_preview=False)
                        handle_dot(message, iteration + 1)
                    else:
                        bot.send_message(message.chat.id, "Failed to deliver more than 5 posts, contact administrator.\nAlso, are you sure your post source is correct?")

            else:
                try:

                    bot.send_animation(message.chat.id, animation='CgADAgADzQMAAjSHqEtFZUPgPn9dOgI', caption="Cat is preparing new posts for you, please try again later.")
                except Exception as e:
                    print(e)
                    bot.send_animation(message.chat.id, animation=open("./resources/loading.gif", 'rb'), caption="Cat is preparing new posts for you, please try again later.")




        @bot.message_handler(regexp="https:\/\/((.*)\.|)reddit\.com\/")
        @bot.channel_post_handler(regexp="https:\/\/((.*)\.|)reddit\.com\/")
        def handle_post(message):
            try:
                #print('url?', message.text)
                url = re.match('(.*)https:\/\/((.*)\.|)reddit\.com\/(?P<url>(.+))\/', message.text, re.DOTALL).group('url')
                #print("?", url)
            except:
                return
            temp = pool.do_request("https://oauth.reddit.com/" + url, chat_id=message.chat.id, full_response=True)
            try:
                post = temp[0]['data']['children'][0]['data']
            except:
                return

            #temp = pool.do_request("")
            try:
                file_type, media, body = compose_post(post)
                how_to_send, what_to_send = compose_message(body=body, media_type=file_type, media=media, chat_id=message.chat.id)

                res = []
                res.append(types.InlineKeyboardButton("🔺", callback_data=json.dumps({'post':post['name'], 'do':"upvote"})))
                res.append(types.InlineKeyboardButton("🔻", callback_data=json.dumps({'post':post['name'], 'do':"downvote"})))
                res.append(types.InlineKeyboardButton("➕", callback_data=json.dumps({'post':post['name'], 'do':"more_options"})))
                #res.append(types.InlineKeyboardButton("iga", callback_data=json.dumps({'author':post['author_fullname'], 'do':"ignore_au"})))
                #res.append(types.InlineKeyboardButton("subs", callback_data=json.dumps({'subreddit':post['subreddit_id'], 'do':"sub_p"})))
                #res.append(types.InlineKeyboardButton("suba", callback_data=json.dumps({'author':post['author_fullname'], 'do':"sub_a"})))
                markup = types.InlineKeyboardMarkup(row_width=len(res))
                markup.add(*res)
                what_to_send['reply_markup'] = markup
                how_to_send['function'](parse_mode="Markdown", ** what_to_send)

                bot.delete_message(message.chat.id, message.message_id)
            except Exception as e:
                #raise(e)
                pass

        @bot.channel_post_handler(regexp='^!login$')
        @bot.message_handler(regexp='^!login$')
        @bot.message_handler(commands=['login'])
        @bot.channel_post_handler(commands=['login'])
        def register(message=None, chat_id=None):
            if message:
                chat_id = message.chat.id
            bot.send_message(chat_id, "https://www.reddit.com/api/v1/authorize?" +
                             "client_id=" + reddit_config['id'] + "&" +
                             "response_type=code&" +
                             "state=" + Fernet(reddit_config['internal_secret'].encode()).encrypt(str(chat_id).encode()).decode('utf-8') + "&" +
                             "redirect_uri=" + reddit_config['redirect_uri'] + "&" +
                             "duration=permanent&" +
                             "scope=identity,vote,read,subscribe,history", disable_web_page_preview=True
                             )
        @bot.channel_post_handler(regexp='^!logout$')
        @bot.message_handler(regexp='^!logout$')
        @bot.message_handler(commands=['logout'])
        @bot.channel_post_handler(commands=['logout'])
        def register(message=None, chat_id=None):
            if message:
                chat_id = message.chat.id
            set_setting(chat_id, "token", None)
            set_setting(chat_id, "refresh_token", None)

        @bot.channel_post_handler(regexp='^!button$')
        @bot.message_handler(regexp='^!button$')
        @bot.message_handler(commands=['button'])
        @bot.channel_post_handler(commands=['button'])
        def button(message=None):
            if message.chat.type in ['private', 'group', 'supergroup']:
                bkb = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
                b = types.KeyboardButton('MOAR                                           ')
                #bkb.row(b, types.KeyboardButton('/menu'))
                bkb.add(b)
            else:
                bkb = None
            if bkb:
                bot.send_message(message.chat.id, "Type `MOAR`", parse_mode="Markdown", reply_markup=bkb)


        @bot.channel_post_handler(regexp='^!me$')
        @bot.message_handler(regexp='^!me$')
        def me(message=None, chat_id=None):
            if message:
                chat_id = message.chat.id

            if message.chat.gatekeeper_chat_data['settings']['token'] is not None:
                token = tokenstuff(message.chat.id)
                response = request_url("https://oauth.reddit.com/api/v1/me", None, [('Authorization', 'bearer ' + token)]);
                bot.send_message(message.chat.id, "{username}".format(username=response['name']))
            else:
                bot.send_message(message.chat.id, "I don't know who you are on reddit.")

        @bot.callback_query_handler(func=lambda call: True)
        def callback_query(call):
            try:
                data = call.data
                chat_id = call.from_user.id
                chat = get_chat(chat_id)
                if not chat:
                    bot.answer_callback_query(call.id, "Send /login to bot to in order to vote and do other stuff.")
                    #bot.send_message(chat_id, "You should /login to reddit api in order to vote and do other stuff with me.")
                    return
                if chat['settings']['token'] is None:
                    bot.send_message(chat_id, "You should /login to reddit api in order to vote and do other stuff with me.")
                    return


                data = json.loads(data)

                if data['do'] == 'ignore_sr':
                    post = reddit_get_one_post(data['post'])
                    subreddit = '/' + post['subreddit_name_prefixed']

                    ignore_list = chat['settings']['ignored']
                    ignore_list.append(subreddit)
                    ignore_list = list(set(ignore_list))
                    set_setting(chat['id'], "ignored", ignore_list)

                    bot.answer_callback_query(call.id, subreddit + " ignored.")

                    cbq_do_more_options(call, chat, post=post)


                    pass
                elif data['do'] == 'unignore_sr':
                    post = reddit_get_one_post(data['post'])
                    subreddit = '/' + post['subreddit_name_prefixed']

                    ignore_list = chat['settings']['ignored']
                    if subreddit in ignore_list:
                        ignore_list.remove(subreddit)
                        ignore_list = list(set(ignore_list))
                        set_setting(chat['id'], "ignored", ignore_list)

                        bot.answer_callback_query(call.id, subreddit + " unignored.")
                        cbq_do_more_options(call, chat, post=post)
                    else:
                        bot.answer_callback_query(call.id, subreddit + " is not in ignore list.")
                        cbq_do_more_options(call, chat, post=post)

                    pass
                elif data['do'] == 'ignore_au':
                    post = reddit_get_one_post(data['post'])
                    author = '/u/' + post['author']

                    ignore_list = chat['settings']['ignored']
                    ignore_list.append(author)
                    ignore_list = list(set(ignore_list))
                    set_setting(chat['id'], "ignored", ignore_list)

                    bot.answer_callback_query(call.id, author + " ignored.")

                    cbq_do_more_options(call, chat, post=post)


                    pass
                elif data['do'] == 'unignore_au':
                    post = reddit_get_one_post(data['post'])
                    author = '/u/' + post['author']

                    ignore_list = chat['settings']['ignored']
                    if author in ignore_list:
                        ignore_list.remove(author)
                        ignore_list = list(set(ignore_list))
                        set_setting(chat['id'], "ignored", ignore_list)

                        bot.answer_callback_query(call.id, author + " unignored.")
                        cbq_do_more_options(call, chat, post=post)
                    else:
                        bot.answer_callback_query(call.id, author + " is not in ignore list.")
                        cbq_do_more_options(call, chat, post=post)

                    pass
                elif data['do'] == 'upvote':
                    token = tokenstuff(chat_id)
                    response = request_url("https://oauth.reddit.com/api/vote", {'dir':1, 'id':data['post']}, [('Authorization', 'bearer ' + token)]);
                    bot.answer_callback_query(call.id, "Upvoted")
                    print(response)
                    pass

                elif data['do'] == 'downvote':
                    token = tokenstuff(chat_id)
                    response = request_url("https://oauth.reddit.com/api/vote", {'dir':-1, 'id':data['post']}, [('Authorization', 'bearer ' + token)]);
                    bot.answer_callback_query(call.id, "Downvoted.")
                    print(response)
                    pass
                elif data['do'] == 'set_src_sub':
                    prev_source = chat['settings']['source']
                    post = reddit_get_one_post(data['post'])
                    source = '/' + post['subreddit_name_prefixed']
                    if prev_source == source:
                        bot.answer_callback_query(call.id, "Source is already " + source)
                    else:
                        set_setting(chat['id'], "source", source)
                        set_setting(chat['id'], "prev_source", prev_source)
                        bot.answer_callback_query(call.id, "New post source is " + source)

                elif data['do'] == 'set_src_user':
                    prev_source = chat['settings']['source']
                    post = reddit_get_one_post(data['post'])
                    source = '/user/' + post['author'] + '/submitted'
                    if prev_source == source:
                        bot.answer_callback_query(call.id, "Source is already " + source)
                    else:
                        set_setting(chat['id'], "source", source)
                        set_setting(chat['id'], "prev_source", prev_source)
                        bot.answer_callback_query(call.id, "New post source is " + source)

                elif data['do'] == 'set_src_prev':
                    if 'prev_source' in chat['settings']:
                        new_prev_source = chat['settings']['source']
                        if chat['settings']['prev_source'] == new_prev_source:
                            bot.answer_callback_query(call.id, "Source is already " + new_prev_source)
                        else:
                            set_setting(chat['id'], "source", chat['settings']['prev_source'])
                            set_setting(chat['id'], "prev_source", new_prev_source)
                            bot.answer_callback_query(call.id, "New post source is " + new_prev_source)


                elif data['do'] == 'more_options':
                    cbq_do_more_options(call, chat, postid=data['post'])

                    #res.append(types.InlineKeyboardButton("🚫", callback_data=json.dumps({'postid':post['id'], 'do':"ignore_sr"})))

                elif data['do'] == 'less_options':
                    res = []
                    res.append(types.InlineKeyboardButton("🔺", callback_data=json.dumps({'post':data['post'], 'do':"upvote"})))
                    res.append(types.InlineKeyboardButton("🔻", callback_data=json.dumps({'post':data['post'], 'do':"downvote"})))
                    res.append(types.InlineKeyboardButton("➕", callback_data=json.dumps({'post':data['post'], 'do':"more_options"})))
                    markup = types.InlineKeyboardMarkup(row_width=len(res))
                    markup.add(*res)
                    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)


            except Exception as e:
                print(e)
                #raise(e)
            finally:
                try:
                    bot.answer_callback_query(call.id, "")
                except:
                    pass

            #return

        @bot.channel_post_handler(regexp='^!menu$')
        @bot.message_handler(regexp='^!menu$')
        @bot.message_handler(commands=['menu'])
        @bot.channel_post_handler(commands=['menu'])
        def menu(message):
            res = []

            text = """Here you can find your current settings and change them.
    NSFW is {nsfw},
    Spoilers is {spoilers}
    Posts source is {source}
    Read posts count is {read_posts_count}
    {logged_in_text}"""

            chat = get_chat(message.chat.id)
            settings = chat['settings']

            is_logged = 'token' in settings and settings['token'] != ''
            nsfw = 'nsfw' in settings and settings['nsfw'] == True
            spoilers = 'spoilers' in settings and settings['spoilers'] == True

            logged_in_text = ''


            markup = types.InlineKeyboardMarkup(row_width=2)
            if is_logged:
                token = tokenstuff(message.chat.id)
                response = request_url("https://oauth.reddit.com/api/v1/me", None, [('Authorization', 'bearer ' + token)]);
                logged_in_text = "Logged in as " + response['name']
                markup.row(types.InlineKeyboardButton("Logout from " + response['name'], callback_data=json.dumps({'do':"logout"})))
            else:
                logged_in_text = "Not logged in."
                markup.row(types.InlineKeyboardButton("Login", callback_data=json.dumps({'do':"login"})))



            res.append(types.InlineKeyboardButton("Show NSFW", callback_data=json.dumps({'do':"show_nsfw"})))
            res.append(types.InlineKeyboardButton("Hide NSFW", callback_data=json.dumps({'do':"hide_nsfw"})))
            res.append(types.InlineKeyboardButton("Show spoilers", callback_data=json.dumps({'do':"show_spoilers"})))
            res.append(types.InlineKeyboardButton("Hide spoilers", callback_data=json.dumps({'do':"hide_spoilers"})))

            res.append(types.InlineKeyboardButton("Set /r/all as source", callback_data=json.dumps({'do':"source_r_all"})))
            if is_logged:
                res.append(types.InlineKeyboardButton("Set /best as source", callback_data=json.dumps({'do':"source_best"})))

            res.append(types.InlineKeyboardButton("Clear read posts", callback_data=json.dumps({'do':"clear_read"})))
            res.append(types.InlineKeyboardButton("Drop source cache", callback_data=json.dumps({'do':"drop_cache"})))
            markup.add(*res)
            if 'prev_source' in chat['settings']:
                markup.row(types.InlineKeyboardButton("Set prev source [" + chat['settings']['prev_source'] + "]", callback_data=json.dumps({'do':"set_src_prev"})))
            markup.row(types.InlineKeyboardButton("Set new source", callback_data=json.dumps({'do':"new_source"})))



            #res.append(types.InlineKeyboardButton("🚫", callback_data=json.dumps({'postid':post['id'], 'do':"ignore_sr"})))
            #res.append(types.InlineKeyboardButton("iga", callback_data=json.dumps({'author':post['author_fullname'], 'do':"ignore_au"})))
            #res.append(types.InlineKeyboardButton("subs", callback_data=json.dumps({'subreddit':post['subreddit_id'], 'do':"sub_p"})))
            #res.append(types.InlineKeyboardButton("suba", callback_data=json.dumps({'author':post['author_fullname'], 'do':"sub_a"})))



            bot.send_message(message.chat.id, text, reply_markup=markup)

def cbq_do_more_options(call, chat, postid=None, post=None):
    if post is None:
        if postid is None:
            raise("no post and no post id")
        one_post = reddit_get_one_post(postid)
    else:
        one_post = post

    if not one_post:
        bot.answer_callback_query(call.id, "Can't find post.")

    subreddit = one_post['subreddit']
    author = one_post['author']
    sub_ignored = '/r/' + subreddit in chat['settings']['ignored']
    author_ignored = '/u/' + author in chat['settings']['ignored']

    row1 = []
    row1.append(types.InlineKeyboardButton("🔺", callback_data=json.dumps({'post':one_post['name'], 'do':"upvote"})))
    row1.append(types.InlineKeyboardButton("🔻", callback_data=json.dumps({'post':one_post['name'], 'do':"downvote"})))
    row1.append(types.InlineKeyboardButton("➖", callback_data=json.dumps({'post':one_post['name'], 'do':"less_options"})))
    #res.append(types.InlineKeyboardButton("iga", callback_data=json.dumps({'author':post['author_fullname'], 'do':"ignore_au"})))
    #res.append(types.InlineKeyboardButton("subs", callback_data=json.dumps({'subreddit':post['subreddit_id'], 'do':"sub_p"})))
    #res.append(types.InlineKeyboardButton("suba", callback_data=json.dumps({'author':post['author_fullname'], 'do':"sub_a"})))
    row2 = []

    row2.append(types.InlineKeyboardButton("More from /r/" + subreddit, callback_data=json.dumps({'post':one_post['name'], 'do':"set_src_sub"})))
    row2.append(types.InlineKeyboardButton("More from /u/" + author, callback_data=json.dumps({'post':one_post['name'], 'do':"set_src_user"})))

    if sub_ignored:
        row2.append(types.InlineKeyboardButton("Unignore /r/" + subreddit, callback_data=json.dumps({'post':one_post['name'], 'do':"unignore_sr"})))
    else:
        row2.append(types.InlineKeyboardButton("Ignore /r/" + subreddit, callback_data=json.dumps({'post':one_post['name'], 'do':"ignore_sr"})))

    if author_ignored:
        row2.append(types.InlineKeyboardButton("Unignore /u/" + author, callback_data=json.dumps({'post':one_post['name'], 'do':"unignore_au"})))
    else:
        row2.append(types.InlineKeyboardButton("Ignore /u/" + author, callback_data=json.dumps({'post':one_post['name'], 'do':"ignore_au"})))



    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.row(*row1)
    markup.add(*row2)

    if 'prev_source' in chat['settings']:
        markup.row(types.InlineKeyboardButton("Set prev source [" + chat['settings']['prev_source'] + "]", callback_data=json.dumps({'do':"set_src_prev"})))

    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

def reddit_get_one_post(postid):
    postid = postid.split('_')
    if len(postid) > 1:
        postid = postid[1]
    else:
        postid = postid[0]
    #token = tokenstuff(chat_id)
    response = request_url("https://api.reddit.com/" + postid + "?limit=1", None)
    return response[0]['data']['children'][0]['data']


def memorize(chat_id, name):
    print("Memorizing", name, "for chat", chat_id)
    db.query("insert into read_posts(chat_id, post, date_added) values (?,?,datetime('now'))", (chat_id, name))
    #db.commit()
    #read_posts.append(post['name'])

def filter_read(chat, posts):
    filtered_posts = []
    names = [post.get('data').get('name') for post in posts]

    ps = "(" + '),('.join(["?" for n in range(0, len(names))]) + ")"
    query = """
    with posts(name) as (
        select * from
            (values {placeholder})
        ) select name from posts left join read_posts on posts.name = read_posts.post and read_posts.chat_id = {chat_id} where id is null
    """.format(placeholder=ps, chat_id=chat['id'])
    unread = db.query(query, names);
    unread = [one[0] for one in unread]

    for post in posts:
        if post['data']["name"] in unread:
            filtered_posts.append(post)

    return filtered_posts



def get_post(chat, after=False, retry=0):
    afstr = ""
    if retry > 0:
        if after:
            afstr = "?after={}".format(after)
    if retry > 5:
        return False
    stack = pool.get_posts("https://oauth.reddit.com/{}{}".format(chat['settings']['source'].lstrip('/'), afstr), chat['id'], after)
    if not len(stack):
        return False
    messages = []
    for msg in stack:
        #print "/r/" + msg['data']['subreddit'], ("/r/" + msg['data']['subreddit']) in chat['settings']['ignored']
        if ("/r/" + msg['data']['subreddit']) in chat['settings']['ignored'] or ("/u/" + msg['data']['author']) in chat['settings']['ignored'] or msg['data']['stickied'] == True:
            pass
        elif msg['data']['over_18'] == True and chat['settings']['nsfw'] == False:
            pass
        elif ('spoiler' in msg['data'] and msg['data']['spoiler'] == True) and chat['settings']['spoilers'] == False:
            pass
        else:
            messages.append(msg)

    messages = filter_read(chat, messages)

    if len(messages) == 0:
        print("MOAR")
        last = stack.pop()
        return get_post(chat, after=last['data']['name'], retry=retry + 1)

    valid_posts = messages
    if not len(valid_posts):
        return False
    post = valid_posts.pop(0)
    return post['data']

def compose_message(body, media_type=None, media=None, chat_id=None):
    to_send = {}
    to_send['function'] = bot.send_message
    to_send['name'] = "text"
    if media is not None:
        if media_type == "image":
            to_send['function'] = bot.send_photo
            to_send['name'] = "photo"
        elif media_type == "gif":
            to_send['function'] = bot.send_animation
            to_send['name'] = "animation"
        elif media_type == "video":
            to_send['function'] = bot.send_video
            to_send['name'] = "data"
        else:
            print('wtf is this?', media)

    to_send_really = {"text" if to_send["name"] == "text" else "caption":body}
    if media is not None:
        to_send_really[to_send['name']] = media
    if chat_id:
        to_send_really['chat_id'] = chat_id

    if to_send['name'] == "text":
        to_send_really['disable_web_page_preview'] = True

    if to_send['name'] != "text" and len(to_send_really['caption']) > 1024:
        print("longer")
        del to_send_really[to_send['name']]

        to_send['name'] = "text"
        to_send['function'] = bot.send_message
        to_send_really['text'] = "[ ](" + media + ")" + to_send_really['caption']
        to_send_really['disable_web_page_preview'] = False
        del to_send_really['caption']

    if to_send['name'] == "text" and len(to_send_really['text']) > 4096:
        print("longer2")
        bottom = re.match('(.*)(?P<bottom>\[\/r\/(.+?)$)', to_send_really['text'], re.DOTALL).group('bottom')
        #print(to_send_really['text'])
        url = re.match('.*\[\/r\/.+?\]\((?P<url>.+?)\)', bottom).group('url')
        print(bottom, url)
        altered_bottom = "...\n[Read more](" + url + ")\n"
        bottom = altered_bottom + bottom
        to_send_really['text'] = to_send_really['text'][0:4096-len(bottom)]
        to_send_really['text'] += bottom


    return to_send, to_send_really

def compose_post(post):

    print (json.dumps(post))


    awards = []

    if len(post['all_awardings']):
        for award in post['all_awardings']:
            if award['name'] == "Silver":
                awards.append('🥈')
            elif award['name'] == "Gold":
                awards.append('🥇')
            elif award['name'] == "Platinum":
                awards.append('🎖')
            #awards.append(award['name'])

    if 'crosspost_parent' in post:
        hint, media = get_media(post['crosspost_parent_list'][0])
    else:
        hint, media = get_media(post)


    if 'post_hint' in post:
        _hint = post['post_hint']
    else:
        _hint = ''

    title = post['title']
    subreddit = post['subreddit']
    permalink = post['permalink']
    url = post['url']
    selftext = post['selftext']
    upvotes = post['score']
    #author = post['author']

    print(awards)
    print(title)
    print(subreddit)
    print(hint, _hint)
    print(media)
    print(url)
    print(post['domain'])

    if selftext:
        content = """*{title}*
{selftext}""".format(title=sanitize_md(title, full=True), selftext=sanitize_md(selftext, full=False))
    else:
        content = "{title}".format(title=sanitize_md(title, full=True))

    #if media == None and hint == 'link':
    #    content += "\n[Read more]({url})".format(url=url)

    #if hint == 'link' :
    #    content += "\n[Read more]({url})".format(url=url)
    if (_hint == 'link' or _hint == '') and post['domain'] not in ["v.redd.it", "i.redd.it", "i.imgur.com", "imgur.com", "www.reddit.com", "gfycat.com"] and "self." not in post['domain']:
        content += "\n[Read more]({url})".format(url=url)



    if hint == 'image' and 'video' in _hint and 'oembed' in post['media']:
        content += "\n{url}".format(url=url)

    if media is not None:
        media = unescape(media)


    body = """{content}
    \n[/r/{subreddit}](https://reddit.com{permalink}) ({upvotes} upvotes) {awards}
    """.format(awards=''.join(awards), content=content, subreddit=subreddit, permalink=permalink, upvotes=upvotes);

    body = unescape(body)
    print(body)
    return hint, media, body

def get_media(post):
    if 'post_hint' in post:
        hint = post['post_hint']
    else:
        hint = None

    media = None

    video_preview = False

    """
    trying to get video preview from preview.reddit_video_preview
    if we succeed, that means we have gif or video post
    """

    try:
        if post['preview']['reddit_video_preview']:

            if post['preview']['reddit_video_preview']['is_gif']:
                hint = 'gif'
            else:
                hint = 'video'
            media = post['preview']['reddit_video_preview']['fallback_url']
            video_preview = True
    except:
        pass

    """
    next, if reddit post hint contains 'video' in it (like "video", "rich:video", "hosted:video")
    and video_preview is false we again trying to get video preview, but from post.media.reddit_video and post.preview.reddit_video
    """
    if hint is not None and 'video' in hint and ('preview' in post):
        if not video_preview:
            hint = 'link'
            if 'reddit_video' in post['media']:
                hint = 'video'
                media = post['media']['reddit_video']['fallback_url']
            elif 'reddit_video' in post['preview']:
                hint = 'video'
                media = post['preview']['reddit_video']['fallback_url']

        #hint = gif_or_video(post)
    """If we successfully extracted video during previous steps,
    hint itself should now be "video" or "gif" even if it wasn't.

    Now we are trying to get medium resolution gif/video which reddit generates
    by itself. If we fail -- we still have big sized 'fallback' preview
    from previous steps.

    In other case we just need to extract image from post.preview
    whatever image fits needed size.
    """
    print("pew", hint, media)
    if hint in ['video', 'gif']:
        _hint, _media = get_image(post, vonly=True)
        print("pew2", _hint, _media)
        if _media is not None and _hint is not None and ('gif' not in _media or '1080' in media):
            hint = _hint
            media = _media
    elif hint is not None:#if hint in ['gif', 'image', 'link']:
        _hint, media = get_image(post)
        if media is not None:
            hint = _hint

    return hint, media


def get_image(post, vonly=False):

    if 'variants' in post['preview']['images'][0] and len(post['preview']['images'][0]['variants']):
        if 'mp4' in post['preview']['images'][0]['variants']:
            images = post['preview']['images'][0]['variants']['mp4']['resolutions']
            images.append(post['preview']['images'][0]['variants']['mp4']['source'])
            threshold = 480
            hint = 'gif'
        elif 'gif' in post['preview']['images'][0]['variants']:
            images = post['preview']['images'][0]['variants']['gif']['resolutions']
            images.append(post['preview']['images'][0]['variants']['gif']['source'])
            threshold = 480
            hint = 'gif'
        else:
            images = post['preview']['images'][0]['resolutions']
            images.append(post['preview']['images'][0]['source'])
            threshold = 1000
            hint = 'image'
    else:
        images = post['preview']['images'][0]['resolutions']
        images.append(post['preview']['images'][0]['source'])
        hint = 'image'
        threshold = 1000
    if vonly and hint == 'image':
        return None, None

    maxw = 0
    maxh = 0
    retimage = None
    for image in images:
        if image['width'] > maxw and image['height'] > maxh:
            maxw = image['width']
            maxh = image['height']
            if image['width'] < threshold: # and image['height'] < 1000:
                retimage = image['url']

    return hint, retimage


def sanitize_md(txt, full=False):
    to_sanitize = ["_", "*", "`", "["]
    for char in to_sanitize:
        if full and char is not "*":
            print(char, txt)
            if char in ["[", "]"]:
                oldchar = "\\" + char
            else:
                oldchar = char
            txt = re.sub(oldchar, "\\" + char, txt)
        else:
            if txt.count(char) % 2:
                pos = txt.rfind(char)
                if pos > -1:
                    txt = txt[:pos] + txt[pos:].replace(char, "\\" + char)
    return txt


def read_posts_count(id):
    try:
        return db.query("select count(id) as count from read_posts where chat_id = ?", [id])[0][0]
    except Exception as e:
        return 0



def helpmsg():
    return """Commands:
    `!login` or /login to log in through reddit api
    `!logout` or /logout to log out from reddit api
    `!me` to check login status
    `!set nsfw on|off` to set nsfw on or off
    `!set source /r/subreddit` to switch post source to /r/subreddit. `/best` works too.
    `!ignore /r/subreddit1 /u/user1 /r/subreddit2 /u/user2` to ignore users and subreddits.
    `!unignore /r/subreddit1 /u/user1 /r/subreddit2 /u/user2` to ignore users and subreddits.
    `!button` or /button to show button for requesting new posts.
    """


