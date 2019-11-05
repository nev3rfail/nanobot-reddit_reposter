#encoding: UTF-8
import json
from plugins import gatekeeper
from plugins.gatekeeper import *

def register_chat(chat_id, admin_id):
    settings = {
        'admin_id':admin_id,
        'nsfw':False,
        'spoilers':False,
        'source':'/r/all',
        'ignored':[],
        'token':None,
        'refresh_token':None,
        'added':None,
        'ttl':None
    }
    db.query("insert into chats(chat_id, settings) VALUES (?, ?)", [chat_id, json.dumps(settings)])
    #db.commit()
    return get_chat(chat_id)

gatekeeper.register_chat = register_chat


