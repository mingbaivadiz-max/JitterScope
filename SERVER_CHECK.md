# Проверка каталога серверов

Проверено: 2026-10-28T01:52:35+05:00.

Источники — официальные документы издателей и конфигурация Valve. Это подтверждает назначение диагностического адреса, но не гарантирует ICMP-ответ или пинг как в матче. В колонке результата — один настоящий ICMP-запрос с текущего подключения (тайм-аут 900 мс), а не многократная проверка стабильности. Доменный адрес может вернуть другой IP при следующем определении DNS. Отсутствие ICMP-ответа не означает, что игра недоступна.

| Узел | Имя / IPv4 | Определённый IP | ICMP сейчас | Источник |
|---|---|---|---|---|
| Cloudflare · контрольный узел | `1.1.1.1` | `1.1.1.1` | 42.9 мс | [Официальный источник](https://developers.cloudflare.com/1.1.1.1/ip-addresses/) |
| Fortnite · Германия | `ping-de.ds.on.epicgames.com` | `3.66.90.162` | 96.1 мс | [Официальный источник](https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US) |
| Fortnite · Франция | `ping-fr.ds.on.epicgames.com` | `15.236.8.96` | 103.3 мс | [Официальный источник](https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US) |
| Fortnite · Великобритания | `ping-gb.ds.on.epicgames.com` | `18.133.101.207` | 95.8 мс | [Официальный источник](https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US) |
| Fortnite · Бахрейн | `ping-bah.ds.on.epicgames.com` | `34.18.144.86` | 183.2 мс | [Официальный источник](https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US) |
| Fortnite · Мумбаи | `ping-mum.ds.on.epicgames.com` | `3.110.24.16` | 203.8 мс | [Официальный источник](https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US) |
| Fortnite · Токио | `ping-tok.ds.on.epicgames.com` | `35.72.18.102` | 256.6 мс | [Официальный источник](https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US) |
| Fortnite · Сидней | `ping-syd.ds.on.epicgames.com` | `3.25.159.42` | 375.7 мс | [Официальный источник](https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US) |
| Fortnite · Вирджиния | `ping-va.ds.on.epicgames.com` | `44.192.142.31` | 189.6 мс | [Официальный источник](https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US) |
| Fortnite · Техас | `ping-tx.ds.on.epicgames.com` | `18.88.1.126` | 207.5 мс | [Официальный источник](https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US) |
| Fortnite · Орегон | `ping-or.ds.on.epicgames.com` | `44.230.113.121` | 262.0 мс | [Официальный источник](https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US) |
| Fortnite · Сан-Паулу | `ping-sao.ds.on.epicgames.com` | `15.228.25.138` | 294.7 мс | [Официальный источник](https://www.epicgames.com/help/c-34254770/c-37371353/a22355516?lang=en-US) |
| VALORANT · EU · диагностика | `162.249.72.1` | `162.249.72.1` | Нет ICMP-ответа за 900 мс | [Официальный источник](https://support.riotgames.com/en-us/valorant/connectivity/how-to-use-tracert-to-obtain-network-logs) |
| VALORANT · EU / восток России · диагностика | `13.248.220.97` | `13.248.220.97` | 93.5 мс | [Официальный источник](https://support.riotgames.com/en-us/valorant/connectivity/how-to-use-tracert-to-obtain-network-logs) |
| VALORANT · Азия / Сингапур · диагностика | `151.106.248.1` | `151.106.248.1` | Нет ICMP-ответа за 900 мс | [Официальный источник](https://support.riotgames.com/en-us/valorant/connectivity/how-to-use-tracert-to-obtain-network-logs) |
| VALORANT · Корея · диагностика | `103.219.128.1` | `103.219.128.1` | Нет ICMP-ответа за 900 мс | [Официальный источник](https://support.riotgames.com/en-us/valorant/connectivity/how-to-use-tracert-to-obtain-network-logs) |
| VALORANT · Северная Америка · диагностика | `192.207.0.1` | `192.207.0.1` | Нет ICMP-ответа за 900 мс | [Официальный источник](https://support.riotgames.com/en-us/valorant/connectivity/how-to-use-tracert-to-obtain-network-logs) |
| VALORANT · Бахрейн · диагностика | `99.83.199.240` | `99.83.199.240` | 88.3 мс | [Официальный источник](https://support.riotgames.com/en-us/valorant/connectivity/how-to-use-tracert-to-obtain-network-logs) |
| VALORANT · Мумбаи · диагностика | `75.2.66.166` | `75.2.66.166` | 86.3 мс | [Официальный источник](https://support.riotgames.com/en-us/valorant/connectivity/how-to-use-tracert-to-obtain-network-logs) |
| CS2 / Dota 2 · Франкфурт · SDR | `155.133.226.68` | `155.133.226.68` | 82.3 мс | [Официальный источник](https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=570) |
| CS2 / Dota 2 · Стокгольм · SDR | `162.254.198.41` | `162.254.198.41` | 96.8 мс | [Официальный источник](https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=570) |
| CS2 / Dota 2 · Вена · SDR | `146.66.155.66` | `146.66.155.66` | 105.8 мс | [Официальный источник](https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=570) |
| CS2 / Dota 2 · Варшава · SDR | `155.133.230.116` | `155.133.230.116` | 117.5 мс | [Официальный источник](https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=570) |
| CS2 / Dota 2 · Сингапур · SDR | `103.10.124.116` | `103.10.124.116` | 260.7 мс | [Официальный источник](https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=570) |
| Overwatch · EU · диагностика Blizzard | `185.60.112.157` | `185.60.112.157` | 105.6 мс | [Официальный источник](https://eu.forums.blizzard.com/en/overwatch/t/welcome-to-the-technical-support-forum/33) |

## Ограничения

- Fortnite: официальные ping endpoints отдельных подрегионов, не сервер выбранного матча.
- VALORANT: Riot публикует эти IP как цели tracert. Они могут не отвечать на ICMP Echo.
- CS2 / Dota 2: SDR-ретрансляторы из официальных JSON-конфигураций appid 730 и 570. Маршрут через Steam и UDP измеряются иначе, чем обычный ICMP.
- Overwatch: адрес из официального закреплённого сообщения поддержки 2018 года; используется как исторически опубликованный диагностический узел EU.
- Каталог не сканирует порты: TCP-порт выбирается пользователем. Для игровых пресетов оставлен ICMP.

## Конфигурация Valve

Ревизии: {'570': 1793064244, '730': 1793064244}.

[Dota 2, appid 570](https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=570) · [CS2, appid 730](https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=730)
