import importlib
from typing import cast

from bb_fnds.cdk_constructs import pipeline_forge

from cdk.stack_inputs import StackInputs


def get_stack_inputs(stack: pipeline_forge.Stack):
    developer_instance = stack.stage == 'local'
    if stack.is_il4:
        if developer_instance or stack.stage == 'dev':
            config_name = 'il4_dev'
        else:
            config_name = 'il4_prod'

    else:
        if developer_instance:
            config_name = 'dev_us_east_1'
        else:
            config_name = f'{stack.stage}_{stack.region.replace("-", "_")}'
            if stack.deployment:
                config_name += f'_{stack.deployment}'

    current_env = importlib.import_module(f'cdk.environments.{config_name}')
    stack_inputs = cast(StackInputs, current_env.config)
    stack_inputs.developer_instance = developer_instance
    return stack_inputs
