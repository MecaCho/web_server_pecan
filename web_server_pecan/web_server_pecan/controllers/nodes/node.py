import base64
from random import choice
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils

import pecan
from wsme import types as wtypes
from wsmeext import pecan as wsme_pecan
from edgeservice.api.v1.controllers import base
from edgeservice.api.v1.controllers import device_node
from edgeservice.api.v1.types import node as node_types
from edgeservice.common import data_models
from edgeservice.common import constants
from edgeservice.common import exceptions
from edgeservice.common import utils
from edgeservice.db import api as db_api
from edgeservice.db import models
from edgeservice.db import prepare as db_prepare
from edgeservice.modules.manager import ModuleManager
from edgeservice.iamclient.iam_client import IAMClient
from edgeservice.tools.cert_gen.certs_helper import CertificateHelper
from edgeservice.tools.placement_client import PlacementHelper
from oslo_db import exception as db_exc
from oslo_config import cfg

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class ActionController(base.BaseController):
    RBAC_TYPE = constants.RBAC_NODE

    def __init__(self, node_id, project_id):
        super(ActionController, self).__init__()
        self.node_id = node_id
        self.project_id = project_id
        self.placement = PlacementHelper()

    @wsme_pecan.wsexpose(wtypes.text, wtypes.text, status_code=200,
                         body=node_types.ActionNodeRootPUT)
    def post(self, node_obj):
        context = pecan.request.context.get('edgeservice_context')
        edge_node_in_db = self._get_db_edge_node(context.session, self.node_id)
        action = node_obj.node.action
        self._auth_check_action(context, edge_node_in_db.project_id,
                                constants.RBAC_PUT)
        if action not in constants.EDGE_DEVICE_ACTION:
            raise exceptions.NodeActionNotSupported()
        state = None
        if action == constants.EDGE_DEVICE_ACTION_START:
            if edge_node_in_db.state != constants.EDGE_DEVICE_STATE_STOPPED:
                raise exceptions.NodeStartConflict()
            state = constants.EDGE_DEVICE_STATE_RUNNING
        if action == constants.EDGE_DEVICE_ACTION_STOP:
            if edge_node_in_db.state != constants.EDGE_DEVICE_STATE_RUNNING:
                raise exceptions.NodeStopConflict()
            state = constants.EDGE_DEVICE_STATE_STOPPED
        lock_session = db_api.get_session(autocommit=False)
        try:
            self.repositories.edge_node.update(
                lock_session, edge_node_in_db.id, **{'state': state})
            message = {'action': action}
            obj_name = None
            prepared_msg = self.events.node_event.prepare_publish(
                self.project_id, edge_node_in_db.id, obj_name,
                constants.OPERATION_UPDATED, message)
            self.publish_mgr.publish(prepared_msg)

            # update edge node to placement
            self.placement.update_router(self.project_id,
                                         edge_node_in_db.id, state)
            lock_session.commit()
        except Exception as e:
            with excutils.save_and_reraise_exception():
                msg = ("Failed to update edge node state %(id)s, due to: "
                       "%(except)s.", {'id': self.node_id, 'except': str(e)})
                LOG.error(msg)
                lock_session.rollback()
        ret = {'node': {'action': action}}
        return ret


