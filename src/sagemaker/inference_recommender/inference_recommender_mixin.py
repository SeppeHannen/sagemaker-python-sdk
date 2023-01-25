# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
"""Placeholder docstring"""
from __future__ import absolute_import

import logging

from typing import List, Dict, Optional

import sagemaker

from sagemaker.parameter import CategoricalParameter

INFERENCE_RECOMMENDER_FRAMEWORK_MAPPING = {
    "xgboost": "XGBOOST",
    "sklearn": "SAGEMAKER-SCIKIT-LEARN",
    "pytorch": "PYTORCH",
    "tensorflow": "TENSORFLOW",
    "mxnet": "MXNET",
}

LOGGER = logging.getLogger("sagemaker")


class Phase:
    """Used to store phases of a traffic pattern to perform endpoint load testing.

    Required for an Advanced Inference Recommendations Job
    """

    def __init__(self, duration_in_seconds: int, initial_number_of_users: int, spawn_rate: int):
        """Initialze a `Phase`"""
        self.to_json = {
            "DurationInSeconds": duration_in_seconds,
            "InitialNumberOfUsers": initial_number_of_users,
            "SpawnRate": spawn_rate,
        }


class ModelLatencyThreshold:
    """Used to store inference request/response latency to perform endpoint load testing.

    Required for an Advanced Inference Recommendations Job
    """

    def __init__(self, percentile: str, value_in_milliseconds: int):
        """Initialze a `ModelLatencyThreshold`"""
        self.to_json = {"Percentile": percentile, "ValueInMilliseconds": value_in_milliseconds}


