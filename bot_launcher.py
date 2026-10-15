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
import os
import signal
import sys
import threading
import time

# Custom modules (empireFunction and its siblings) live here.
_FUNCTION_DIR = "/ikabot/ikabot/function"
if _FUNCTION_DIR not in sys.path:
    sys.path.insert(0, _FUNCTION_DIR)

# Set once a real shutdown (SIGTERM from `docker stop`/restart) is under way, so the
# supervisor thread stops respawning the worker while the container is going down.
_shutting_down = threading.Event()

# Respawn backoff (seconds). A one-off game-side session rotation recovers on the first
# entry; a persistent failure (e.g. the login service is down) backs off so we never hammer
# the login flow — respawning in a tight loop would be both useless and an anti-detection
# risk. The ladder resets once a worker has stayed up past _HEALTHY_UPTIME.
_RESPAWN_BACKOFFS = [15, 30, 60, 120, 300, 600]
_HEALTHY_UPTIME = 600

# Surgical overrides: (module, overrides source, fatal-if-it-fails).
# We inject our function definitions into the *live* stock module namespaces
# instead of shadowing whole files with mounted copies. Shadowing froze a stock
# file at one version, so any symbol the upstream later added to it went missing
# and broke imports (e.g. 7.6.0's splitCargoBetweenFleets). Overriding only the
# functions we tune keeps every other stock symbol live and additive upstream
# changes can no longer break us.
#   planRoutes  -> anti-detection human delays; CRITICAL, must apply (fatal).
#   loadCustomModule -> our Add/Remove menu; menu-only, off the boot path (best-effort).
_OVERRIDES = [
    ("ikabot.helpers.planRoutes", "/ikabot/planroutes_overrides.py", True),
    ("ikabot.function.loadCustomModule", "/ikabot/loadcustommodule_overrides.py", False),
]


def _apply_surgical_patches():
    """Inject our overrides into the live stock modules. Must run BEFORE importing
    command_line/empireFunction so every `from <module> import <fn>` binds ours."""
    import importlib
    import traceback
    for mod_name, src_path, fatal in _OVERRIDES:
        try:
            mod = importlib.import_module(mod_name)
            with open(src_path) as f:
                exec(compile(f.read(), src_path, "exec"), mod.__dict__)
        except Exception:
            if fatal:
                raise
            sys.stderr.write(
                "[bot_launcher] AVISO: override nao-critico falhou (%s); a continuar.\n"
                % mod_name
            )
            traceback.print_exc()


def _register_worker(session, process):
    """Best-effort: list the worker in the process table so it shows up in the menu,
    just like a menu-launched task. Never fatal."""
    try:
        from ikabot.helpers.process import updateProcessList
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


def _spawn_worker(session, config, empireFunction):
    """Fork empireFunction as a background process under the same (session, event,
    stdin_fd, predetermined_input) contract the menu uses. Returns (process, event).

    On a respawn the child is a fresh fork of PID 1, so it gets PID 1's logged-in
    session; its first game request re-validates the cookie and, if the game rotated
    the session, re-logs in from the persisted ~/.ikabot cookie — i.e. a rotation is
    now recovered in-process instead of taking the whole container down."""
    event = multiprocessing.Event()
    config.has_params = len(config.predetermined_input) > 0
    process = multiprocessing.Process(
        target=empireFunction,
        args=(session, event, sys.stdin.fileno(), config.predetermined_input),
        name="empireFunction",
    )
    process.start()
    _register_worker(session, process)
    return process, event


