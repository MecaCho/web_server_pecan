import pecan
import json
import six
import wsme
import functools

from edgeservice.api.v1.controllers import base
from edgeservice.api.v1.types import funcmgr as funcmgr_types
from edgeservice.tools.function_client import FunctionClient
from oslo_config import cfg
from oslo_utils import excutils
from oslo_log import log as logging
from wsme import types as wtypes
from wsmeext import pecan as wsme_pecan

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def method_decorator(func):
    def wrapper(self, *args):
        print "Add wrapper.."
        return func(self, *args)

    return wrapper


def return_api_resp(*args, **kwargs):
    """Decorator that reports the execution error."""
    to_type = kwargs.get("to_type", None)
    sig = wsme.signature(*args, **kwargs)

    def catch_api_error(func):

        @six.wraps(func)
        def wrapper(self, *args, **kwargs):
            resp = None
            try:
                context = pecan.request.context.get('edgeservice_context')
                self.func_mgr.token = context.auth_token
                resp = func(self, *args, **kwargs)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    LOG.error("Failed to %s , %s: " % (func.__name__, str(e)))
            if resp:
                resp = json.loads(resp, object_hook=JsonToClass(
                        cls=to_type).unserialize_object)
            return resp

        return wrapper

    return catch_api_error


class JsonToClass(object):
    def __init__(self, cls):
        self.class_name = cls

    def unserialize_object(self, d):
        cls = self.class_name
        obj = cls.__new__(cls)
        for key, value in d.items():
            setattr(obj, key, value)
        return obj


class FunctionMgrController(base.BaseController):
    def __init__(self, project_id):
        self.project_id = project_id
        super(FunctionMgrController, self).__init__()
        self.func_mgr = FunctionClient()

    @wsme_pecan.wsexpose(funcmgr_types.FunctionMgrResponse, wtypes.text,
                         body=funcmgr_types.FunctionMgrPost,
                         status_code=200)
    @return_api_resp(to_type=funcmgr_types.FunctionMgrResponse)
    def post(self, id, function_body):

        return self.func_mgr.create_function(self.project_id, id,
                                             function_body)

    @wsme_pecan.wsexpose(funcmgr_types.FunctionMgrResponse, wtypes.text)
    @return_api_resp(to_type=funcmgr_types.FunctionMgrResponse)
    def get_one(self, id):
        """Gets a single function details."""

        return self.func_mgr.get_function(self.project_id, id)

    @wsme_pecan.wsexpose([funcmgr_types.FunctionMgrResponse])
    @return_api_resp(to_type=funcmgr_types.FunctionMgrResponse)
    def get_all(self):
        """Gets all function details."""

        return self.func_mgr.list_functions(self.project_id)

    @wsme_pecan.wsexpose(None, wtypes.text, status_code=204)
    def delete(self, id):

        LOG.debug("Delete a function: %s", id)
        self.func_mgr.delete_function(self.project_id, id)

    @pecan.expose()
    def _lookup(self, fn_id, *remainder):
        if fn_id and len(remainder) and remainder[0] == 'force':
            return FunctionMgrForceController(project_id=self.project_id), ''

        if fn_id and len(remainder) and remainder[0] == 'libraries':
            return FunctionLibraryController(project_id=self.project_id,
                                             fn_urn=fn_id), ''


class FunctionLibraryController(FunctionMgrController):
    def __init__(self, project_id, fn_urn):
        super(FunctionLibraryController, self).__init__(project_id)
        self.fn_urn = fn_urn
        self.project_id = project_id
        self.func_mgr = FunctionClient()

    @wsme_pecan.wsexpose([funcmgr_types.LibraryMgrResponse])
    @return_api_resp(to_type=funcmgr_types.LibraryMgrResponse)
    def get_all(self):
        """Gets all libraries by function details."""

        return self.func_mgr.get_library_by_function(self.project_id,
                                                     self.fn_urn)


class FunctionMgrForceController(FunctionMgrController):
    def __init__(self, project_id):
        self.project_id = project_id
        super(FunctionMgrForceController, self).__init__(project_id)
        self.func_mgr = FunctionClient()

    @wsme_pecan.wsexpose(None, wtypes.text, status_code=204)
    def delete(self, id):
        LOG.debug("Force delete a function: %s", id)
        return self.func_mgr.delete_function_force(self.project_id, id)


