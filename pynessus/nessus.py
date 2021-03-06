"""
Copyright 2014 Quentin Kaiser

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.

You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from httplib import HTTPSConnection, CannotSendRequest, ImproperConnectionState
import os
import json
import socket
import ssl
import errno
from xml.dom.minidom import parseString
from models.scan import Scan
from models.policy import Policy
from models.plugin import Plugin, PluginFamily, PluginRule
from models.user import User
from models.folder import Folder
from models.template import Template
from models.host import Host
from models.scanner import Scanner
from models.agent import Agent
from models.agentgroup import AgentGroup
from models.mail import Mail
from models.permission import Permission
from models.proxy import Proxy
from models.group import Group
from models.vulnerability import Vulnerability


class NessusAPIError(Exception):
    pass


class Nessus(object):
    """
        A Nessus Server instance.
    """

    def __init__(self, url="", port=8834, verify=True):
        """
        Constructor.
        Params:
            url(string): nessus server's url
            port(int): nessus server's port
            verify(bool): verify server's SSL cert if True
        Returns:
        """
        self._url = url
        self._port = port
        self._verify = verify

        self._uuid = 0
        self._connection = None
        self._product = None
        self._engine = None
        self._web_ui = None
        self._misc_settings = []
        self._loaded_plugin_set = None
        self._scanner_boottime = 0
        self._idle_timeout = 0
        self._plugin_set = None
        self._plugins_lastupdated = 0
        self._plugins_expiration = 0

        self._web_server_version = None
        self._expiration = None
        self._nessus_ui_version = None
        self._ec2 = None
        self._nessus_type = None
        self._capabilities = None
        self._plugin_set = None
        self._idle_timeout = None
        self._scanner_boottime = None
        self._server_version = None
        self._feed = None

        self._mail = None
        self._proxy = None

        # managing multiple user sessions
        self._user = None

        self._agents = []
        self._agentgroups = []
        self._schedules = []
        self._policies = []
        self._templates = []
        self._scans = []
        self._tags = []
        self._folders = []
        self._users = []
        self._notifications = []
        self._scanners = []
        self._permissions = []
        self._groups = []
        self._plugin_families =[]
        self._plugin_rules = []
        self._plugins = []

        self._headers = {
            "Content-type": "application/json",
            "Accept": "application/json"
        }

    def Agent(self):
        return Agent(self)

    def AgentGroup(self):
        return AgentGroup(self)

    def Scan(self):
        return Scan(self)

    def Host(self):
        return Host(self)

    def Policy(self):
        return Policy(self)

    def Plugin(self):
        return Plugin(self)

    def PluginFamily(self):
        return PluginFamily(self)

    def PluginRule(self):
        return PluginRule(self)

    def Schedule(self):
        return Schedule(self)

    def Scanner(self):
        return Scanner(self)

    def User(self, username=None, password=None):
        return User(self, username, password)

    def Folder(self):
        return Folder(self)

    def Template(self):
        return Template(self)

    def Mail(self):
        return Mail(self)

    def Permission(self):
        return Permission(self)

    def Proxy(self):
        return Proxy(self)

    def Group(self):
        return Group(self)

    def Vulnerability(self):
        return Vulnerability(self)

    def _request(self, method, target, params, headers=None):
        """
        Send an HTTP request.
        Params:
            method(string): HTTP method (i.e. GET, POST, PUT, DELETE, HEAD)
            target(string): target path (i.e. /schedule/new)
            params(string): HTTP parameters
            headers(array): HTTP headers
        Returns:
            Response body if successful, None otherwise.
        """
        try:
            if self._connection is None:
                if not self._verify:
                    ctx = ssl._create_unverified_context()
                    self._connection = HTTPSConnection(self._url, self._port, context=ctx)
                else:
                    self._connection = HTTPSConnection(self._url, self._port)
            self._connection.request(method, target, params, self._headers if headers is None else headers)
        except CannotSendRequest:
            self._connection = HTTPSConnection(self._url, self._port)
            self.login(self._user)
            self._request(method, target, params, self._headers)
        except ImproperConnectionState:
            self._connection = HTTPSConnection(self._url, self._port)
            self.login(self._user)
            self._request(method, target, params, self._headers)
        except socket.error as serr:
            if serr.errno != errno.ECONNREFUSED:
                # Not the error we are looking for, re-raise
                raise serr
            else:
                raise Exception("Can't connect to Nessus at https://%s:%s" % (self._url, self._port))

        response = self._connection.getresponse()
        if response.status == 200:
            return response.read()
        else:
            raise Exception(response.read())

    def _api_request(self, method, target, params=None):
        """
        Send a request to the Nessus REST API.
        Params:
            method(string): HTTP method (i.e. GET, PUT, POST, DELETE, HEAD)
            target(string): target path (i.e. /schedule/new)
            params(dict): HTTP parameters
        Returns:
            dict: parsed dict from json answer, None if no content.
        """
        if not params:
            params = {}
        raw_response = self._request(method, target, json.dumps(params))
        if raw_response is not None and len(raw_response):
            response = json.loads(raw_response)
            if response is not None and "error" in response:
                raise NessusAPIError(response["error"])
            return response
        return None

    @staticmethod
    def _encode(filename):
        """
        Encode filename content into a multipart/form-data data string.
        Params:
            filename(string): filename of the file that will be encoded.
        Returns:
            string: multipart/form-data data string
        """

        boundary = '----------bundary------'
        crlf = '\r\n'
        body = []

        with open(filename, "rb") as f:
            body.extend(
                [
                    '--' + boundary,
                    'Content-Disposition: form-data; name="Filedata"; filename="%s"' % (os.path.basename(filename)),
                    'Content-Type: text/xml',
                    '',
                    f.read(),
                ]
            )
            body.extend(['--' + boundary + '--', ''])
        return 'multipart/form-data; boundary=%s' % boundary, crlf.join(body)

    def login(self, user):
        """
        Log into Nessus server with provided user profile.
        Args:
            user (User): user instance
        Returns:
            bool: True if successful login, False otherwise.
        Raises:
        """
        if self.server_version[0] != "6":
            raise Exception("This version of Nessus is not supported by pynessus. \nIf you absolutely need to use "
                            "pynessus with Nessus 5.x, please follow the instructions"
                            "available on the git repository (https://github.com/qkaiser/pynessus)")
        params = {'username': user.username, 'password': user.password}
        response = self._api_request("POST", "/session", params)
        if response is not None:
            if "status" in response:
                raise Exception(response["status"])
            self._user = user
            self._user.token = response['token']
            # Persist token value for subsequent requests
            self._headers["X-Cookie"] = 'token=%s' % (response['token'])
            return True
        else:
            return False

    def logout(self):
        """
        Log out of the Nessus server, invalidating the current token value.
        Returns:
            bool: True if successful login, False otherwise.
        """
        self._request("DELETE", "/session", [])
        return True

    @property
    def status(self):
        """
        Return the Nessus server status.
        Params:
        Returns
        """
        response = self._api_request("GET", "/server/status", "")
        if response is not None:
            return response["status"]
        else:
            return "unknown"

    def load(self):
        """
        Load Nessus.
        Returns:
            bool: True if successful login, False otherwise.
        """
        success = True
        success &= self.load_properties()
        success &= self.load_mail()
        success &= self.load_proxy()
        success &= self.load_scanners()
        success &= self.load_agents()
        success &= self.load_agentgroups()
        success &= self.load_policies()
        success &= self.load_scans()
        success &= self.load_folders()
        success &= self.load_templates()
        success &= self.load_users()
        #success &= self.load_groups()
        #success &= self.load_plugin_families()
        #success &= self.load_plugin_rules()
        return success

    def load_plugin_families(self):
        """

        :return:
        """
        response = self._api_request("GET", "/plugins/families", "")
        if response is not None and "families" in response:
            for family in response["families"]:
                p = self.PluginFamily()
                p.id = family["id"]
                p.name = family["name"]
                p.plugin_count = family["count"]
                p.load_plugins()
                self._plugin_families.append(p)
        return True

    def load_plugin_rules(self):
        """

        :return:
        """

        response = self._api_request("GET", "/plugin-rules", "")
        if "plugin_rules" in response and response["plugin_rules"] is not None:
            for p in response["plugin_rules"]:
                plugin_rule = self.PluginRule()
                plugin_rule.id = p["id"]
                plugin_rule.plugin_id = p["plugin_id"]
                plugin_rule.date = p["date"]
                plugin_rule.host = p["host"]
                plugin_rule.type = p["type"]
                plugin_rule.owner = p["owner"]
                plugin_rule.owner_id = p["owner_id"]
                self._plugin_rules.append(plugin_rule)
        return True

    def load_groups(self):
        """

        :return:
        """
        response = self._api_request("GET", "/groups")
        if "groups" in response and response["groups"] is not None:
            for g in response["groups"]:
                group = self.Group()
                group.id = g["id"]
                group.name = g["name"]
                group.user_count = g["user_count"]
                group.permissions = g["permissions"]
                self._groups.append(group)
        return True

    def load_agents(self):
        """

        :return:
        """
        for scanner in self._scanners:
            response = self._api_request("GET", "/scanners/%d/agents" % scanner.id)
            if "agents" in response and response["agents"] is not None:
                for a in response["agents"]:
                    agent = self.Agent()
                    agent.distros = a["distros"]
                    agent.id = a["id"]
                    agent.ip = a["ip"]
                    agent.last_scanned = a["last_scanned"]
                    agent.name = a["name"]
                    agent.platform = a["platform"]
                    agent.token = a["token"]
                    agent.uuid = a["uuid"]
                    agent.scanner_id = scanner.id
                    self._agents.append(agent)
        return True

    def load_agentgroups(self):
        """

        :return:
        """
        for scanner in self._scanners:
            response = self._api_request("GET", "/scanners/%d/agent-groups" % scanner.id)
            if "groups" in response and response["groups"] is not None:
                for g in response["groups"]:
                    group = self.AgentGroup()
                    group.id = g["id"]
                    group.name = g["name"]
                    group.owner_id = g["owner_id"]
                    group.owner = g["owner"]
                    group.shared = g["shared"]
                    group.user_permissions = g["user_permissions"]
                    group.creation_date = g["creation_date"]
                    group.last_modification_date = g["last_modification_date"]
                    self._agentgroups.append(group)
        return True

    def load_properties(self):
        """
        Load Nessus server properties.
        Returns:
            bool: True if successful login, False otherwise.
        """
        response = self._api_request("GET", "/server/properties?json=1", {})
        if response is not None:
            self._loaded_plugin_set = response["loaded_plugin_set"]
            self._uuid = response["server_uuid"]
            self._expiration = response["expiration"]
            self._nessus_ui_version = response["nessus_ui_version"]
            self._nessus_type = response["nessus_type"]
            self._notifications = []
            for notification in response["notifications"]:
                self._notifications.append(notification)
            self._capabilities = response["capabilities"]
            self._plugin_set = response["plugin_set"]
            self._idle_timeout = response["idle_timeout"]
            self._scanner_boottime = response["scanner_boottime"]
            self._server_version = response["server_version"]
            return True
        else:
            return False

    def load_mail(self):
        self._mail = self.Mail()
        return self._mail.load()

    def load_proxy(self):
        self._proxy = self.Proxy()
        return self._proxy.load()

    def load_templates(self):
        """
        Load Nessus server's scan templates.
        Params:
        Returns:
            bool: True if successful login, False otherwise.
        """
        response = self._api_request("GET", "/editor/scan/templates", "")
        self._templates = []
        if "templates" in response:
            for t in response["templates"]:
                template = self.Template()
                template.uuid = t["uuid"]
                template.title = t["title"]
                template.name = t["name"]
                template.description = t["desc"]
                template.more_info = t["more_info"] if "more_info" in t else None
                template.cloud_only = t["cloud_only"]
                template.subscription_only = t["subscription_only"]
                self._templates.append(template)
        return True

    def load_scanners(self):
        """

        :return:
        """
        response = self._api_request("GET", "/scanners")
        if "scanners" in response:
            for s in response["scanners"]:
                scanner = self.Scanner()
                scanner.id = s["id"]
                scanner.uuid = s["uuid"]
                scanner.name = s["name"]
                scanner.type = s["type"]
                scanner.status = s["status"]
                scanner.scan_count = s["scan_count"]
                scanner.engine_version = s["engine_version"]
                scanner.platform = s["platform"]
                scanner.loaded_plugin_set = s["loaded_plugin_set"]
                scanner.registration_code = s["registration_code"]
                scanner.owner = s["owner"]
                self._scanners.append(scanner)
        return True

    def load_scans(self, tag_id=None):
        """
        Load Nessus server's scans. Load scans from a specific tag if tag_id is provided.
        Params:
            tag_id(int, optional): Tag's identification number.
        Returns:
            bool: True if successful login, False otherwise.
        """
        response = self._api_request("GET", "/scans", "")
        self._scans = []
        if "scans" in response and response["scans"] is not None:
            for s in response["scans"]:
                scan = self.Scan()
                scan.status = s["status"]
                scan.name = s["name"]
                scan.read = s["read"]
                scan.last_modification_date = s["last_modification_date"]
                scan.creation_date = s["creation_date"]
                scan.user_permissions = s["user_permissions"]
                scan.shared = s["shared"]
                scan.id = s["id"]
                scan.template = self.Template()
                scan.template.uuid = s["uuid"]
                scan.folder = self.Folder()
                scan.folder.id = s["folder_id"]
                for user in self.users:
                    if user.id == s["owner_id"]:
                        scan.owner = user
                self._scans.append(scan)
        return True

    def load_folders(self):
        """

        Params:
        Returns:
        """
        response = self._api_request("GET", "/folders")
        if "folders" in response:
            self._folders = []
            for result in response["folders"]:
                f = self.Folder()
                f.id = result["id"]
                f.type = result["type"] if "type" in result else "local"
                f.custom = result["custom"]
                f.default_tag = result["default_tag"]
                f.name = result["name"]
                f.unread_count = result["unread_count"] if "unread_count" in result else 0
                self._folders.append(f)
            return True
        else:
            return False

    def load_policies(self):
        """
        Load Nessus server's policies.
        Params:
        Returns:
            bool: True if successful login, False otherwise.
        """
        response = self._api_request("GET", "/policies")
        if "policies" in response and response["policies"] is not None:
            self._policies = []
            for result in response['policies']:
                policy = self.Policy()
                policy.id = result["id"]
                policy.template_uuid = result["template_uuid"]
                policy.name = result["name"]
                policy.owner = result["owner"]
                policy.creation_date = result["creation_date"]
                policy.no_target = result["no_target"] if "no_target" in result else False
                policy.visibility = result["visibility"]
                policy.shared = result["shared"]
                policy.user_permissions = result["user_permissions"]
                policy.last_modification_date = result["last_modification_date"]
                policy.creation_date = result["creation_date"]
                self._policies.append(policy)
        return True

    def load_users(self):
        """
        Load Nessus server's users.
        Params:
        Returns:
            bool: True if successful login, False otherwise.
        """
        response = self._api_request("GET", "/users")
        if "users" in response:
            users = []
            for result in response["users"]:
                user = self.User()
                user.last_login = result["lastlogin"]
                user.permissions = result["permissions"]
                user.type = result["type"]
                user.name = result["name"]
                user.username = result["username"]
                user.id = result["id"]
                users.append(user)
            self._users = users
            return True
        else:
            return False

    def upload_file(self, filename):
        """
        Upload the file identified by filename to the server.
        Params:
            filename(string): file path
        Returns:
            bool: True if successful, False otherwise.
        """
        if not os.path.isfile(filename):
            raise Exception("This file does not exist.")
        else:
            content_type, body = self._encode(filename)
            headers = self._headers
            headers["Content-type"] = content_type
            response = json.loads(self._request("POST", "/file/upload", body, self._headers))
            if "fileuploaded" in response:
                return response["fileuploaded"]
            else:
                return False

    def import_policy(self, filename):
        """
        Import an existing policy uploaded using Nessus.file (.nessus format only).
        Params:
        Returns:
        """
        uploaded_file = self.upload_file(filename)
        if uploaded_file:
            response = self._api_request(
                "POST",
                "/policies/import",
                {"file": uploaded_file}
            )
            return True if response is None else False
        else:
            raise Exception("An error occured while uploading %s." % filename)

    def import_scan(self, filename, folder_id=None, password=None):
        """
        Import an existing policy uploaded using Nessus.file (.nessus format only).
        Params:
            filename(str):
            folder_id(int):
            password(str):
        Returns:
        """
        uploaded_file = self.upload_file(filename)
        if uploaded_file:
            params = {"file": uploaded_file}
            if folder_id is not None:
                params["folder_id"] = folder_id
            if password is not None:
                params["password"] = password
            response = self._api_request(
                "POST",
                "/scans/import",
                params
            )
            return True if response is None else False

    @property
    def server_version(self):
        if self._server_version is None:
            if "404 File not found" not in self._request("GET", "/nessus6.html", ""):
                self._server_version = "6.x"
            elif self._request("GET", "/html5.html", "") is not None:
                self._server_version = "5.x"
            else:
                self._server_version = "unknown"
        return self._server_version

    @property
    def agents(self):
        if self._agents is None:
            self.load_agents()
        return self._agents

    @property
    def agentgroups(self):
        if self._agentgroups is None:
            self.load_agentgrous()
        return self._agentgroups

    @property
    def scanners(self):
        if not len(self._scanners):
            self.load_scanners()
        return self._scanners

    @property
    def scans(self):
        if self._scans is None:
            self.load_scans()
        return self._scans

    @property
    def policies(self):
        if self._policies is None:
            self.load_policies()
        return self._policies

    @property
    def users(self):
        if self._users is None:
            self.load_users()
        return self._users

    @property
    def tags(self):
        if self._tags is None:
            self.load_tags()
        return self._tags

    @property
    def templates(self):
        if not len(self._templates):
            self.load_templates()
        return self._templates

    @property
    def mail(self):
        return self._mail

    @property
    def proxy(self):
        return self._proxy

    @property
    def folders(self):
        if not len(self._folders):
            self.load_folders()
        return self._folders

    @property
    def groups(self):
        return self._groups

    @property
    def user(self):
        return self._user

    @property
    def plugin_families(self):
        return self._plugin_families

    @property
    def plugin_rules(self):
        return self._plugin_rules

    @policies.setter
    def policies(self, value):
        self._policies = value

    @scans.setter
    def scans(self, value):
        self._scans = value

    @tags.setter
    def tags(self, value):
        self._tags = value

    @users.setter
    def users(self, value):
        self._users = value

    @templates.setter
    def templates(self, value):
        self._templates = value

    @scanners.setter
    def scanners(self, value):
        self._scanners = value

    @agents.setter
    def agents(self, value):
        self._agents = value

    @agentgroups.setter
    def agentgroups(self, value):
        self._agentgroups = value

    @mail.setter
    def mail(self, value):
        if isinstance(value, Mail):
            self._mail = value
        else:
            raise Exception("Not a Mail instance")

    @proxy.setter
    def proxy(self, value):
        if isinstance(value, Proxy):
            self._proxy = value
        else:
            raise Exception("Not a Proxy instance")

    @folders.setter
    def folders(self, value):
        self._folders = value

    @groups.setter
    def groups(self, value):
        self._groups = value

    @user.setter
    def user(self, value):
        if isinstance(value, User):
            self._user = value
        else:
            raise Exception("Not a User instance")
