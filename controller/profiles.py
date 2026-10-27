# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 SanyLok
import json
from .model import validate_target


class Profiles:
    def __init__(self, settings):
        self.settings = settings
        try:
            raw = json.loads(settings.value('profiles/json','[]'))
            self.items = []
            for item in raw[:50] if isinstance(raw,list) else []:
                try:
                    self.items.append(self.validate(item))
                except (ValueError,TypeError,KeyError):
                    continue
        except (ValueError,TypeError,KeyError):
            self.items = []

    @staticmethod
    def validate(item):
        if not isinstance(item,dict):
            raise ValueError('Некорректный профиль')
        name = str(item['name']).strip()
        if not name or len(name) > 64:
            raise ValueError('Имя профиля должно содержать от 1 до 64 символов')
        host = validate_target(item['host'])
        port = int(item.get('port',443))
        if not 1 <= port <= 65535 or item.get('mode','icmp') not in ('icmp','tcp'):
            raise ValueError('Некорректный протокол или порт')
        return {'name':name,'host':host,'adapter':str(item.get('adapter') or ''),
                'mode':item.get('mode','icmp'),'port':port,
                'compare':[validate_target(host) for host in item.get('compare',[])[:5]]}

    def save(self, item):
        item = self.validate(item)
        items = [old for old in self.items if old['name'] != item['name']] + [item]
        if len(items) > 50:
            raise ValueError('Допустимо до 50 профилей')
        self.items = items
        self._persist()

    def remove(self, name):
        self.items = [item for item in self.items if item['name'] != name]
        self._persist()

    def _persist(self):
        self.settings.setValue('profiles/json',json.dumps(self.items,ensure_ascii=False))
        self.settings.sync()
