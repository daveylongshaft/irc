import importlib
import inspect
import sys


class ServiceDispatcher:
    """Shared module lookup, class resolution, instance caching, and method dispatch.

    Used by both the server (Service.handle_command) and client
    (ClientServiceHandler._handle_plugin).  All logic lives here once.

    Lookup order (controlled by extra_paths):
      1. csc_loop.infra.<name>
      2. csc_services.<name>
      3. bare <name>           (files on sys.path, e.g. PROJECT_ROOT/services/)
      4. <name>_service        (file_handler deploy convention: <Class>_service.py)
      5+. any extra_paths      (e.g. "plugins.{name}_plugin" for client-local plugins)

    Each entry in extra_paths is a module-name template where {name} is replaced
    with the lowercased class name.
    """

    DEFAULT_NAMESPACES = ["csc_loop.infra", "csc_services"]
    DEFAULT_EXTRA_PATHS = ["{name}_service"]

    def __init__(self, context, extra_paths=None):
        """
        context     -- object passed as the sole argument to service class constructors
        extra_paths -- list of module-name templates tried after the bare name;
                       {name} is substituted with the lowercased class name.
                       Defaults to ["{name}_service"].
        """
        self.context = context
        self.extra_paths = extra_paths if extra_paths is not None else self.DEFAULT_EXTRA_PATHS
        self.loaded = {}   # keyed by class_name_raw; instances survive module reloads

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dispatch(self, class_name_raw, method_name_raw, args):
        """Find the module, resolve the class, dispatch the method.

        Returns a string result (or error message).
        args is a list and may be mutated (default method prepend).
        """
        module, module_name_used = self._find_module(class_name_raw)
        if module is None:
            return f"Error: Module for '{class_name_raw}' not found."

        try:
            class_name = self._resolve_class(module, class_name_raw, module_name_used)
        except ImportError as e:
            return f"Error: {e}"

        try:
            if class_name_raw not in self.loaded:
                self.loaded[class_name_raw] = getattr(module, class_name)(self.context)
            instance = self.loaded[class_name_raw]

            method_to_call = self._resolve_method(instance, method_name_raw, args)
            if method_to_call is None:
                return f"Error: Method '{method_name_raw}' not found in '{class_name}'."

            result = method_to_call(*args)
            return str(result) if result is not None else "OK"

        except Exception as e:
            return f"Error: {e}"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find_module(self, class_name_raw):
        """Walk the lookup chain and return (module, module_name_used) or (None, None)."""
        name_lower = class_name_raw.lower()

        # 1-2: package namespaces
        for ns in self.DEFAULT_NAMESPACES:
            candidate = f"{ns}.{name_lower}"
            module = self._try_import(candidate)
            if module is not None:
                return module, candidate

        # 3: bare name (files directly on sys.path)
        module = self._try_import(name_lower)
        if module is not None:
            return module, name_lower

        # 4+: extra_paths templates
        for template in self.extra_paths:
            candidate = template.format(name=name_lower)
            module = self._try_import(candidate)
            if module is not None:
                return module, candidate

        return None, None

    @staticmethod
    def _try_import(module_name):
        """Import or reload a module by name. Returns module or None on ImportError."""
        try:
            if module_name in sys.modules:
                return importlib.reload(sys.modules[module_name])
            return importlib.import_module(module_name)
        except ImportError:
            return None

    @staticmethod
    def _resolve_class(module, class_name_raw, module_name_used):
        """Find the class in the module. Tries exact, lower, capitalize, then scan."""
        for candidate in [class_name_raw, class_name_raw.lower(), class_name_raw.capitalize()]:
            if hasattr(module, candidate):
                return candidate
        for attr in dir(module):
            if attr.lower() == class_name_raw.lower() and inspect.isclass(getattr(module, attr)):
                return attr
        raise ImportError(f"Class '{class_name_raw}' not found in '{module_name_used}'.")

    @staticmethod
    def _resolve_method(instance, method_name_raw, args):
        """Find a callable method on the instance, falling back to default().

        If default() is used, method_name_raw is prepended to args in-place.
        Returns the callable or None.
        """
        if not method_name_raw.startswith('_') and hasattr(instance, method_name_raw):
            attr = getattr(instance, method_name_raw)
            if inspect.ismethod(attr) or inspect.isfunction(attr):
                return attr

        if hasattr(instance, "default"):
            default = getattr(instance, "default")
            if inspect.ismethod(default) or inspect.isfunction(default):
                args.insert(0, method_name_raw)
                return default

        return None
