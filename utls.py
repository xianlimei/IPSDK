#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2019/8/20 下午8:25
# @Author  : yu
# @Software: PyCharm
# @license : Copyright(C),威胁猎人
import requests
import json
import os
import subprocess
import traceback
import base64
import time

import pymysql
from DBUtils.PooledDB import PooledDB


import logging
import logging.handlers
from logging import getLogger, INFO, WARN, DEBUG, ERROR, FATAL, WARNING, CRITICAL

from pymongo import MongoClient, ReplaceOne
from Crypto.Cipher import AES
from Crypto import Random

from config import G_CONFIG


__all__ = ["DownLoad", "produce", "consume"]


class ThLog(object):
    LOG_LEVEL = logging.INFO
    DATE_FORMAT = time.strftime('%Y-%m-%d', time.localtime(time.time()))

    FORMAT = '[%(asctime)s]-%(levelname)-8s<%(name)s> {%(filename)s:%(lineno)s} -> %(message)s'
    formatter = logging.Formatter(FORMAT)

    def __init__(self, module_name):
        self._normal = None
        self._error = None
        self.name = module_name

    def get_normal_log(self):
        file_name = './{0}.log'.format(self.name)
        normal_handler = logging.handlers.TimedRotatingFileHandler(filename=file_name, backupCount=30, when="D")
        normal_handler.setFormatter(self.formatter)
        normal_log = getLogger(self.name)
        normal_log.setLevel(self.LOG_LEVEL)
        normal_log.addHandler(normal_handler)
        return normal_log

    def get_error_log(self):
        file_name = './ERROR_{0}.log'.format(self.name)
        error_handler = logging.handlers.TimedRotatingFileHandler(filename=file_name, backupCount=7, when="D")
        error_handler.setFormatter(self.formatter)
        error_log = getLogger(self.name + '_error')
        error_log.setLevel(self.LOG_LEVEL)
        error_log.addHandler(error_handler)
        return error_log

    @property
    def normal_log(self):
        if not self._normal:
            self._normal = self.get_normal_log()
        return self._normal

    @property
    def error_log(self):
        if not self._error:
            self._error = self.get_error_log()
        return self._error

    def set_name(self, name):
        self.name = name

    def setLevel(self, level):
        self.normal_log.setLevel(level)

    def _backup_print(self, msg, *args, **kwargs):
        if args:
            msg = "{0}/{1}".format(msg, str(args))
        if kwargs:
            msg = "{0}/{1}".format(msg, str(kwargs))
        print(msg)

    def debug(self, msg, *args, **kwargs):
        if self.normal_log.isEnabledFor(DEBUG):
            self.normal_log._log(DEBUG, msg, args, **kwargs)
            self._backup_print(msg, args, kwargs)

    def info(self, msg, *args, **kwargs):
        if self.normal_log.isEnabledFor(INFO):
            self.normal_log._log(INFO, msg, args, **kwargs)
            self._backup_print(msg, args, kwargs)

    def warning(self, msg, *args, **kwargs):
        if self.normal_log.isEnabledFor(WARN):
            self.normal_log._log(WARNING, msg, args, **kwargs)

    def warn(self, msg, *args, **kwargs):
        if self.normal_log.isEnabledFor(WARN):
            self.normal_log._log(WARN, msg, args, **kwargs)

    def error(self, msg, *args, **kwargs):
        if self.error_log.isEnabledFor(ERROR):
            self.normal_log._log(ERROR, msg, args, **kwargs)
            self.error_log._log(ERROR, msg, args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        if self.error_log.isEnabledFor(CRITICAL):
            self.normal_log._log(CRITICAL, msg, args, **kwargs)
            self.error_log._log(CRITICAL, msg, args, **kwargs)

    def fatal(self, msg, *args, **kwargs):
        if self.error_log.isEnabledFor(FATAL):
            self.normal_log._log(FATAL, msg, args, **kwargs)
            self.error_log._log(FATAL, msg, args, **kwargs)


logger = ThLog("cli")


def status_upload(version, tag):

    url = "http://{}/call_back".format(G_CONFIG.host)

    payload = {"snuser": G_CONFIG.user["snuser"], "snkey": G_CONFIG.user["snkey"], "version": version, "tag": tag}
    headers = {
        'Content-Type': "application/json"
    }

    try:
        requests.request("POST", url, data=json.dumps(payload), headers=headers, timeout=1)
        return 0
    except:
        return 1


class DownLoad(object):
    """
    download handle
    """

    @classmethod
    def aes_encrypt_seg(cls, phoneno, snkey=G_CONFIG.user["snkey"]):
        remainder = len(phoneno) % AES.block_size
        if remainder:
            padded_value = phoneno + '\0' * (AES.block_size - remainder)
        else:
            padded_value = phoneno
        # a random 16 byte key
        iv = Random.new().read(AES.block_size)
        # CFB mode
        cipher = AES.new(bytes(snkey, encoding='utf8'), AES.MODE_CFB, iv, segment_size=128)
        # drop the padded value(phone number length is short the 16bytes)
        value = cipher.encrypt(bytes(padded_value, encoding="utf8")[:len(phoneno)])
        ciphertext = iv + value
        return str(base64.encodebytes(ciphertext).strip(), encoding="utf8")

    @classmethod
    def aes_decrypt_seg(cls, phoneno, snkey=G_CONFIG.user["snkey"]):
        data = base64.decodebytes(bytes(phoneno, encoding="utf8"))
        cihpertxt = data[AES.block_size:]
        remainder = len(cihpertxt) % AES.block_size
        if remainder:
            padded_value = cihpertxt + b'\0' * (AES.block_size - remainder)
        else:
            padded_value = cihpertxt
        cryptor = AES.new(bytes(snkey, encoding="utf8"), AES.MODE_CFB, data[0:AES.block_size], segment_size=128)
        plain_text = cryptor.decrypt(padded_value)
        return str(plain_text[0:len(cihpertxt)], encoding="utf8")

    @classmethod
    def download(cls, url, file_name):
        """
        从oss下载数据重命名后保存
        :param url: oss下载链接
        :param file_name: 文件名
        :return: bool
        """
        try:
            r = requests.get(url)
            file_path = "./download/" + file_name
            with open(file_path, "wb") as code:
                code.write(r.content)
            cmd = "gunzip {file}".format(file=file_path)
            subprocess.call(cmd, shell=True)
            status_upload(file_name.split(".")[0], "download")
            return True
        except:
            logger.error(traceback.format_exc())
            return False

    def get_upgrade_resp(self, data):
        """
        获取更新包下载链接信息
        :param data:
        :return: dict()
        """
        url = "https://{host}/api/v4/upgrade/".format(host=G_CONFIG.host)

        pstr = json.dumps(data)

        cstr = self.aes_encrypt_seg(pstr)

        payload = {
            "snuser": G_CONFIG.user["snuser"],
            "data": cstr
        }

        try:
            r = requests.post(url, data=json.dumps(payload))
            rjson = json.loads(r.text)
            if rjson["status"] == 200:
                return json.loads(self.aes_decrypt_seg(rjson["data"]))
            else:
                logger.warn("if status is 503, please check you user, snkey, and if ip in white list")
                return {}
        except:
            logger.error(traceback.format_exc())
            return {}

    def get_initial_resp(self):
        url = "https://{host}/api/v4/initial/".format(host=G_CONFIG.host)
        payload = {
            "snuser": G_CONFIG.user["snuser"]
        }
        # print("====>request body<====")
        logger.info(payload)
        try:
            r = requests.post(url, data=json.dumps(payload))
            # print("====>response body<====")
            # print(r.text)
            rjson = json.loads(r.text)
            # print(rjson)
            if rjson["status"] == 200:
                print(type(self.aes_decrypt_seg(rjson["data"])))
                logger.info(self.aes_decrypt_seg(rjson["data"]))
            else:
                logger.warn("if status is 503, please check you user, snkey, and if ip in white list")
                return {}
        except:
            logger.error(traceback.format_exc())
            return {}

    def run(self):
        """
        持续从服务端下载文件到本地
        :return:
        """
        # curver = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        curver = G_CONFIG.curver
        while True:
            result = self.get_upgrade_resp({"curver": curver, "limit": 100})
            count = result.get("count", 0)
            curver = result.get("nextver", curver)
            files = result.get("files", [])
            if count:
                for file in files:
                    n = 0
                    while n < 10:
                        if self.download(url=file["link"], file_name=file["name"]):
                            status_upload(file["name"].split(".")[0], "download")
                            break
                        else:
                            n = n + 1
                            if n == 10:
                                logger.error("尝试10次未下载成功")
                                status_upload(file["name"].split(".")[0], "download_fail")

                    # logger.info("{}:下载成功".format(file["name"]))

            time.sleep(10)


class IpToMongoDB(object):
    """
    数据设计结构:{"ip": str,  IP
                "type": ,IP类型，包括ADSL、IDC、基站、未知
                "score": data_list[2],风险分数，范围0-100，分数越高被黑产持有的概率也就越高
                "tag": data_list[3],：风险标签，包括秒拨、代理、数据中心、无
                "country": data_list[4],国家
                "province": data_list[5],省
                "city": data_list[6],市
                "owner": data_list[7],所有者
                "operator": data_list[8] 运营商
                }
    """
    _instance = None

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = IpToMongoDB()
        return cls._instance

    def __init__(self):
        self.conn = MongoClient(G_CONFIG.mongodb["uri"])
        self.conn.get_database(G_CONFIG.mongodb["db"]).get_collection(G_CONFIG.mongodb["collection"]).\
            create_index([("ip", 1)], unique=True)

    def get_conn(self):
        """
        返回collection的连接
        :return:
        """
        db_name = G_CONFIG.mongodb["db"]
        coll_name = G_CONFIG.mongodb["collection"]

        return self.conn[db_name][coll_name]

    def batch_insert(self, data_list):
        """
        批量插入信息
        :param data_list: [{"ip": str,  IP
                "type": ,IP类型，包括ADSL、IDC、基站、未知
                "score": data_list[2],风险分数，范围0-100，分数越高被黑产持有的概率也就越高
                "tag": data_list[3],：风险标签，包括秒拨、代理、数据中心、无
                "country": data_list[4],国家
                "province": data_list[5],省
                "city": data_list[6],市
                "owner": data_list[7],所有者
                "operator": data_list[8] 运营商
                }]
        :return: int(1: success, 0: failed)
        """
        if not data_list:
            return 0

        try:
            self.get_conn().insert_many(data_list, ordered=False, bypass_document_validation=True)
            return 1
        except:
            logger.error(traceback.format_exc())
            return 0

    def batch_update(self, data_list):
        """
        批量操作,存在则更新,不存在则insert
        :param data_list:
        :return:
        """
        if not data_list:
            return 0
        update_operations = list()
        try:
            for data in data_list:
                op = ReplaceOne({"ip": data["ip"]}, replacement=data, upsert=True)
                update_operations.append(op)
            self.get_conn().bulk_write(update_operations, ordered=False)
            return 1
        except:
            logger.error(traceback.format_exc())
            return 0


class IpToMysql(object):
    _instance = None

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = IpToMysql(**G_CONFIG.mysql)
        return cls._instance

    def __init__(self, host, port, user, password, db, table, charset='utf8', **kwargs):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.db = db
        self.charset = charset
        self.table = table

        self.pool = PooledDB(
            creator=pymysql, maxconnections=10, mincached=5, blocking=True, ping=0,
            host=self.host, port=self.port, user=self.user, passwd=self.password, database=self.db,
            charset=self.charset, **kwargs
        )

    def create_table(self):
        conn = self.pool.connection()
        cursor = conn.cursor()
        sql = "create table if not exists `{table}` " \
                           "(`ip` varchar(20) NOT NULL ," \
                           "`type` varchar(10) COMMENT '类型', " \
                           "`score` varchar(5) COMMENT '风险分数'," \
                           "`tag` varchar(10) COMMENT '风险标签'," \
                           "`country` varchar(30) COMMENT '国家', " \
                           "`province` varchar(30) COMMENT '省'," \
                           "`city` varchar(30) COMMENT '市'," \
                           "`owner` varchar(30) COMMENT '所有者'," \
                           "`operator` varchar(30) COMMENT '运营商'," \
                           " primary key (ip));".format(table=self.table)
        cursor.execute(sql)
        conn.commit()
        cursor.close()
        conn.close()
        return 1

    def execute_many_sql_with_commit(self, param_list):
        """
        执行更新或插入语句
        :param sql:
        :param param_list: [(), (), ...]
        :return:
        """
        if not param_list:
            return 0
        try:
            conn = self.pool.connection()
            cursor = conn.cursor()
            sql = "INSERT INTO `{table}` " \
                  "(`ip`, `type`, `score`, `tag`, `country`, `province`, `city`, `owner`, `operator`) " \
                  "VALUES(%(ip)s, %(type)s, %(score)s, %(tag)s, %(country)s, %(province)s, %(city)s, %(owner)s, %(operator)s) " \
                  "on duplicate key update score=VALUES(score), tag=VALUES(tag)"
            sql = sql.format(table=self.table)
            cursor.executemany(sql, param_list)
            conn.commit()
            cursor.close()
            conn.close()
            return 1
        except:
            logger.error(traceback.format_exc())
            return 0


def produce():

    path_to_task = "./task/"
    if not os.path.isdir(path_to_task):
        os.mkdir(path_to_task)
    path_to_watch = "./download/"
    if not os.path.isdir(path_to_watch):
        os.mkdir(path_to_watch)
    before_list = []
    while True:
        after_list = os.listdir(path_to_watch)
        if not after_list:
            time.sleep(10)
            continue
        added = [f for f in after_list if f not in before_list]
        # logger.info("本轮新增文件：{}".format(added))
        if added:
            for f in added:
                try:
                    if ".gz" in f:
                        subprocess.call("gunzip ./download/{file_old} && mv ./download/{file_new} ./task/ ".
                                        format(file_old=f, file_new=f.split('.')[0]),
                                        shell=True)
                    elif not f.isdigit():
                        continue
                    else:
                        subprocess.call("mv ./download/{file} ./task/".format(file=f), shell=True)
                except:
                    logger.error(traceback.format_exc())
                    continue
        before_list = after_list
        time.sleep(10)


def consume(database):
    def parse_data(origin_data):
        """
        解析成 json 数据入mongo
        :param origin_data: 文件里的每一行的数据
        :return:
        """
        try:
            data_list = origin_data.split("\n")[0].split("\t")
            return {"ip": data_list[0],
                    "type": data_list[1],
                    "score": data_list[2],
                    "tag": data_list[3],
                    "country": data_list[4],
                    "province": data_list[5],
                    "city": data_list[6],
                    "owner": data_list[7],
                    "operator": data_list[8],
                    }
        except:
            logger.error(traceback.format_exc())
            return {}

    def run(file):
        try:
            with open("./task/{}".format(file), "r") as fp:
                lines = fp.readlines()
                json_data_list = list(map(parse_data, lines))

                if database == "mongodb":
                    # start_time = time.time()
                    n = 0
                    while n < 5:
                        if IpToMongoDB.get_instance().batch_update(json_data_list):
                            status_upload(file, "db")
                            break
                        else:
                            n = n + 1
                            if n == 5:
                                logger.error("{}入库尝试5次未成功".format(file))
                                status_upload(file, "db_fail")

                    # logger.info("入库 耗时:{0}, 共插入数据{1}".format(time.time() - start_time, len(json_data_list)))
                if database == "mysql":
                    # start_time = time.time()
                    n = 0
                    while n < 5:
                        if IpToMysql.get_instance().execute_many_sql_with_commit(json_data_list):
                            status_upload(file, "db")
                            break
                        else:
                            n = n + 1
                            if n == 5:
                                logger.error("{}入库尝试5次未成功".format(file))
                                status_upload(file, "db_fail")

                    # logger.info("入库 耗时:{0}, 共插入数据{1}".format(time.time() - start_time, len(json_data_list)))
        except:
            logger.error("报错文件:{0}/n, {1}".format(f, traceback.format_exc()))
        finally:
            cmd = "rm -rf ./task/{}".format(file)
            subprocess.call(cmd, shell=True)
            return

    if database == "mysql":
        IpToMysql.get_instance().create_table()
    path_to_task = "./task/"
    if not os.path.isdir(path_to_task):
        os.mkdir(path_to_task)
    while True:
        files = os.listdir(path_to_task)
        files.sort()
        if files:
            for f in files:
                run(f)
        else:
            time.sleep(10)