class InferenceRecommenderMixin:
    """A mixin class for SageMaker ``Inference Recommender`` that will be extended by ``Model``"""

    def right_size(
        self,
        sample_payload_url: str = None,
        supported_content_types: List[str] = None,
        supported_instance_types: List[str] = None,
        job_name: str = None,
        framework: str = None,
        job_duration_in_seconds: int = None,
        hyperparameter_ranges: List[Dict[str, CategoricalParameter]] = None,
        phases: List[Phase] = None,
        traffic_type: str = None,
        max_invocations: int = None,
        model_latency_thresholds: List[ModelLatencyThreshold] = None,
        max_tests: int = None,
        max_parallel_tests: int = None,
        log_level: Optional[str] = "Verbose",
    ):
        """Recommends an instance type for a SageMaker or BYOC model.

        Args:
            sample_payload_url (str): The S3 path where the sample payload is stored.
            supported_content_types: (list[str]): The supported MIME types for the input data.
            supported_instance_types (list[str]): A list of the instance types that this model
                is expected to work on. (default: None).
            job_name (str): The name of the Inference Recommendations Job. (default: None).
            framework (str): The machine learning framework of the Image URI.
                Only required to specify if you bring your own custom containers (default: None).
            job_duration_in_seconds (int): The maximum job duration that a job can run for.
                (default: None).
            hyperparameter_ranges (list[Dict[str, sagemaker.parameter.CategoricalParameter]]):
                Specifies the hyper parameters to be used during endpoint load tests.
                `instance_type` must be specified as a hyperparameter range.
                `env_vars` can be specified as an optional hyperparameter range. (default: None).
                Example::

                    hyperparameter_ranges = [{
                        'instance_types': CategoricalParameter(['ml.c5.xlarge', 'ml.c5.2xlarge']),
                        'OMP_NUM_THREADS': CategoricalParameter(['1', '2', '3', '4'])
                    }]

            phases (list[Phase]): Specifies the criteria for increasing load
                during endpoint load tests. (default: None).
            traffic_type (str): Specifies the traffic type that matches the phases. (default: None).
            max_invocations (str): defines invocation limit for endpoint load tests (default: None).
            model_latency_thresholds (list[ModelLatencyThreshold]): defines the response latency
                thresholds for endpoint load tests (default: None).
            max_tests (int): restricts how many endpoints are allowed to be
                spun up for this job (default: None).
            max_parallel_tests (int): restricts how many concurrent endpoints
                this job is allowed to spin up (default: None).
            log_level (str): specifies the inline output when waiting for right_size to complete
                (default: "Verbose").

        Returns:
            sagemaker.model.Model: A SageMaker ``Model`` object. See
            :func:`~sagemaker.model.Model` for full details.
        """
        if not isinstance(self, sagemaker.model.ModelPackage):
            raise ValueError("right_size() is currently only supported with a registered model")

        if not framework and self._framework():
            framework = INFERENCE_RECOMMENDER_FRAMEWORK_MAPPING.get(self._framework, framework)

        framework_version = self._get_framework_version()

        endpoint_configurations = self._convert_to_endpoint_configurations_json(
            hyperparameter_ranges=hyperparameter_ranges
        )
        traffic_pattern = self._convert_to_traffic_pattern_json(
            traffic_type=traffic_type, phases=phases
        )
        stopping_conditions = self._convert_to_stopping_conditions_json(
            max_invocations=max_invocations, model_latency_thresholds=model_latency_thresholds
        )
        resource_limit = self._convert_to_resource_limit_json(
            max_tests=max_tests, max_parallel_tests=max_parallel_tests
        )

        if endpoint_configurations or traffic_pattern or stopping_conditions or resource_limit:
            LOGGER.info("Advance Job parameters were specified. Running Advanced job...")
            job_type = "Advanced"
        else:
            LOGGER.info("Advance Job parameters were not specified. Running Default job...")
            job_type = "Default"

        self._init_sagemaker_session_if_does_not_exist()

        ret_name = self.sagemaker_session.create_inference_recommendations_job(
            role=self.role,
            job_name=job_name,
            job_type=job_type,
            job_duration_in_seconds=job_duration_in_seconds,
            model_package_version_arn=self.model_package_arn,
            framework=framework,
            framework_version=framework_version,
            sample_payload_url=sample_payload_url,
            supported_content_types=supported_content_types,
            supported_instance_types=supported_instance_types,
            endpoint_configurations=endpoint_configurations,
            traffic_pattern=traffic_pattern,
            stopping_conditions=stopping_conditions,
            resource_limit=resource_limit,
        )

        self.inference_recommender_job_results = (
            self.sagemaker_session.wait_for_inference_recommendations_job(
                ret_name, log_level=log_level
            )
        )
        self.inference_recommendations = self.inference_recommender_job_results.get(
            "InferenceRecommendations"
        )

        return self

    def _check_inference_recommender_args(
        self,
        instance_type=None,
        initial_instance_count=None,
        accelerator_type=None,
        serverless_inference_config=None,
        async_inference_config=None,
    ):
        """Validates that Inference Recommendation parameters can be used in `model.deploy()`

        Args:
            instance_type (str): The initial number of instances to run
                in the ``Endpoint`` created from this ``Model``. If not using
                serverless inference or the model has not called ``right_size()``,
                then it need to be a number larger or equals
                to 1 (default: None)
            initial_instance_count (int):The EC2 instance type to deploy this Model to.
                For example, 'ml.p2.xlarge', or 'local' for local mode. If not using
                serverless inference or the model has not called ``right_size()``,
                then it is required to deploy a model.
                (default: None)
            accelerator_type (str): whether accelerator_type has been passed into `model.deploy()`.
            serverless_inference_config (sagemaker.serverless.ServerlessInferenceConfig)):
                whether serverless_inference_config has been passed into `model.deploy()`.
            async_inference_config (sagemaker.model_monitor.AsyncInferenceConfig):
                whether async_inference_config has been passed into `model.deploy()`.

        Returns:
            (string, int) or None: Top instance_type and associated initial_instance_count
            if self.inference_recommender_job_results has been generated. Otherwise, return None.
        """
        if accelerator_type:
            raise ValueError("accelerator_type is not compatible with right_size().")
        if instance_type or initial_instance_count:
            LOGGER.warning(
                "instance_type or initial_instance_count specified."
                "Overriding right_size() recommendations."
            )
            return None
        if async_inference_config:
            LOGGER.warning(
                "async_inference_config is specified. Overriding right_size() recommendations."
            )
            return None
        if serverless_inference_config:
            LOGGER.warning(
                "serverless_inference_config is specified. Overriding right_size() recommendations."
            )
            return None

        instance_type = self.inference_recommendations[0]["EndpointConfiguration"]["InstanceType"]
        initial_instance_count = self.inference_recommendations[0]["EndpointConfiguration"][
            "InitialInstanceCount"
        ]
        return (instance_type, initial_instance_count)

    def _convert_to_endpoint_configurations_json(
        self, hyperparameter_ranges: List[Dict[str, CategoricalParameter]]
    ):
        """Bundle right_size() parameters into an endpoint configuration for Advanced job"""
        if not hyperparameter_ranges:
            return None

        endpoint_configurations_to_json = []
        for parameter_range in hyperparameter_ranges:
            if not parameter_range.get("instance_types"):
                raise ValueError("instance_type must be defined as a hyperparameter_range")
            parameter_range = parameter_range.copy()
            instance_types = parameter_range.get("instance_types").values
            parameter_range.pop("instance_types")

            for instance_type in instance_types:
                parameter_ranges = []
                for name, param in parameter_range.items():
                    as_json = param.as_json_range(name)
                    as_json["Value"] = as_json.pop("Values")
                    parameter_ranges.append(as_json)
                endpoint_configurations_to_json.append(
                    {
                        "EnvironmentParameterRanges": {
                            "CategoricalParameterRanges": parameter_ranges
                        },
                        "InstanceType": instance_type,
                    }
                )

        return endpoint_configurations_to_json

    def _convert_to_traffic_pattern_json(self, traffic_type: str, phases: List[Phase]):
        """Bundle right_size() parameters into a traffic pattern for Advanced job"""
        if not phases:
            return None
        return {
            "Phases": [phase.to_json for phase in phases],
            "TrafficType": traffic_type if traffic_type else "PHASES",
        }

    def _convert_to_resource_limit_json(self, max_tests: int, max_parallel_tests: int):
        """Bundle right_size() parameters into a resource limit for Advanced job"""
        if not max_tests and not max_parallel_tests:
            return None
        return {
            "MaxNumberOfTests": max_tests,
            "MaxParallelOfTests": max_parallel_tests,
        }

    def _convert_to_stopping_conditions_json(
        self, max_invocations: int, model_latency_thresholds: List[ModelLatencyThreshold]
    ):
        """Bundle right_size() parameters into stopping conditions for Advanced job"""
        if not max_invocations and not model_latency_thresholds:
            return None
        return {
            "MaxInvocations": max_invocations,
            "ModelLatencyThresholds": [threshold.to_json for threshold in model_latency_thresholds],
        }