def _supervise(session, config, empireFunction, holder):
    """Respawn the worker whenever it dies, unless we're shutting down.

    The worker loop only ever exits abnormally (session rotation → sys.exit, or an
    unhandled error); it never returns on its own. Before this, such a death left PID 1
    alive but idle and recovery waited on the healthcheck + autoheal restarting the whole
    container (~36 min, and it dropped `docker attach`). Here we join the dead worker and
    fork a fresh one within seconds. The container healthcheck/autoheal stays as the
    backstop for the case this can't cover (PID 1 itself wedging)."""
    from empire_utils import logger
    backoff_idx = 0
    spawn_time = time.time()
    while True:
        holder[0].join()
        if _shutting_down.is_set():
            return
        uptime = time.time() - spawn_time
        if uptime > _HEALTHY_UPTIME:   # ran healthily → treat as a fresh incident
            backoff_idx = 0
        wait = _RESPAWN_BACKOFFS[min(backoff_idx, len(_RESPAWN_BACKOFFS) - 1)]
        try:
            logger.error("[supervisor] worker empireFunction terminou (code=%s, uptime=%ds) — a relançar em %ds"
                         % (holder[0].exitcode, int(uptime), wait))
        except Exception:
            pass
        if _shutting_down.wait(wait):
            return
        try:
            holder[0], _ = _spawn_worker(session, config, empireFunction)
            spawn_time = time.time()
            backoff_idx += 1
            try:
                logger.info("[supervisor] worker empireFunction relançado (pid=%s)" % holder[0].pid)
            except Exception:
                pass
        except Exception:
            # Spawn itself failed — back off further and retry; never die (that would strand
            # the empire with no worker and no supervisor).
            backoff_idx += 1


def _install_shutdown_handler():
    """On SIGTERM (docker stop/restart) mark shutdown so the supervisor stops respawning,
    then let the default disposition terminate PID 1 as usual."""
    def _handle(signum, frame):
        _shutting_down.set()
        try:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
        except Exception:
            pass
    try:
        signal.signal(signal.SIGTERM, _handle)
    except Exception:
        pass


def _run():
    import ikabot.config as config

    # Relocate the stock ikabot log (RotatingFileHandler) off container-local /tmp onto the
    # persistent ikalogs volume BEFORE helpers.logging reads the path at import time. The stock
    # log is where session rotation / re-login / request retries are recorded; on /tmp it was
    # wiped by the very autoheal restart that followed a worker death, so those outages could
    # not be root-caused from it afterwards. On the shared volume it survives the restart.
    try:
        config.LOGS_DIRECTORY_FILE = "/tmp/ikalogs/ikabot_stock.log"
    except Exception:
        pass

    # Apply our surgical patches before anything imports the stock modules.
    _apply_surgical_patches()

    from ikabot.web.session import Session
    from ikabot.command_line import menu, init
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

    # Logs in; pops the email and (on a fresh login) the password from
    # predetermined_input.
    session = Session()

    # Drain any leftover predetermined_input before handing off. We only ever
    # supply email+password for login, so nothing legitimate remains afterwards.
    # This matters because the login flow does not always pop the password: once
    # a session is cached (~/.ikabot/users/<email>.json, persists across a plain
    # docker restart), Session() reuses the cookies and leaves the password in
    # the queue. A leftover would otherwise be popped by the first menu read()
    # below and misfire a random menu action. Draining makes the menu fully
    # interactive again and keeps us immune to login-flow pop-count changes.
    while len(config.predetermined_input):
        config.predetermined_input.pop()

    # Spawn empireFunction the same way the menu would (multiprocessing.Process
    # with the (session, event, stdin_fd, predetermined_input) contract), but
    # targeting the function directly instead of walking the menu by number.
    process, event = _spawn_worker(session, config, empireFunction)

    # empireFunction calls event.set() immediately, so this returns as soon as
    # the worker is up.
    event.wait()

    # Supervise the worker from a daemon thread: if it dies (session rotation →
    # sys.exit, or an unhandled error) respawn it within seconds instead of leaving
    # the empire idle until autoheal restarts the whole container (~36 min, and it
    # dropped docker attach). `holder` lets the thread swap in each new process.
    _install_shutdown_handler()
    holder = [process]
    threading.Thread(
        target=_supervise,
        args=(session, config, empireFunction, holder),
        name="worker-supervisor",
        daemon=True,
    ).start()

    # predetermined_input is empty now -> the menu is fully interactive over the
    # tty (docker attach). Same PID-1 menu the container has always exposed.
    try:
        menu(session, checkUpdate=False)
    finally:
        _shutting_down.set()
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
