import json
from copy import deepcopy
import logging
import os
import uuid

logger = logging.getLogger(__name__)


def file2resource(file: str) -> dict:
    """Convert a file to a resource dict.
    
    Args:
        file: The file to convert
    Returns:
        The resource
    """
    # todo
    logger.warning(f'file title and description not implemented, use filename as title and description')
    return {
        'uri': file,
        'title': os.path.basename(file),
        'description': file
    }

def resources2user_input(resources: list[dict]) -> str:
    """Convert a list of resources to a user input string.
    
    Args:
        resources: The list of resources
    Returns:
        The user input string
    """
    resources = deepcopy(resources)
    res_str = json.dumps(resources, indent=2, ensure_ascii=False)
    res_str = "\nThe user uploaded the following files as input resources: \n" + res_str + '\n'
    return res_str