class NodesController(base.BaseController):
    RBAC_TYPE = constants.RBAC_NODE

    def __init__(self, project_id):
        super(NodesController, self).__init__()
        self.project_id = project_id
        self.manager = ModuleManager()
        self.iam_client = IAMClient()
        self.placement = PlacementHelper()

    def _update_config_map(self, session, edge_node_in_db, lc_dbs):
        edge_device_db = self.repositories.edge_node.get(
            session, id=edge_node_in_db.id)

        if edge_device_db and edge_device_db.master_addr:
            log_cfg_dict = dict()
            for lc_db in lc_dbs:
                if lc_db.type == constants.LOG_TYPE_LOCAL:
                    if lc_db.component == constants.LOG_COMPONENT_APP:
                        log_cfg_dict['app_log_file_size'] = '%sM' % str(
                            lc_db.size)
                        log_cfg_dict['app_log_rotate_num'] = str(
                            lc_db.rotate_num)
                        log_cfg_dict[
                            'app_log_rotate_period'] = lc_db.rotate_period
                    if lc_db.component == constants.LOG_COMPONENT_SYSTEM:
                        log_cfg_dict['system_log_file_size'] = '%sM' % str(
                            lc_db.size)
                        log_cfg_dict['system_log_rotate_num'] = str(
                            lc_db.rotate_num)
                        log_cfg_dict[
                            'system_log_rotate_period'] = lc_db.rotate_period
                if lc_db.type == constants.LOG_TYPE_LTS:
                    if lc_db.component == constants.LOG_COMPONENT_APP:
                        log_cfg_dict['app_log_level'] = lc_db.level
                    if lc_db.component == constants.LOG_COMPONENT_SYSTEM:
                        log_cfg_dict['system_log_level'] = lc_db.level
            # update logger container config map
            self.manager.update_module(['config_map'], edge_device_db,
                                       update_body=log_cfg_dict)
        return edge_device_db

    @wsme_pecan.wsexpose(node_types.EdgeNodeRootResponse, wtypes.text)
    def get_one(self, id):
        """Gets a single edge node details."""
        context = pecan.request.context.get('edgeservice_context')

        self._auth_check_action(context, self.project_id,
                                constants.RBAC_GET_ONE)

        edge_node = self._get_db_edge_node(context.session, id)
        deployment_num = self._get_instance_num_by_edge_device(
            context.session, edge_node.id)
        edge_node.deployment_num = deployment_num
        self.get_edge_device_status(edge_node)
        log_config_dbs, _ = self.repositories.log_config.get_all(
            context.session, edge_node_id=id)
        edge_node.log_configs = log_config_dbs
        edge_node.device_num = self.repositories.group_device_binding.count(
            context.session, edge_node_id=id)
        result = self._convert_db_to_type(
            edge_node, node_types.EdgeNodeResponse)
        return node_types.EdgeNodeRootResponse(node=result)

    @wsme_pecan.wsexpose(node_types.EdgeNodesRootResponse, wtypes.text,
                         wtypes.text, ignore_extra_args=True)
    def get_all(self):
        """Lists all edge groups."""
        pcontext = pecan.request.context
        context = pcontext.get('edgeservice_context')
        project_id = context.project_id or self.project_id

        query_filter = self._auth_get_all(context, project_id)
        ph = pcontext.get(constants.PAGINATION_HELPER)
        app_name = ph.params.get('app_name')
        tags = ph.params.get('tags')
        device_id = ph.params.get('device_id')
        device_name = ph.params.get('device_name')
        tags_dict = None
        if tags:
            tags_dict = utils.parse_tags(tags)
        filter_with = dict()
        query_filter['show_deleted'] = False
        relation = None
        comment = None
        if tags_dict:
            edge_nodes, count = self.repositories.edge_node.get_all_by_tags(
                context.session,
                pagination_helper=pcontext.get(constants.PAGINATION_HELPER),
                tags=tags_dict,
                **query_filter)
        elif device_id or device_name:
            if device_name:
                device_db = self.repositories.device.get(
                    context.session, project_id=self.project_id,
                    name=device_name)
                if device_db:
                    device_id = device_db.id
                else:
                    device_id = None
            filter_with['joined_model'] = models.DeviceGroupBinding
            filter_with['joined_model_key'] = 'edge_node_id'
            filter_with['filter_by_key'] = 'device_id'
            filter_with['filter_by_value'] = device_id
            edge_nodes, count = self.repositories.edge_node.get_all(
                context.session,
                pagination_helper=pcontext.get(constants.PAGINATION_HELPER),
                filter_with=filter_with,
                **query_filter)
            for edge_node in edge_nodes:
                dev_node_bound_db = self.repositories.group_device_binding.get(
                    context.session, device_id=device_id,
                    edge_node_id=edge_node.id)
                if dev_node_bound_db:
                    relation = dev_node_bound_db.relation
                    comment = dev_node_bound_db.comment
        elif app_name:
            filter_with['joined_model'] = models.Instance
            filter_with['joined_model_key'] = 'edge_node_id'
            filter_with['filter_by_key'] = 'name'
            filter_with['filter_by_value'] = app_name
            edge_nodes, count = self.repositories.edge_node.get_all(
                context.session,
                pagination_helper=pcontext.get(constants.PAGINATION_HELPER),
                filter_with=filter_with,
                **query_filter)
        else:
            edge_nodes, count = self.repositories.edge_node.get_all(
                context.session,
                pagination_helper=pcontext.get(constants.PAGINATION_HELPER),
                filter_with=None,
                **query_filter)
        node_models = []
        if edge_nodes:
            for node in edge_nodes:
                deployment_num = self._get_instance_num_by_edge_device(
                    context.session, node.id)
                node.deployment_num = deployment_num
                self.get_edge_device_status(node)
                node.device_num = \
                    self.repositories.group_device_binding.count(
                        context.session, edge_node_id=node.id)
                node_models.append(node)
        result = self._convert_db_to_type(node_models,
                                          [node_types.EdgeNodeResponse])
        for ret in result:
            ret.relation = relation
        for ret in result:
            ret.comment = comment
        return node_types.EdgeNodesRootResponse(nodes=result, count=count)

    def create_ak_sk(self, context, session, iam_role):
        domain_id = context.user_domain_id
        self.iam_client.get_ak_sk_from_iam(
            domain_id=domain_id, project_id=self.project_id,
            iam_role=iam_role)
        aksk_refresh_dict = {'project_id': self.project_id,
                             'domain_id': domain_id,
                             'iam_role': iam_role}
        LOG.debug('Create new ak sk refresh for %s.' % iam_role)
        try:
            aksk = self.repositories.aksk_refresh.create(
                session,
                **aksk_refresh_dict)
            return aksk
        except db_exc.DBDuplicateEntry as exc:
            LOG.debug("DBDuplicateEntry create_ak_sk %s :" % str(exc))
            msg = ('Iam role %(name)s in project %(project_id)s has '
                   'existed.' % {'name': iam_role,
                                 'project_id': self.project_id})
            LOG.debug(msg)
            aksk = self.repositories.aksk_refresh.get(
                session,
                project_id=self.project_id,
                iam_role=iam_role)
            return aksk

    def _add_device_to_node(self, lock_session, edge_node_id, node_obj):
        all_devices = []
        relation = node_obj.get('relation')
        comment = node_obj.get('comment')
        utils.check_relation_validate_input(relation)
        utils.check_comment_validate_input(comment)
        for device_id in node_obj.get('device_ids'):
            device_db = self._get_db_device(lock_session, device_id)
            device_dict = device_db.to_dict()
            device_attr_filter_with = dict()
            device_attr_filter_with['device_id'] = edge_node_id
            device_attr, attr_count = self.repositories.device_attributes. \
                get_all(
                    lock_session,
                    pagination_helper=None,
                    **device_attr_filter_with)

            device_twin_filter_with = dict()
            device_twin_filter_with['device_id'] = edge_node_id
            # device_twin_filter_with['show_twin_deleted'] = True
            device_twin, twin_count = self.repositories.device_twin.get_all(
                lock_session,
                pagination_helper=None,
                **device_twin_filter_with
            )
            device_dict = device_db.to_dict()
            result_attrs = dict()
            if len(device_attr) > 0:
                for attr in device_attr:
                    name, msg_attr = utils.attr_to_msg_attr(attr)
                    result_attrs[name] = msg_attr
                device_dict['attributes'] = result_attrs
            result_twins = dict()
            if len(device_twin) > 0:
                for twin in device_twin:
                    name, msg_twin = utils.twin_to_msg_twin(twin)
                    result_twins[name] = msg_twin
                device_dict['twin'] = result_twins
            device_dict.pop('created_at')
            device_dict.pop('updated_at')
            device_dict.pop('id_inc')
            all_devices.append(device_dict)

        for device_id in node_obj.get('device_ids'):
            binding = {'device_id': device_id}
            count = self.repositories.group_device_binding.count(
                lock_session, **binding)
            if count > 0:
                raise exceptions.DeviceGroupHasBound(device_id=device_id)

            binding = {'edge_node_id': edge_node_id, 'device_id': device_id,
                       'relation': relation,
                       'comment': comment}
            self.repositories.group_device_binding.create_bare(
                lock_session, **binding)
        return all_devices

    @wsme_pecan.wsexpose(node_types.EdgeNodeRootResponse,
                         body=node_types.NodeRootPOST,
                         status_code=201)
    def post(self, edge_node):
        """Creates a edge node.
        add label to node:
        get node info throuth label:
        """
        context = pecan.request.context.get('edgeservice_context')
        node = edge_node.node

        if not self.project_id and context.project_id:
            self.project_id = context.project_id
        if not self.project_id:
            raise exceptions.MissingProjectID()

        self._auth_check_action(context, self.project_id,
                                constants.RBAC_POST)

        post_edge_node_dict = db_prepare.check_edge_node_parms(
            node.to_dict(render_unsets=False))
        log_config_dict = []
        if node.log_configs:
            log_config_dict = db_prepare.validate_log_config(
                node.log_configs)

        iam_role = post_edge_node_dict.get('iam_role')
        node_model = data_models.EdgeNode()
        added_devices = []
        edge_node_dict_pre_db = dict()
        edge_node_dict_pre_db['project_id'] = self.project_id
        lock_session = db_api.get_session(autocommit=False)
        edge_node_in_db = None
        try:
            # create ak sk refresh if not exist
            if iam_role:
                aksk = self.repositories.aksk_refresh.get(
                    lock_session,
                    project_id=self.project_id,
                    iam_role=iam_role)
                if not aksk:
                    aksk = self.create_ak_sk(context,
                                             lock_session,
                                             iam_role)
                edge_node_dict_pre_db['iam_role_id'] = aksk.id
            edge_node_dict_pre_db['name'] = post_edge_node_dict.get('name')
            edge_node_dict_pre_db['description'] = post_edge_node_dict. \
                get('description')
            edge_node_dict_pre_db['iam_role'] = post_edge_node_dict. \
                get('iam_role')
            edge_node_dict_pre_db['name'] = node.name
            edge_node_dict_pre_db['enable_gpu'] = node.enable_gpu
            edge_node_dict_pre_db['state'] = constants. \
                EDGE_DEVICE_STATE_UNCONNECTED
            edge_node_dict_pre_db['deployment_num'] = 0
            edge_node_dict_pre_db["master_addr"] = \
                self.select_master_for_node()
            _device_infos = post_edge_node_dict.get('device_infos', [])
            edge_node_dict_pre_db['device_num'] = len(_device_infos)

            edge_node_in_db = self.repositories.edge_node.create(
                lock_session, **edge_node_dict_pre_db)
            # first write the all default, then write user config
            for comp in (constants.LOG_COMPONENT_APP,
                         constants.LOG_COMPONENT_SYSTEM,):  # noqa
                log = {'project_id': self.project_id,
                       'edge_node_id': edge_node_in_db.id,
                       'component': comp, 'type': constants.LOG_TYPE_LOCAL,
                       'size': CONF.edge_core.default_rotate_size,
                       'rotate_num': CONF.edge_core.default_rotate_num,
                       'rotate_period': CONF.edge_core.default_rotate_period}
                self.repositories.log_config.create(lock_session, **log)

                log = {'project_id': self.project_id,
                       'edge_node_id': edge_node_in_db.id,
                       'component': comp, 'type': constants.LOG_TYPE_LTS,
                       'level': CONF.edge_core.default_level}
                self.repositories.log_config.create(lock_session, **log)
            for lc in log_config_dict:
                lc['project_id'] = self.project_id
                lc['edge_node_id'] = edge_node_in_db.id
                self.repositories.log_config.get_config_wait_update(
                    lock_session, self.project_id, lc)

            added_devices = []
            for device_info in _device_infos:
                added_device = self._add_device_to_node(
                    lock_session, edge_node_in_db.id, device_info)
                added_devices.extend(added_device)

            edge_node_in_db.pause_docker_image = \
                CONF.edge_core.pause_docker_image
            edge_node_in_db.master_url = CONF.edge_core.master_url
            cert_help = CertificateHelper(edge_node_in_db.project_id,
                                          edge_node_in_db.id,
                                          context.auth_token,
                                          domain_id=context.user_domain_id,
                                          node_db=edge_node_in_db)
            ca, cert, private_key, package = cert_help.cert_helper()
            log_config_dbs, _ = self.repositories.log_config.get_all(
                lock_session, edge_node_id=edge_node_in_db.id)
            node_model.ca = ca
            node_model.certificate = cert
            node_model.private_key = private_key
            node_model.package = package
            node_model.log_configs = log_config_dbs
            node_model.enable_gpu = node.enable_gpu
            node_model.pause_docker_image = CONF.edge_core.pause_docker_image
            node_model.master_url = CONF.edge_core.master_url
            node_model.name = edge_node_in_db.name
            node_model.description = edge_node_in_db.description
            node_model.id = edge_node_in_db.id
            node_model.project_id = edge_node_in_db.project_id
            node_model.created_at = edge_node_in_db.created_at
            node_model.updated_at = edge_node_in_db.updated_at
            node_model.enable_gpu = edge_node_in_db.enable_gpu
            if _device_infos:
                node_model.device_infos = _device_infos
            node_model.state = edge_node_in_db.state
            lock_session.commit()
        except db_exc.DBDuplicateEntry as exc:
            LOG.debug("DBDuplicateEntry create_node %s :" % str(exc))
            msg = ('Edge node %(name)s in project %(project_id)s has '
                   'existed.' % {'name': edge_node_dict_pre_db['name'],
                                 'project_id': self.project_id})
            raise exceptions.ResourceNameExisted(detail=msg)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.warn("Failed to create edge node %s."
                         % post_edge_node_dict)
                lock_session.rollback()
        prepared_msg = self.events.node_event.prepare_publish(
            self.project_id, edge_node_in_db.id, edge_node_in_db.name,
            constants.OPERATION_CREATED, post_edge_node_dict)
        self.publish_mgr.publish(prepared_msg)
        if added_devices:
            message = {'added_devices': added_devices}
            prepared_msg = self.events.group_membership_event.prepare_publish(
                self.project_id, edge_node_in_db.id, edge_node_in_db.name,
                constants.OPERATION_UPDATED, message)
            self.publish_mgr.publish(prepared_msg)

        result = self._convert_db_to_type(
            node_model, node_types.EdgeNodeResponse)
        return node_types.EdgeNodeRootResponse(node=result)

    def select_master_for_node(self):
        try:
            base_keys = CONF.edge_core.edge_clusters.keys()
            ret = base64.b64decode(choice(base_keys))
            return ret
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error("Select master_addr for node failed : %s", str(e))

    def _has_new_iam_role(self, group_obj):
        new_iam_role = group_obj.iam_role
        if new_iam_role is None:
            return False
        if new_iam_role == '' or new_iam_role:
            return True

    @wsme_pecan.wsexpose(node_types.EdgeNodeRootResponse,
                         wtypes.text, status_code=200,
                         body=node_types.NodeRootPUT)
    def put(self, id, node_obj):
        """Updates an edge group."""
        context = pecan.request.context.get('edgeservice_context')
        node = node_obj.node
        if not self.project_id and context.project_id:
            self.project_id = context.project_id
        if not self.project_id:
            raise exceptions.MissingProjectID()

        self._auth_check_action(context, self.project_id,
                                constants.RBAC_PUT)
        edge_group_dict = {}
        edge_node_in_db = None
        lc_dbs = None
        node_dict = node.to_dict(render_unsets=False)
        description = node_dict.get('description')
        if description is not None:
            utils.validate_desc(description)
            edge_group_dict['description'] = description
        log_config_dict = []
        if node.log_configs:
            log_config_dict = db_prepare.validate_log_config(
                node.log_configs)
        lock_session = db_api.get_session(autocommit=False)
        try:
            edge_node_in_db = self._get_db_edge_node(lock_session, id)
            new_iam_role = node.iam_role
            old_iam_role = edge_node_in_db.iam_role
            aksk = None
            clear_iam_role = False
            is_has_new_iam_role = self._has_new_iam_role(node)
            # delete iam role from edge group
            if is_has_new_iam_role and old_iam_role and not new_iam_role:
                # clear the secret ak/sk
                clear_iam_role = True
            # replace a new iam role without same name
            if old_iam_role and new_iam_role and old_iam_role != new_iam_role:
                aksk = self.repositories.aksk_refresh.get(
                    lock_session,
                    project_id=self.project_id,
                    iam_role=new_iam_role)
                if not aksk:
                    # get ak sk from iam, and save to aksk refresh
                    aksk = self.create_ak_sk(context,
                                             lock_session,
                                             new_iam_role)

            # replace a new iam role with same name, pass
            # new add iam role
            if not old_iam_role and new_iam_role:
                aksk = self.repositories.aksk_refresh.get(
                    lock_session,
                    project_id=self.project_id,
                    iam_role=new_iam_role)
                if not aksk:
                    # get ak sk from iam, and save to aksk refresh
                    aksk = self.create_ak_sk(context,
                                             lock_session,
                                             new_iam_role)

            if aksk:
                edge_group_dict['iam_role_id'] = aksk.id
            if clear_iam_role:
                edge_group_dict['iam_role_id'] = None
            if is_has_new_iam_role:
                edge_group_dict['iam_role'] = new_iam_role
            self.repositories.edge_node.update(lock_session,
                                               edge_node_in_db.id,
                                               **edge_group_dict)

            if is_has_new_iam_role and old_iam_role \
                    and old_iam_role != new_iam_role:
                self.repositories.aksk_refresh.delete_if_not_used(
                    lock_session,
                    project_id=self.project_id,
                    iam_role=old_iam_role)
            # update log config
            for lc in log_config_dict:
                lc['project_id'] = self.project_id
                lc['edge_node_id'] = edge_node_in_db.id
                self.repositories.log_config.get_config_wait_update(
                    lock_session, self.project_id, lc)
            lc_dbs, _ = self.repositories.log_config.get_all(
                lock_session, edge_node_id=edge_node_in_db.id)
            if log_config_dict and (edge_node_in_db.state != constants.EDGE_DEVICE_STATE_UNCONNECTED):   # noqa
                self._update_config_map(lock_session, edge_node_in_db, lc_dbs)
            lock_session.commit()
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.warn("Failed to update edge node %s." % id)
                lock_session.rollback()
        try:
            prepared_msg = self.events.node_event.prepare_publish(
                self.project_id,
                edge_node_in_db.id, edge_node_in_db.name,
                constants.OPERATION_UPDATED,
                edge_group_dict,
                parent_msg_topic=self.events.node_event.ROUTING_KEY)
            self.publish_mgr.publish(prepared_msg)
        except Exception:
            with excutils.save_and_reraise_exception():
                rb_dict = {}
                for k, v in edge_group_dict.items():
                    rb_dict[k] = edge_node_in_db.k
                self.repositories.edge_node.update(context.session,
                                                    edge_node_in_db.id,
                                                    **rb_dict)
        edge_node_db = self._get_db_edge_node(context.session, id)
        edge_node_db.log_configs = lc_dbs
        result = self._convert_db_to_type(
            edge_node_db, node_types.EdgeNodeResponse)
        return node_types.EdgeNodeRootResponse(node=result)

    def _delete(self, id, cascade=False):
        """Deletes a edge group."""
        context = pecan.request.context.get('edgeservice_context')
        # edge_node = self._get_db_edge_group(context.session, id)
        edge_device_db = self._get_db_edge_node(
            context.session, id)
        self._auth_check_action(context, edge_device_db.project_id,
                                constants.RBAC_DELETE)
        lock_session = db_api.get_session(autocommit=False)
        try:
            filters = {'edge_node_id': id}
            instance = self.repositories.instance.get(
                lock_session, **filters)
            if instance:
                raise exceptions.InstanceExisted()

            count = self.repositories.group_device_binding.count(
                lock_session, edge_node_id=id)
            if count > 0:
                raise exceptions.DeviceInGroup()

            if edge_device_db.state != constants.EDGE_DEVICE_STATE_UNCONNECTED:
                modules = ['config_map']
                modules.extend(CONF.edge_core.system_modules)
                if edge_device_db.enable_gpu:
                    modules.extend(['gpu_plugin'])
                self.manager.delete_module(modules, edge_device_db)
                self.manager.delete_node(edge_device_db)

            _filters = {'edge_node_id': id}
            self.repositories.log_config.delete_all(lock_session, **_filters)
            self.repositories.edge_node.delete(
                lock_session, id=id)

            if edge_device_db.iam_role:
                self.repositories.aksk_refresh.delete_if_not_used(
                    lock_session,
                    project_id=self.project_id,
                    iam_role=edge_device_db.iam_role)

            # We need clean this group's tag when delete group
            self._delete_resource_tag(
                lock_session, id, constants.RESOURCE_TYPE_EDGENODE)

            # delete edge node in placement
            self.placement.delete_router(self.project_id, id)
            lock_session.commit()
        except Exception:
            with excutils.save_and_reraise_exception():
                msg = ('Delete node: %s failure.' % id)
                LOG.error(msg)
                lock_session.rollback()
        try:
            prepared_msg = self.events.node_event.prepare_publish(
                self.project_id, edge_device_db.id,
                edge_device_db.name, constants.OPERATION_DELETED)
            self.publish_mgr.publish(prepared_msg)
            if CONF.psm.cert_revoke:
                cert_helper = CertificateHelper(edge_device_db.project_id,
                                                context.auth_token,
                                                edge_device_db.id,
                                                domain_id=context.
                                                user_domain_id)
                cert_helper.revoke_cert()
        except Exception as exc:
            msg = ('Delete node: %s failure, reasion: %s.' % (id, exc))
            LOG.error(msg)

    @wsme_pecan.wsexpose(None, wtypes.text, wtypes.text, status_code=204)
    def delete(self, id, cascade=False):
        """Deletes a edge group."""

        LOG.debug("Delete a group: %s", id)
        cascade = strutils.bool_from_string(cascade)
        return self._delete(id, cascade)

    @pecan.expose()
    def _lookup(self, node_id, *remainder):
        if node_id and len(remainder) and remainder[0] == 'action':
            return ActionController(node_id=node_id,
                                    project_id=self.project_id), ''

        if node_id and len(remainder) and remainder[0] == 'devices':
            return device_node.UpdateDevicesNodeController(
                node_id=node_id,
                project_id=self.project_id), ''
