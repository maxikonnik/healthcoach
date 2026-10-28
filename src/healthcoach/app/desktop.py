# -*- coding: utf-8 -*-
"""Инструмент как приложение macOS: значок в Dock, меню, выход по Cmd+Q.

Почему не хватило запускающего скрипта. Значок в Dock — это не картинка
у процесса, а обещание системе, что процесс зарегистрируется оконным
приложением. Обычный скрипт этого не делает: система ждёт регистрации,
значок бесконечно подпрыгивает и не отвечает на щелчки, хотя сервис при
этом работает. Здесь регистрация настоящая — через `NSApplication`.

Сервис живёт в потоке того же процесса, а не отдельным: тогда «Завершить»
в Dock останавливает инструмент, а не оставляет сервер висеть без значка.
"""

from __future__ import annotations

import socket
import threading
import time
import webbrowser

from healthcoach.app.main import HOST, PORT, URL, default_app

_alive: list = []
"""Что должно пережить выход из `run()`: делегат приложения. AppKit
ссылок не держит, а сборщик мусора Python убрал бы объект вместе с
реакцией на щелчки по значку."""

_READY_TIMEOUT = 90.0
"""Сколько ждать ответа сервиса, прежде чем открывать браузер. Первый
запуск после обновления собирает окружение и читает базу знаний — минуты
хватает с запасом, а окно, открытое раньше времени, показало бы ошибку
соединения."""


def _port_is_taken() -> bool:
    """Инструмент уже поднят — из терминала или прошлым запуском.

    Второй сервис на том же порту не встанет, и вместо значка коуч
    получил бы окно с ошибкой. Правильный ответ — открыть браузер и
    ничего больше не делать.
    """
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((HOST, PORT)) == 0


def _wait_and_open() -> None:
    deadline = time.monotonic() + _READY_TIMEOUT
    while time.monotonic() < deadline:
        if _port_is_taken():
            webbrowser.open(URL)
            return
        time.sleep(0.3)


def run() -> None:
    """Точка входа: uv run python -m healthcoach.app.desktop"""
    import AppKit
    import objc
    import uvicorn

    if _port_is_taken():
        webbrowser.open(URL)
        return

    server = uvicorn.Server(
        uvicorn.Config(default_app(), host=HOST, port=PORT, log_config=None)
    )
    # Обработчики сигналов uvicorn ставит только в главном потоке, а он
    # здесь занят циклом событий AppKit; остановка идёт через should_exit.
    threading.Thread(target=server.run, daemon=True).start()

    class Delegate(AppKit.NSObject):
        def applicationDidFinishLaunching_(self, notification):
            threading.Thread(target=_wait_and_open, daemon=True).start()

        def applicationShouldHandleReopen_hasVisibleWindows_(self, app, has_windows):
            """Щелчок по значку уже запущенного приложения.

            Своих окон у инструмента нет — окно ему заменяет вкладка
            браузера, и её коуч закрывает чаще, чем само приложение.
            Поэтому щелчок открывает вкладку заново: иначе значок
            выглядел бы неотзывчивым, каким он и был до этого модуля.
            """
            webbrowser.open(URL)
            return True

        def applicationShouldTerminate_(self, app):
            server.should_exit = True
            return AppKit.NSTerminateNow

        def applicationSupportsSecureRestorableState_(self, app):
            # Иначе система пишет в лог предупреждение при каждом запуске.
            # Восстанавливать нечего — своих окон у приложения нет.
            return True

        @objc.IBAction
        def openInBrowser_(self, sender):
            webbrowser.open(URL)

    app = AppKit.NSApplication.sharedApplication()
    # Regular — обычное приложение со значком в Dock и строкой меню.
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)

    delegate = Delegate.alloc().init()
    app.setDelegate_(delegate)
    # Ссылка на делегата живёт в модуле: AppKit держит делегата слабо, а
    # приписать объекту PyObjC свой атрибут нельзя — он не словарь Python.
    _alive.append(delegate)

    _build_menu(AppKit, delegate)
    app.activateIgnoringOtherApps_(True)
    app.run()


def _build_menu(AppKit, delegate) -> None:
    """Строка меню: без неё не работает даже Cmd+Q.

    Пункты берёт на себя система только у приложений с готовым меню;
    у собранного вручную его нет, и выйти из инструмента было бы нечем.
    """
    bar = AppKit.NSMenu.alloc().init()
    app_item = AppKit.NSMenuItem.alloc().init()
    bar.addItem_(app_item)

    menu = AppKit.NSMenu.alloc().init()
    open_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Открыть в браузере", "openInBrowser:", "o"
    )
    open_item.setTarget_(delegate)
    menu.addItem_(open_item)
    menu.addItem_(AppKit.NSMenuItem.separatorItem())
    menu.addItem_(
        AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Завершить Health Coaching", "terminate:", "q"
        )
    )
    app_item.setSubmenu_(menu)
    AppKit.NSApplication.sharedApplication().setMainMenu_(bar)


if __name__ == "__main__":
    run()
