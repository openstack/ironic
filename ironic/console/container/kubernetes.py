#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Kubernetes pod console container provider.
"""
import json
import re
import time
import yaml

from oslo_concurrency import processutils
from oslo_log import log as logging

from ironic.common import exception
from ironic.common import utils
from ironic.conf import CONF
from ironic.console.container import base

LOG = logging.getLogger(__name__)

# How often to check pod status
POD_READY_POLL_INTERVAL = 2


class KubernetesConsoleContainer(base.BaseConsoleContainer):
    """Console container provider which uses kubernetes pods."""

    def __init__(self):
        # confirm kubectl is available
        try:
            utils.execute("kubectl", "version")
        except processutils.ProcessExecutionError as e:
            LOG.exception(
                "kubectl not available, " "this provider cannot be used."
            )
            raise exception.ConsoleContainerError(
                provider="kubernetes", reason=e
            )
        if not CONF.vnc.console_image:
            raise exception.ConsoleContainerError(
                provider="kubernetes",
                reason="[vnc]console_image must be set.",
            )
        try:
            self._render_template()
        except Exception as e:
            raise exception.ConsoleContainerError(
                provider="kubernetes",
                reason=f"Parsing {CONF.vnc.kubernetes_container_template} "
                f"failed: {e}",
            )

    def _render_template(self, uuid="", app_name=None, app_info=None):
        """Render the Kubernetes manifest template.

        :param uuid: Unique identifier for the node.
        :param app_name: Name of the application to run in the container.
        :param app_info: Dictionary of application-specific information.
        :returns: A string containing the rendered Kubernetes YAML manifest.
        """

        # TODO(stevebaker) Support bind-mounting certificate files to
        # handle verified BMC certificates

        if not uuid:
            uuid = ""
        if not app_name:
            app_name = "fake"
        if not app_info:
            app_info = {}

        params = {
            "uuid": uuid,
            "image": CONF.vnc.console_image,
            "app": app_name,
            "app_info": json.dumps(app_info).strip(),
            "read_only": CONF.vnc.read_only,
            "conductor": CONF.host,
        }
        return utils.render_template(
            CONF.vnc.kubernetes_container_template, params=params
        )

    def _apply(self, manifest):
        try:
            utils.execute(
                "kubectl", "apply", "-f", "-", process_input=manifest
            )
        except processutils.ProcessExecutionError as e:
            LOG.exception("Problem calling kubectl apply")
            raise exception.ConsoleContainerError(
                provider="kubernetes", reason=e
            )

    def _delete(
        self, resource_type, namespace, resource_name=None, selector=None
    ):
        args = [
            "kubectl",
            "delete",
            "-n",
            namespace,
            resource_type,
            "--ignore-not-found=true",
        ]
        if resource_name:
            args.append(resource_name)
        elif selector:
            args.append("-l")
            args.append(selector)
        else:
            raise exception.ConsoleContainerError(
                provider="kubernetes",
                reason="Delete must be called with either a resource name "
                "or selector.",
            )
        try:
            utils.execute(*args)
        except processutils.ProcessExecutionError as e:
            LOG.exception("Problem calling kubectl delete")
            raise exception.ConsoleContainerError(
                provider="kubernetes", reason=e
            )

    def _get_pod_node_ip(self, pod_name, namespace):
        try:
            out, _ = utils.execute(
                "kubectl",
                "get",
                "pod",
                pod_name,
                "-n",
                namespace,
                "-o",
                "jsonpath={.status.podIP}",
            )
            return out.strip()
        except processutils.ProcessExecutionError as e:
            LOG.exception("Problem getting pod host IP for %s", pod_name)
            raise exception.ConsoleContainerError(
                provider="kubernetes", reason=e
            )

    def _wait_for_pod_ready(self, pod_name, namespace):
        end_time = time.time() + CONF.vnc.kubernetes_pod_timeout
        while time.time() < end_time:
            try:
                out, _ = utils.execute(
                    "kubectl",
                    "get",
                    "pod",
                    pod_name,
                    "-n",
                    namespace,
                    "-o",
                    "json",
                )
                pod_status = json.loads(out)
                if (
                    "status" in pod_status
                    and "conditions" in pod_status["status"]
                ):
                    for condition in pod_status["status"]["conditions"]:
                        if (
                            condition["type"] == "Ready"
                            and condition["status"] == "True"
                        ):
                            LOG.debug("Pod %s is ready.", pod_name)
                            return
            except (
                processutils.ProcessExecutionError,
                json.JSONDecodeError,
            ) as e:
                LOG.warning(
                    "Could not get pod status for %s: %s", pod_name, e
                )

            time.sleep(POD_READY_POLL_INTERVAL)

        msg = (
            f"Pod {pod_name} did not become ready in "
            f"{CONF.vnc.kubernetes_pod_timeout}s"
        )

        raise exception.ConsoleContainerError(
            provider="kubernetes", reason=msg
        )

    def _get_resources_from_yaml(self, rendered, kind=None):
        """Extracts Kubernetes resources from a YAML manifest.

        This method parses a multi-document YAML string and yields each
        Kubernetes resource (dictionary) found. If `kind` is specified,
        only resources of that specific kind are yielded.

        :param rendered: A string containing the rendered Kubernetes YAML
                         manifest.
        :param kind: Optional string, the 'kind' of Kubernetes resource to
                     filter by (e.g., 'Pod', 'Service'). If None, all
                     resources are yielded.
        :returns: A generator yielding Kubernetes resource dictionaries.
        """
        # Split the YAML into individual documents
        documents = re.split(r"^---\s*$", rendered, flags=re.MULTILINE)
        for doc in documents:
            if not doc.strip():
                continue
            data = yaml.safe_load(doc)
            if not data:
                continue
            if not kind or data.get("kind") == kind:
                yield data

    def start_container(self, task, app_name, app_info):
        """Start a console container for a node.

        Any existing running container for this node will be stopped.

        :param task: A TaskManager instance.
        :raises: ConsoleContainerError
        """
        node = task.node
        uuid = node.uuid

        LOG.debug("Starting console container for node %s", uuid)

        rendered = self._render_template(uuid, app_name, app_info)
        self._apply(rendered)

        pod = list(self._get_resources_from_yaml(rendered, kind="Pod"))[0]
        pod_name = pod["metadata"]["name"]
        namespace = pod["metadata"]["namespace"]

        try:
            self._wait_for_pod_ready(pod_name, namespace)
            host_ip = self._get_pod_node_ip(pod_name, namespace)
        except Exception as e:
            LOG.error(
                "Failed to start container for node %s, cleaning up.", uuid
            )
            try:
                self._stop_container(uuid)
            except Exception:
                LOG.exception(
                    "Could not clean up resources for node %s", uuid
                )
            raise e

        return host_ip, 5900

    def _stop_container(self, uuid):
        rendered = self._render_template(uuid)
        resources = list(self._get_resources_from_yaml(rendered))
        resources.reverse()
        for resource in resources:
            kind = resource["kind"]
            name = resource["metadata"]["name"]
            namespace = resource["metadata"]["namespace"]
            self._delete(kind, namespace, resource_name=name)

    def stop_container(self, task):
        """Stop a console container for a node.

        Any existing running container for this node will be stopped.

        :param task: A TaskManager instance.
        :raises: ConsoleContainerError
        """
        node = task.node
        uuid = node.uuid
        self._stop_container(uuid)

    def _labels_to_selector(self, labels):
        selector = []
        for key, value in labels.items():
            selector.append(f"{key}={value}")
        return ",".join(selector)

    def stop_all_containers(self):
        """Stops all running console containers

        This is run on conductor startup and graceful shutdown to ensure
        no console containers are running.
        :raises: ConsoleContainerError
        """
        LOG.debug("Stopping all console containers")
        rendered = self._render_template()
        resources = list(self._get_resources_from_yaml(rendered))
        resources.reverse()

        for resource in resources:
            kind = resource["kind"]
            namespace = resource["metadata"]["namespace"]
            labels = resource["metadata"]["labels"]
            selector = self._labels_to_selector(labels)
            self._delete(kind, namespace, selector=selector)