class FunctionMgrActionController(base.BaseController):
    def __init__(self, project_id, fn_urn, action, node_id):
        self.project_id = project_id
        super(FunctionMgrActionController, self).__init__()
        self.func_mgr = FunctionClient()
        self.fn_urn = fn_urn
        self.action = action
        self.node_id = node_id

    @wsme_pecan.wsexpose(funcmgr_types.FunctionActionResponce, status_code=200)
    @return_api_resp()
    def post(self):
        self.func_mgr.function_action(
                project_id=self.project_id,
                node_id=self.node_id,
                fn_urn=self.fn_urn,
                action=self.action)
        result = funcmgr_types.FunctionActionResponce(result="success")
        result.node_id = self.node_id
        result.action = self.action
        result.function_urn = self.fn_urn
        return result


class FunctionMgrLibraryController(base.BaseController):
    def __init__(self, project_id):
        self.project_id = project_id
        super(FunctionMgrLibraryController, self).__init__()
        self.func_mgr = FunctionClient()

    @wsme_pecan.wsexpose(wtypes.text, wtypes.text,
                         body=funcmgr_types.LibraryMgrRootPost,
                         status_code=200)
    @return_api_resp(to_type=funcmgr_types.LibraryMgrResponse)
    def post(self, lib_body):
        return self.func_mgr.create_library(self.project_id, lib_body)

    @wsme_pecan.wsexpose(funcmgr_types.LibraryMgrResponse, wtypes.text)
    @return_api_resp(to_type=funcmgr_types.LibraryMgrResponse)
    def get_one(self, id):
        """Gets a single library details."""

        return self.func_mgr.get_library(self.project_id, id)

    @wsme_pecan.wsexpose(funcmgr_types.LibraryMgrResponse, wtypes.text,
                         body=funcmgr_types.LibraryMgrRootPost,
                         status_code=200)
    @return_api_resp(to_type=funcmgr_types.LibraryMgrResponse)
    def put(self, id, body):
        """Put a single library details."""

        return self.func_mgr.update_library(self.project_id, id, body)

    @wsme_pecan.wsexpose([funcmgr_types.LibraryMgrResponse])
    @return_api_resp(to_type=funcmgr_types.LibraryMgrResponse)
    def get_all(self):
        """Gets all libraries details."""

        return self.func_mgr.list_libraries(self.project_id)

    @wsme_pecan.wsexpose(None, wtypes.text, status_code=204)
    def delete(self, id):
        LOG.debug("Delete a library: %s", id)
        return self.func_mgr.delete_library(self.project_id, id)


class FunctionMgrRuntimeController(base.BaseController):
    def __init__(self, project_id):
        self.project_id = project_id
        super(FunctionMgrRuntimeController, self).__init__()
        self.func_mgr = FunctionClient()

    def post(self, lib_body):
        pass

    @pecan.expose(funcmgr_types.RuntimeMgrResponse)
    @return_api_resp(to_type=funcmgr_types.RuntimeMgrResponse)
    def get_one(self, *args):
        """Gets a single runtime details."""
        if len(args) == 2:
            language = args[0]
            version = args[1]
            return self.func_mgr.get_runtime(self.project_id,
                                             language, version)

    def put(self, id, body):
        pass

    @wsme_pecan.wsexpose([funcmgr_types.RuntimeMgrResponse])
    @return_api_resp(to_type=funcmgr_types.RuntimeMgrResponse)
    def get_all(self):
        """Gets all libraries details."""

        return self.func_mgr.list_runtimes(self.project_id)

    def delete(self, id):
        pass


