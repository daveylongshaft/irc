"""
Configuration file loader with JSON schema validation.
"""
import json
import logging
from jsonschema import validate, ValidationError

from csc_service.shared.config_schemas import SCHEMAS

logger = logging.getLogger(__name__)

def load_config(path, schema_name):
    """
    Loads a JSON configuration file, validates it against a schema,
    and returns the configuration dictionary.

    :param path: Path to the configuration file.
    :param schema_name: Name of the schema to use for validation.
    :return: Configuration dictionary or None if validation fails.
    """
    try:
        with open(path, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.warning(f"Config file not found: {path}, using defaults.")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {path}: {e}")
        return None

    if schema_name not in SCHEMAS:
        logger.error(f"Unknown schema name: {schema_name}")
        return None

    schema = SCHEMAS[schema_name]

    try:
        validate(instance=config, schema=schema)
        # TODO: Add migration logic here if config["version"] < schema["properties"]["version"]["minimum"]
        return config
    except ValidationError as e:
        logger.error(f"Schema validation failed for {path}:")
        logger.error(f"  - Error: {e.message}")
        logger.error(f"  - Path: {list(e.path)}")
        logger.error(f"  - Validator: {e.validator} = {e.validator_value}")
        return None
