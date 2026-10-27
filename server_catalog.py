# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 SanyLok
"""Diagnostic endpoints checked against publisher sources on 2026-10-28.

An official diagnostic endpoint is not necessarily a match server, nor does its
publication guarantee that it answers ICMP from every network.
"""
CHECKED = "2026-10-28"
EPIC = "https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US"
RIOT = "https://support.riotgames.com/en-us/valorant/connectivity/how-to-use-tracert-to-obtain-network-logs"
BLIZZARD = "https://eu.forums.blizzard.com/en/overwatch/t/welcome-to-the-technical-support-forum/33"
VALVE = "https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=570"
VALVE_CS2 = "https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=730"

PRESETS = [
    {"name": "Cloudflare · контрольный узел", "host": "1.1.1.1", "source": "https://developers.cloudflare.com/1.1.1.1/ip-addresses/",
     "note": "Публичный DNS / контроль интернета. Не игровой сервер."},
]
for name, code in [("Германия", "de"), ("Франция", "fr"), ("Великобритания", "gb"),
                   ("Бахрейн", "bah"), ("Мумбаи", "mum"), ("Токио", "tok"),
                   ("Сидней", "syd"), ("Вирджиния", "va"), ("Техас", "tx"),
                   ("Орегон", "or"), ("Сан-Паулу", "sao")]:
    PRESETS.append({"name": f"Fortnite · {name}", "host": f"ping-{code}.ds.on.epicgames.com",
                    "source": EPIC, "note": "Официальный ping endpoint Epic. IP определяется через DNS; дата-центр матча может отличаться."})
for region, address in [("EU", "162.249.72.1"), ("EU / восток России", "13.248.220.97"),
                         ("Азия / Сингапур", "151.106.248.1"), ("Корея", "103.219.128.1"),
                         ("Северная Америка", "192.207.0.1"), ("Бахрейн", "99.83.199.240"),
                         ("Мумбаи", "75.2.66.166")]:
    PRESETS.append({"name": f"VALORANT · {region} · диагностика", "host": address,
                    "source": RIOT, "note": "Riot публикует этот адрес для tracert. ICMP Echo может фильтроваться; это не адрес конкретного матча."})
for city, address in [("Франкфурт", "155.133.226.68"), ("Стокгольм", "162.254.198.41"),
                       ("Вена", "146.66.155.66"), ("Варшава", "155.133.230.116"),
                       ("Сингапур", "103.10.124.116")]:
    PRESETS.append({"name": f"CS2 / Dota 2 · {city} · SDR", "host": address,
                    "source": VALVE, "source_extra": VALVE_CS2,
                    "note": "Ретранслятор из конфигурации Valve для appid 570 и 730. Только ICMP-оценка маршрута: SDR использует UDP, TCP-порт 27015 здесь не проверяется."})
PRESETS.append({"name": "Overwatch · EU · диагностика Blizzard", "host": "185.60.112.157",
                "source": BLIZZARD, "note": "Официальный пост поддержки Blizzard рекомендует адрес для трассировки/pathping. Пост 2018 года; это диагностический узел, не гарантия текущего сервера матча."})

SERVERS = {preset["name"]: preset["host"] for preset in PRESETS}
BY_HOST = {preset["host"]: preset for preset in PRESETS}