class FunctionMgrNodeRootController(base.BaseController):
    def __init__(self, project_id):
        self.project_id = project_id
        super(FunctionMgrNodeRootController, self).__init__()

    @pecan.expose()
    def _lookup(self, node_id, *remainder):
        if node_id and len(remainder) and remainder[0] == 'functions':
            if len(remainder) == 3 and remainder[2] == 'stat':
                return FunctionStatController(node_id=node_id,
                                              project_id=self.project_id,
                                              fn_urn=remainder[1]), ''
            if len(remainder) == 3 and (remainder[2] in ("start", "stop")):
                return FunctionMgrActionController(project_id=self.project_id,
                                                   node_id=node_id,
                                                   fn_urn=remainder[1],
                                                   action=remainder[2]), ''
            if len(remainder) == 2:
                return FunctionNodeController(node_id=node_id,
                                              project_id=self.project_id,
                                              fn_urn=remainder[1]), ''
            return FunctionNodeController(node_id=node_id,
                                          project_id=self.project_id), ''
        if node_id and len(remainder) and remainder[0] == 'deploy':
            return FunctionDeployController(node_id=node_id,
                                            project_id=self.project_id), ''
        if node_id and len(remainder) and remainder[0] == 'deploystatus':
            return FunctionDeployStatusController(
                    node_id=node_id,
                    project_id=self.project_id,
                    deploy_id=remainder[1]), ''


class FunctionStatController(base.BaseController):
    def __init__(self, project_id, node_id, fn_urn):
        super(FunctionStatController, self).__init__()
        self.project_id = project_id
        self.node_id = node_id
        self.func_mgr = FunctionClient()
        self.fn_urn = fn_urn

    @wsme_pecan.wsexpose(funcmgr_types.FunctionStatResponse)
    @return_api_resp(to_type=funcmgr_types.FunctionStatResponse)
    def get_all(self):
        """get functions status in node details."""

        return self.func_mgr.get_function_ins_status(
                project_id=self.project_id, node_id=self.node_id,
                fn_urn=self.fn_urn)


class FunctionNodeController(base.BaseController):
    def __init__(self, project_id, node_id, fn_urn=None):
        super(FunctionNodeController, self).__init__()
        self.project_id = project_id
        self.node_id = node_id
        self.func_mgr = FunctionClient()
        self.fn_urn = fn_urn

    @wsme_pecan.wsexpose([funcmgr_types.FunctionMgrResponse])
    @return_api_resp(to_type=funcmgr_types.FunctionMgrResponse)
    def get_all(self):
        """list functions in node details."""

        return self.func_mgr.list_fn_in_node(project_id=self.project_id,
                                             node_id=self.node_id)

    @wsme_pecan.wsexpose(funcmgr_types.FunctionActionResponce, status_code=200)
    @return_api_resp(to_type=funcmgr_types.FunctionActionResponce)
    def post(self):
        id = self.fn_urn

        self.func_mgr.assign_function_to_node(self.project_id, id,
                                              self.node_id)
        return json.dumps({"action"      : "assign function in node",
                           "node_id"     : self.node_id,
                           "function_urn": self.fn_urn, "result": "success"})

    @wsme_pecan.wsexpose(None, status_code=204)
    @return_api_resp(to_type=funcmgr_types.FunctionActionResponce)
    def delete(self):
        id = self.fn_urn

        self.func_mgr.delete_fn_from_node(self.project_id, id, self.node_id)
        return json.dumps({"action"      : "delete function in node",
                           "node_id"     : self.node_id,
                           "function_urn": self.fn_urn, "result": "success"})


class FunctionDeployController(base.BaseController):
    def __init__(self, project_id, node_id):
        super(FunctionDeployController, self).__init__()
        self.project_id = project_id
        self.node_id = node_id
        self.func_mgr = FunctionClient()

    @wsme_pecan.wsexpose(funcmgr_types.DeployStatusResponse, status_code=200)
    @return_api_resp(to_type=funcmgr_types.DeployStatusResponse)
    def post(self):
        return self.func_mgr.deploy_single_node(self.project_id,
                                                self.node_id)


class FunctionDeployStatusController(base.BaseController):
    def __init__(self, project_id, node_id, deploy_id):
        super(FunctionDeployStatusController, self).__init__()
        self.project_id = project_id
        self.node_id = node_id
        self.depoly_id = deploy_id
        self.func_mgr = FunctionClient()

    @wsme_pecan.wsexpose(funcmgr_types.DeployStatusResponse, status_code=200)
    @return_api_resp(to_type=funcmgr_types.DeployStatusResponse)
    def get_all(self):
        return self.func_mgr.get_deployment_status(
                self.project_id, self.node_id, self.depoly_id)
