import json
import socket
import struct
import threading
import time
import uuid

from typing import List

from .lan_message_listener import LanMessageListener, LanMessage
from ..const.const import DEVICE_ID, _LOGGER
from ..const.message_type import message_type_cases, get_terminal_host
from ..model.device_cmd_message import DeviceCmdMessage
from ..util.command import get_receive_command, get_send_command, get_send_heart
from ..util.convert import binary_to_hex


class LanProcess:

    def __init__(self):
        self.hosts = []
        self.hosts_status: dict[str, dict] = {}
        self.hosts_ip: dict[str, dict] = {}
        self.hosts_heart: dict[str, dict] = {}
        self.hosts_lan_secret_key: dict[str, str] = {}
        self.lock = threading.Lock()
        self.lan_port = 54283
        self.broadcast_ip = "239.0.0.188"
        self.__receive = True
        self.__hear_beat = True
        self.subscribers = []

    def sync_hosts(self, entry_id: str, hosts: List[str], lan_secret_key: str):
        """
        设置主机

        参数：
        hosts: List[str]: 主机序列号集合

        返回：
        """

        # 检查并初始化外层字典键
        if entry_id not in self.hosts_status:
            self.hosts_status[entry_id] = {}
        if entry_id not in self.hosts_ip:
            self.hosts_ip[entry_id] = {}
        if entry_id not in self.hosts_heart:
            self.hosts_heart[entry_id] = {}

        wait_for_remove = []
        with self.lock:
            # 添加 hosts 中有，但 hosts_status 中没有的主机
            if len(hosts) == 0:
                self.hosts_status[entry_id] = {}
            else:
                # 比对
                # 移除
                for host in self.hosts_status[entry_id]:
                    if host not in hosts:
                        wait_for_remove.append(host)
                for host in wait_for_remove:
                    self.hosts_status[entry_id].pop(host)
                    self.hosts_ip[entry_id].pop(host)
                # 增加
                for host in hosts:
                    if host not in self.hosts_status[entry_id]:
                        self.hosts_status[entry_id][host] = False  # 设置默认状态
                        self.hosts_ip[entry_id][host] = ""
                        self.hosts_heart[entry_id][host] = 0
                        self.hosts_lan_secret_key[host] = lan_secret_key

        self._broadcast_to_offline_hosts()

    def start(self):
        # 启动接收线程
        join_group_thread = threading.Thread(target=self._join_group, args=(), daemon=True)
        join_group_thread.start()

        # 开启心跳线程
        heart_beat_thread = threading.Thread(target=self.heart_beat, args=(), daemon=True)
        heart_beat_thread.start()

    def stop(self):
        self.__receive = False
        self.__hear_beat = False

    def clear_hosts(self, entry_id: str):
        """
        清空指定集成的主机列表
        """
        with self.lock:
            if entry_id in self.hosts_status:
                self.hosts_status[entry_id] = {}
                self.hosts_ip[entry_id] = {}
                self.hosts_heart[entry_id] = {}

    def get_online_hosts(self, entry_id: str) -> List[str]:

        """
        获取在线主机的列表。
    `
        返回:
        List[str]: 在线主机的序列号列表。
        """
        online_hosts = [host for host, status in self.hosts_status[entry_id].items() if status is True]
        return online_hosts

    def check_is_online(self, host_sequence) -> bool:
        """
        获取在线主机的列表。

        返回:
        List[str]: 在线主机的序列号列表。
        """
        for entry_id in self.hosts_status:
            if host_sequence in self.hosts_status[entry_id]:
                return self.hosts_status[entry_id].get(host_sequence, False)

    def _join_group(self):
        # 创建UDP套接字
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # 绑定套接字到组播地址和端口
        udp_socket.bind(("", self.lan_port))

        # 加入组播组
        group = socket.inet_aton(self.broadcast_ip)
        mreq = struct.pack("4sL", group, socket.INADDR_ANY)
        udp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        # 接收组播数据包
        while self.__receive:
            data, addr = udp_socket.recvfrom(1024)  # 接收最多1024字节的数据
            binary_data = binary_to_hex(data)
            try:
                message = get_receive_command(binary_data, self.hosts_lan_secret_key)
                host_sequence = message.sequence
                if host_sequence == DEVICE_ID:
                    continue

                # _LOGGER.info(
                #     "接收到指令" + message.sequence + ":" + "%s == %s",
                #     addr,
                #     message.to_dict(),
                # )

                # 重置心跳计数器
                for entry_id in self.hosts_heart:
                    handle_hosts_heart = self.hosts_heart[entry_id]
                    if host_sequence in handle_hosts_heart:
                        handle_hosts_heart[host_sequence] = 0

                # 原主机的在线状态
                # 循环所有实体的列表
                for entry_id in self.hosts_status:
                    handle_hosts_status = self.hosts_status[entry_id]
                    handle_hosts_ip = self.hosts_ip[entry_id]

                    if host_sequence in handle_hosts_status:
                        old_host_online = handle_hosts_status.get(host_sequence, False)
                        # 更新ip
                        old_host_ip = handle_hosts_ip.get(host_sequence, "")
                        new_ip = addr[0]
                        if old_host_ip == "" or old_host_ip != new_ip:
                            handle_hosts_ip[host_sequence] = addr[0]
                        # 更新在线
                        if not old_host_online:
                            # 更新主机为在线
                            handle_hosts_status[host_sequence] = True
                            # 发布在线消息
                            online_message = DeviceCmdMessage(
                                str(uuid.uuid4()),
                                "1.0",
                                "terminal.host",
                                {"sequence": host_sequence, "property": {"online": True}},
                            )
                            self._publish(online_message.to_dict())
                            # 发送查询指令
                            self._send_terminal_data_up(host_sequence)

                    if not message.data_json == "":
                        # 指令处理命令
                        new_data_model = json.loads(message.data_json)
                        self.resolve_message(new_data_model)

            except ValueError as ex:
                _LOGGER.error("Invalid input. Please enter a number.", ex)

    def resolve_message(self, new_data_model):
        self._publish(new_data_model)

    def add_message_listener(self, callback):
        self.subscribers.append(callback)

    def remove_message_listener(self, callback):
        self.subscribers.remove(callback)

    def _publish(self, lan_message: dict[str, any]):
        for callback in self.subscribers:
            callback(lan_message)

    def _send_terminal_data_up(self, host_sequence: str):
        send_message = DeviceCmdMessage(
            str(uuid.uuid4()),
            "1.0",
            "sys.op",
            {"terminal_data_up": {"sequence": host_sequence}},
        )
        json_data = json.dumps(send_message.to_dict())
        lan_secret_key = self.hosts_lan_secret_key.get(host_sequence, "")
        if lan_secret_key == "":
            return
        operate_command = get_send_command(
            lan_secret_key, json_data, "NON", DEVICE_ID
        )
        command = {"host_sequence": host_sequence, "operate_command": operate_command}
        # 发送
        if not operate_command == b"":
            self._send(command["host_sequence"], command["operate_command"])

    def _send_query_info(self, host_sequence: str):
        send_message = DeviceCmdMessage(
            str(uuid.uuid4()),
            "1.0",
            "terminal.host",
            {"sequence": host_sequence, "service": {"query_info": {"params": ["use_storage_percent"]}}},
        )
        json_data = json.dumps(send_message.to_dict())
        lan_secret_key = self.hosts_lan_secret_key.get(host_sequence, "")
        if lan_secret_key == "":
            return
        operate_command = get_send_command(
            lan_secret_key, json_data, "NON", DEVICE_ID
        )
        command = {"host_sequence": host_sequence, "operate_command": operate_command}
        # 发送
        if not operate_command == b"":
            self._send(command["host_sequence"], command["operate_command"])

    def _broadcast_to_offline_hosts(self):
        for entry_id in self.hosts_status:
            handle_hosts_status = self.hosts_status[entry_id]
            offline_hosts = [host for host, status in handle_hosts_status.items() if status is False]
            if len(offline_hosts) > 0:
                # 开始进行广播,目前发送查询主机信息
                for host in offline_hosts:
                    self._send_query_info(host)

    def activate_scene(self, host_sequence, scene_no):
        data_json = {"sequence": host_sequence, "service": {
            "scene_execute": {
                "scene_no": scene_no,
            }
        }}
        message = DeviceCmdMessage(str(uuid.uuid4()), "1.0", get_terminal_host(), data_json)
        lan_secret_key = self.hosts_lan_secret_key.get(host_sequence, "")
        if lan_secret_key == "":
            return
        operate_command = get_send_command(
            lan_secret_key,
            json.dumps(message.to_dict()),
            "CON",
            DEVICE_ID,
        )
        # 发送
        # _LOGGER.debug("------发送局域网的指令%s  %s", host_sequence, message.to_dict())
        if not operate_command == b"":
            self._send(host_sequence, operate_command)

    def device_operate(self, host_sequence: str, device_type_no: str, device_no: str,
                       terminal_sequence: str, route_num: int, is_group: bool, is_virtual_device: bool, commands):
        parts = device_type_no.split('-')
        if len(parts) == 0:
            return
        device_class_no = parts[0]
        sequence = terminal_sequence
        route = route_num

        if is_group:
            data_json = {"sequence": host_sequence}
            message_type = get_terminal_host()
            data_json["service"] = {
                "device_group_cmd_down": {
                    "group_no": device_no,
                    "property": commands,
                    "service": {},
                }
            }
        else:
            data_json = {"sequence": sequence}
            message_type = message_type_cases.get(device_class_no, lambda: "")()
            if message_type == "":
                _LOGGER.error("message_type is empty ,device_no is %s", device_no)
                return

            if route != 0:
                data_json["route"] = route
            else:
                if is_virtual_device:
                    data_json.sequence = device_no
                    data_json["route"] = 1
                else:
                    return

            data_json["property"] = commands

        message = DeviceCmdMessage(str(uuid.uuid4()), "1.0", message_type, data_json)
        lan_secret_key = self.hosts_lan_secret_key.get(host_sequence, "")
        if lan_secret_key == "":
            return
        operate_command = get_send_command(
            lan_secret_key,
            json.dumps(message.to_dict()),
            "CON",
            DEVICE_ID,
        )
        # 发送
        # _LOGGER.debug("------发送局域网的指令%s  %s", host_sequence, message)
        if not operate_command == b"":
            self._send(host_sequence, operate_command)

    def cancel(self):
        self.__receive = False
        self.__hear_beat = False

    def heart_beat(self):
        """心跳包"""
        while self.__hear_beat:
            for entry_id in self.hosts_status:
                handle_hosts_status = self.hosts_status[entry_id]
                offline_hosts = [host for host, status in handle_hosts_status.items() if status is not True]
                online_hosts = [host for host, status in handle_hosts_status.items() if status is True]

                # 离线主机
                for host_sequence in offline_hosts:
                    # 发送心跳包
                    operate_command = get_send_heart("CON", DEVICE_ID)
                    if not operate_command == b"":
                        # 发送
                        self._send(host_sequence, operate_command)

                # 在线主机
                for host_sequence in online_hosts:
                    handle_hosts_heart = self.hosts_heart[entry_id]
                    if host_sequence in handle_hosts_heart:
                        if handle_hosts_heart[host_sequence] >= 3:
                            handle_hosts_heart[host_sequence] = 0
                            # 处理离线
                            # 状态
                            handle_hosts_status = self.hosts_status[entry_id]
                            if host_sequence in handle_hosts_status:
                                handle_hosts_status[host_sequence] = False
                            # ip
                            handle_hosts_ip = self.hosts_ip[entry_id]
                            if host_sequence in handle_hosts_ip:
                                handle_hosts_ip[host_sequence] = ""
                            # 发送离线消息
                            online_message = DeviceCmdMessage(
                                str(uuid.uuid4()),
                                "1.0",
                                "terminal.host",
                                {"sequence": host_sequence, "property": {"online": False}}
                            )
                            self._publish(online_message.to_dict())
                        else:
                            # 发送心跳包
                            operate_command = get_send_heart("CON", DEVICE_ID)
                            if not operate_command == b"":
                                # 发送
                                self._send(host_sequence, operate_command)
                                handle_hosts_heart[host_sequence] += 1

            # 发送发现主机广播包
            self._broadcast_to_offline_hosts()

            time.sleep(30)

    def _send(self, host_sequence, message):
        """
        发送消息
        :param host_sequence: 主机序列号
        :param message: 消息
        :return:
        """
        broadcast_address = ""
        for entry_id in self.hosts_ip:
            if host_sequence in self.hosts_ip[entry_id]:
                handle_hosts_ip = self.hosts_ip[entry_id]
                broadcast_address = handle_hosts_ip.get(host_sequence, "")

        if broadcast_address == "":
            if not self.check_is_online(host_sequence):
                broadcast_address = self.broadcast_ip
        if broadcast_address == "":
            _LOGGER.error(f"------发送局域网的指令，ip 为空，host_sequence: {host_sequence} ")

        if broadcast_address == "":
            return 19997, "找不到主机！"

        try:
            # 创建UDP套接字
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp_socket.sendto(message, (broadcast_address, self.lan_port))
        finally:
            if udp_socket:
                udp_socket.close()
