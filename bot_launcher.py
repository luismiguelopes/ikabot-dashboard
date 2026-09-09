#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deterministic launcher for the empire bot.

The container used to auto-start empireFunction by replaying interactive menu
keystrokes (``21 7 1 ... 21 7 3``). That is fragile: the numbers are screen
positions, so any upstream image that reorders the menus makes the navigation
land on the wrong entry and crash startup.

This launcher instead:
  1. logs in via the stock Session() (same code the menu uses),
  2. spawns empireFunction *by reference* as a background process (no menu
     indices involved, so a menu reorder can never break it),
  3. drops into the normal ikabot menu on PID 1, so ``docker attach ikabot``
     still gives the full interactive menu exactly as before.

Usage:  python3 bot_launcher.py <email> <password>
"""
import multiprocessing
import sys
import time

# Custom modules (empireFunction and its siblings) live here.
_FUNCTION_DIR = "/ikabot/ikabot/function"
if _FUNCTION_DIR not in sys.path:
    sys.path.insert(0, _FUNCTION_DIR)


def _run():
    import ikabot.config as config
    from ikabot.web.session import Session
    from ikabot.command_line import menu, init
    from ikabot.helpers.process import updateProcessList
    from empireFunction import empireFunction

    # Same startup housekeeping as command_line.init(): chdir HOME, ensure the
    # ika cookie file exists.
    init()

    # argv -> predetermined_input (email, password), ints where possible, so
    # Session() can pop them exactly as it does from the normal command line.
    config.has_params = len(sys.argv) > 1
    for arg in sys.argv[1:]:
        try:
            config.predetermined_input.append(int(arg))
        except ValueError:
            config.predetermined_input.append(arg)

    # Logs in; pops email + password from predetermined_input.
    session = Session()

    # Spawn empireFunction the same way the menu would (multiprocessing.Process
    # with the (session, event, stdin_fd, predetermined_input) contract), but
    # targeting the function directly instead of walking the menu by number.
    event = multiprocessing.Event()
    config.has_params = len(config.predetermined_input) > 0
    process = multiprocessing.Process(
        target=empireFunction,
        args=(session, event, sys.stdin.fileno(), config.predetermined_input),
        name="empireFunction",
    )
    process.start()

    # Best-effort: register the worker in the process table so it shows up in
    # the menu, just like a menu-launched task.
    try:
        process_list = updateProcessList(session)
        process_list.append({
            "pid": process.pid,
            "action": "empireFunction",
            "date": time.time(),
            "status": "started",
        })
        updateProcessList(session, programprocesslist=process_list)
    except Exception:
        pass

    # empireFunction calls event.set() immediately, so this returns as soon as
    # the worker is up.
    event.wait()

    # predetermined_input is empty now -> the menu is fully interactive over the
    # tty (docker attach). Same PID-1 menu the container has always exposed.
    try:
        menu(session, checkUpdate=False)
    finally:
        try:
            session.logout()
        except Exception:
            pass


def main():
    import ikabot.config as config
    manager = multiprocessing.Manager()
    config.predetermined_input = manager.list()
    try:
        _run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        multiprocessing.freeze_support()
    main()
