# klippy status push to feishu
#
# Copyright (C) 2022 Albert Lee
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import logging
import requests
import socket

# Annotation imports
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
    Dict,
    List,
)
if TYPE_CHECKING:
    from confighelper import ConfigHelper
    from .klippy_apis import KlippyAPI
    DBComp = database.MoonrakerDatabase

class PushFeishu:
    def __init__(self, config: ConfigHelper) -> None:
        self.server = config.get_server()
        self.last_print_stats: Dict[str, Any] = {}

        self.botsecret = config.get('feishu_bot_secret')

        db: DBComp = self.server.load_component(config, "database")
        db_path = db.get_database_path()
        self.gc_path: str = db.get_item(
            "moonraker", "file_manager.gcode_path", "").result()
        self.print_name: str = db.get_item(
            "fluidd", "uiSettings.general.instanceName", "").result()
        if self.print_name is None:
            self.print_name = db.get_item(
                "mainsail", "uiSettings.general.instanceName", "").result()
        if self.print_name is None:
            self.print_name = self.server.get_host_info()['hostname']

        self.last_print_stats: Dict[str, Any] = {}
        self.server.register_event_handler(
            "server:klippy_started", self._handle_started)
        self.server.register_event_handler(
            "server:klippy_shutdown", self._handle_shutdown)
        self.server.register_event_handler(
            "server:status_update", self._status_update)

    async def _handle_started(self, state: str) -> None:
        if state != "ready":
            return
        kapis: KlippyAPI = self.server.lookup_component('klippy_apis')
        sub: Dict[str, Optional[List[str]]] = {"print_stats": None}
        try:
            result = await kapis.subscribe_objects(sub)
        except self.server.error as e:
            logging.info(f"Error subscribing to print_stats")
        self.last_print_stats = result.get("print_stats", {})
        if "state" in self.last_print_stats:
            state = self.last_print_stats["state"]
            logging.info(f"Job state initialized: {state}")

    async def _handle_shutdown(self, state: str) -> None:
        logging.info(f"Shutdown: {state}")

    async def _status_update(self, data: Dict[str, Any]) -> None:
        # print(data)
        if "webhooks" in data:
            webhooks = data['webhooks']
            state = webhooks['state']
            state_message = webhooks['state_message']
            logging.info(f"Status: {state}")
            logging.info(f"Info: {state_message}")
            if state == "shutdown":
                # 报错停机
                self._pushState(state=state, text=state_message)
        elif "print_stats" in data:
            print_stats = data['print_stats']

            if "state" in print_stats:
                new_ps = dict(self.last_print_stats)
                new_ps.update(print_stats)
                state = print_stats['state']
                filename = new_ps['filename']
                if state == "printing":
                    # 开始打印
                    self._pushState(state=state, filename=filename)
                elif state == "complete":
                    # 打印完成
                    self._pushState(state=state, filename=filename)
                elif state == "error":
                    # 错误
                    self._pushState(state=state, text=new_ps['message'])
                elif state == "paused":
                    # 暂停
                    self._pushState(state=state, filename=filename)
                elif state == "standby":
                    # 取消
                    self._pushState(state=state, filename=filename)
                else:
                    logging.info(f"状态：{state}")
                    print(data)
            self.last_print_stats.update(print_stats)

    def _pushState(self, state: str, text: str = None, filename: str = None):
        dic = {}

        state_title = ""
        info = ""
        digest = ""
        # 判断打印机状态
        if state == "shutdown":
            state_title = "停机"
            info = text
            if "\n" in text:
                digest = text.split("\n")[0]
            else:
                digest = text

        elif state == "printing":
            state_title = "开始打印"
            info = f"Printstart: \n{filename}"
            digest = info

        elif state == "complete":
            state_title = "打印结束"
            info = f"Printed: \n{filename} \n"
            digest = info

        elif state == "error":
            state_title = "错误"
            info = text
            digest = text

        elif state == "paused":
            # 暂停
            state_title = "打印暂停"
            info = f"Printing: \n{filename} \n"
            digest = info

        elif state == "standby":
            # 取消
            state_title = "取消打印"
            info = f"Printed: \n{filename} \n"
            digest = info

        else:
            logging.error("unknown state")
            return

        hostname = self.server.get_host_info()['hostname']

        dic = {'msg_type': "text", 'content': {
                'text': digest}}

        r = requests.post(
                "https://open.feishu.cn/open-apis/bot/v2/hook/" + self.botsecret, json=dic)
        if r.json()['StatusCode'] == 0:
            logging.info(f"Message push successfully")
            return
        else:
            self.server.add_warning(
                f"[Push_Feishu] Failed to push message. ErrCode:{r.json()['code']},ErrMsg:{r.json()['msg']}"
                "\n\nIf you want to get rid of this warning, please restart MoonRaker.")
            logging.error(
                f"Failed to push message. ErrCode:{r.json()['code']},ErrMsg:{r.json()['msg']}")
            return

def load_component(config: ConfigHelper) -> PushFeishu:
    return PushFeishu(config)