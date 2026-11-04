#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Surgical overrides for ikabot.helpers.planRoutes (anti-detection human delays).

This file is NOT mounted over the stock module. Instead, bot_launcher execs it
into the *live* stock planRoutes module namespace at startup
(`exec(compile(...), planRoutes.__dict__)`), redefining only sendGoods and
executeRoutes. Every other name they use (city_url, actionRequest, getCity,
wait, getMinimumWaitingTime, getShipCapacity, waitForArrival, splitCargoBetweenFleets,
json, math, Decimal, time, random) resolves from the stock module's own globals.

Why not a full-file copy: shadowing the whole planRoutes.py freezes it at one
upstream version, so any function the upstream later adds (e.g. 7.6.0's
splitCargoBetweenFleets, imported by consolidateResources) goes missing and the
bot won't boot. Overriding only the two functions we tune keeps everything else
live, so additive upstream changes can't break us.

The only bodies here that differ from stock are the `time.sleep(random...)`
pauses — see the inline "Pausa ..." comments.
"""


def sendGoods(session, originCityId, destinationCityId, islandId, ships, send, useFreighters=False):
    """This function will execute one route
    Parameters
    ----------
    session : ikabot.web.session.Session
        Session object
    originCityId : int
        integer representing the ID of the origin city
    destinationCityId : int
        integer representing the ID of the destination city
    islandId : int
        integer representing the ID of the destination city's island
    ships : int
        integer representing the amount of ships needed to execute the route
    send : list
        array of resources to send
    """
    # this can fail if a random request is made in between this two posts
    while True:
        html = session.get()
        current_city = getCity(html)  # the city the bot is right now
        time.sleep(random.randint(2, 5))
        city = getCity(session.get(city_url + originCityId))  # the origin city
        currId = current_city["id"]

        # Change from the city the bot is sitting right now to the city we want to load resources from
        data = {
            "action": "header",
            "function": "changeCurrentCity",
            "actionRequest": actionRequest,
            "oldView": "city",
            "cityId": originCityId,
            "backgroundView": "city",
            "currentCityId": currId,
            "ajax": "1",
        }

        session.post(params=data)

        # Pausa humana entre mudar de cidade e confirmar o envio
        time.sleep(random.randint(3, 7))

        # Request to send the resources from the origin to the target
        data = {
            "action": "transportOperations",
            "function": "loadTransportersWithFreight",
            "destinationCityId": destinationCityId,
            "islandId": islandId,
            "oldView": "",
            "position": "",
            "avatar2Name": "",
            "city2Name": "",
            "type": "",
            "activeTab": "",
            "transportDisplayPrice": "0",
            "premiumTransporter": "0",
            "capacity": "5",
            "max_capacity": "5",
            "jetPropulsion": "0",
            "backgroundView": "city",
            "currentCityId": originCityId,
            "templateView": "transport",
            "currentTab": "tabSendTransporter",
            "actionRequest": actionRequest,
            "ajax": "1",
        }

        if useFreighters is False:
            shiptype = "transporters"
            data[shiptype] = ships
        else:
            shiptype = "usedFreightersShips"
            data[shiptype] = ships
            data["transporters"] = "0"
        # add amounts of resources to send
        for i in range(len(send)):
            if city["availableResources"][i] > 0:
                key = "cargo_resource" if i == 0 else "cargo_tradegood{:d}".format(i)
                data[key] = send[i]

        resp = session.post(params=data)
        resp = json.loads(resp, strict=False)
        if resp[3][1][0]["type"] == 10:
            break
        elif resp[3][1][0]["type"] == 11:
            wait(getMinimumWaitingTime(session))
        # Pausa aleatória no retry em vez de 5s fixo
        time.sleep(random.randint(4, 9))


def executeRoutes(session, routes, useFreighters=False):
    """This function will execute all the routes passed to it, regardless if there are enough ships available to do so
    Parameters
    ----------
    session : ikabot.web.session.Session
        Session object
    routes : list
        a list of tuples, each of which represent a route. A route is defined like so : (originCity,destinationCity,islandId,wood,wine,marble,crystal,sulfur). originCity and destintionCity should be passed as City objects
    """
    ship_capacity, freighter_capacity = getShipCapacity(session)
    for route in routes:
        (origin_city, destination_city, island_id, *toSend) = route
        destination_city_id = destination_city["id"]

        while sum(toSend) > 0:
            session.setStatus(
                f' Sending {toSend[0]}W, {toSend[1]}V, {toSend[2]}M, {toSend[3]}C, {toSend[4]}S | {origin_city["name"]} ---> {destination_city["name"]} '
            )
            ships_available = waitForArrival(session, useFreighters)
            if useFreighters is False:
                storageCapacityInShips = ships_available * ship_capacity
            else:
                storageCapacityInShips = ships_available * freighter_capacity

            html = session.get(city_url + str(origin_city["id"]))
            origin_city = getCity(html)
            html = session.get(city_url + str(destination_city_id))
            destination_city = getCity(html)
            foreign = str(destination_city["id"]) != str(destination_city_id)
            if foreign is False:
                storageCapacityInCity = destination_city["freeSpaceForResources"]

            send = []
            for i in range(len(toSend)):
                if foreign is False:
                    min_val = min(
                        origin_city["availableResources"][i],
                        toSend[i],
                        storageCapacityInShips,
                        storageCapacityInCity[i],
                    )
                else:
                    min_val = min(
                        origin_city["availableResources"][i],
                        toSend[i],
                        storageCapacityInShips,
                    )
                send.append(min_val)
                storageCapacityInShips -= send[i]
                toSend[i] -= send[i]

            resources_to_send = sum(send)
            if resources_to_send == 0:
                # no space available
                # wait an hour and try again
                wait(60 * 60)
                continue

            if useFreighters is False:
                available_ships = int(
                    math.ceil((Decimal(resources_to_send) / Decimal(ship_capacity)))
                )
            else:
                available_ships = int(
                    math.ceil((Decimal(resources_to_send) / Decimal(freighter_capacity)))
                )
            sendGoods(
                session,
                origin_city["id"],
                destination_city_id,
                island_id,
                available_ships,
                send,
                useFreighters,
            )

            # Pausa humana entre frotas consecutivas — simula o utilizador a preparar
            # o próximo envio em vez de disparar imediatamente após o anterior
            if sum(toSend) > 0:
                time.sleep(random.randint(10, 25))

        # Pausa entre rotas distintas (origem/destino diferente)
        time.sleep(random.randint(12, 30))
