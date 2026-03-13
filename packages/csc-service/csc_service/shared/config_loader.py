
import json
from jsonschema import validate, ValidationError
from csc_service.shared.config_schemas import SCHEMAS

def load_config(path, schema_name, logger):
    """
    Load a JSON config file, validate it against a schema, and return it.
    """
    try:
        with open(path) as f:
            config = json.load(f)
        
        schema = SCHEMAS.get(schema_name)
        if not schema:
            logger.log(f"ERROR: No schema found for {schema_name}")
            return None

        validate(instance=config, schema=schema)
        
        # Version migration can be added here in the future
        
        return config
    except json.JSONDecodeError as e:
        logger.log(f"ERROR: Invalid JSON in {path}: {e}")
        return None
    except ValidationError as e:
        logger.log(f"ERROR: Schema validation failed for {path}: {e.message}")
        return None
    except FileNotFoundError:
        logger.log(f"WARNING: Config file not found: {path}, using defaults")
        return {}
