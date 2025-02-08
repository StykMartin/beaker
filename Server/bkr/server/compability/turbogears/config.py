import os
import glob
import re

from cherrypy import config
from configobj import ConfigObj
import pkg_resources
import logging
import logging.handlers

import six


__all__ = ["update_config", "get", "update"]


class ConfigError(Exception):
    pass

def _get_formatters(formatters):
    for key, formatter in formatters.items():
        kw = {}
        fmt = formatter.get("format", None)
        if fmt:
            fmt = fmt.replace("*(", "%(")
            kw["fmt"] = fmt
        datefmt = formatter.get("datefmt", None)
        if datefmt:
            kw["datefmt"] = datefmt
        formatter = logging.Formatter(**kw)
        formatters[key] = formatter

def _get_handlers(handlers, formatters):
    for key, handler in handlers.items():
        try:
            cls = handler.get("class")
            args = handler.get("args", tuple())
            level = handler.get("level", None)
            try:
                cls = eval(cls, logging.__dict__)
            except NameError:
                try:
                    cls = eval(cls, logging.handlers.__dict__)
                except NameError:
                    raise ConfigError("Specified class in handler "
                        "%s is not a recognizable logger name" % key)
            try:
                handler_obj = cls(*eval(args, logging.__dict__))
            except IOError as err:
                raise ConfigError("Missing or wrong argument to "
                    "%s in handler %s -> %s " % (cls.__name__,key,err))
            except TypeError as err:
                raise ConfigError("Wrong format for arguments "
                    "to %s in handler %s -> %s" % (cls.__name__,key,err))
            if level:
                level = eval(level, logging.__dict__)
                handler_obj.setLevel(level)
        except KeyError:
            raise ConfigError("No class specified for logging "
                "handler %s" % key)
        formatter = handler.get("formatter", None)
        if formatter:
            try:
                formatter = formatters[formatter]
            except KeyError:
                raise ConfigError("Handler %s references unknown "
                            "formatter %s" % (key, formatter))
            handler_obj.setFormatter(formatter)
        handlers[key] = handler_obj

def _get_loggers(loggers, handlers):
    for key, logger in loggers.items():
        qualname = logger.get("qualname", None)
        if qualname:
            log = logging.getLogger(qualname)
        else:
            log = logging.getLogger()

        level = logger.get("level", None)
        if level:
            level = eval(level, logging.__dict__)
        else:
            level = logging.NOTSET
        log.setLevel(level)

        propagate = logger.get("propagate", None)
        if propagate is not None:
            log.propagate = propagate

        cfghandlers = logger.get("handlers", None)
        if cfghandlers:
            if isinstance(cfghandlers, six.string_types):
                cfghandlers = [cfghandlers]
            for handler in cfghandlers:
                try:
                    handler = handlers[handler]
                except KeyError:
                    raise ConfigError("Logger %s references unknown "
                                "handler %s" % (key, handler))
                log.addHandler(handler)

def configure_loggers(config):
    """Configures the Python logging module, using options that are very
    similar to the ones listed in the Python documentation. This also
    removes the logging configuration from the configuration dictionary
    because CherryPy doesn't like it there. Here are some of the Python
    examples converted to the format used here:

    [logging]
    [[loggers]]
    [[[parser]]]
    [logger_parser]
    level="DEBUG"
    handlers="hand01"
    propagate=1
    qualname="compiler.parser"

    [[handlers]]
    [[[hand01]]]
    class="StreamHandler"
    level="NOTSET"
    formatter="form01"
    args="(sys.stdout,)"

    [[formatters]]
    [[[form01]]]
    format="F1 *(asctime)s *(levelname)s *(message)s"
    datefmt=


    One notable format difference is that *() is used in the formatter
    instead of %() because %() is already used for config file
    interpolation.

    """
    if not config.has_key("logging"):
        config.setdefault("global", {})["tg.new_style_logging"] = False
        return
    logcfg = config["logging"]
    formatters = logcfg.get("formatters", {})
    _get_formatters(formatters)

    handlers = logcfg.get("handlers", {})
    _get_handlers(handlers, formatters)

    loggers = logcfg.get("loggers", {})
    _get_loggers(loggers, handlers)

    del config["logging"]
    config.setdefault("global", {})["tg.new_style_logging"] = True

def config_defaults():
    """Return a dict with default global config settings."""
    return dict(
        current_dir_uri = os.path.abspath(os.getcwd())
    )

def config_obj(configfile = None, modulename = None):
    """Read configuration from given config file and/or module.

    See the docstring of the 'update_config' function for parameter description.

    Returns a config.ConfigObj object.

    """
    defaults = config_defaults()

    if modulename:
        firstdot = modulename.find('.')
        if firstdot < 0:
            raise ConfigError('Config file package not specified')
        lastdot = modulename.rfind('.')
        top_level_package = modulename[:firstdot]
        packagename = modulename[:lastdot]
        modname = modulename[lastdot+1:]
        modfile = pkg_resources.resource_filename(packagename,
                                        modname + '.cfg')
        if not os.path.exists(modfile):
            modfile = pkg_resources.resource_filename(packagename,
                                            modname)
        if os.path.isdir(modfile):
            configfiles = glob.glob(os.path.join(modfile, '*.cfg'))
        else:
            configfiles = [modfile]
        configdata = ConfigObj(unrepr=True)
        top_level_dir = os.path.normpath(pkg_resources.resource_filename(
            top_level_package, ''))
        package_dir = os.path.normpath(pkg_resources.resource_filename(
            packagename, ''))
        defaults.update(dict(top_level_dir=top_level_dir,
                             package_dir=package_dir))
        configdata.merge(dict(DEFAULT=defaults))
        for file in configfiles:
            configdata2 = ConfigObj(file, unrepr=True)
            configdata2.merge(dict(DEFAULT=defaults))
            configdata.merge(configdata2)

    if configfile:
        if modulename:
            configdata2 = ConfigObj(configfile, unrepr=True)
            configdata2.merge(dict(DEFAULT=defaults))
            configdata.merge(configdata2)
        else:
            configdata = ConfigObj(configfile, unrepr=True)
    return configdata

def update_config(configfile=None, modulename=None):
    """Update the system configuration from given config file and/or module.

    'configfile' is a ConfigObj (INI-style) config file, 'modulename' a module
    path in dotted notation. The function looks for files with a ".cfg"
    extension if the given module name refers to a package directory or a file
    with the base name of the right-most part of the module path and a ".cfg"
    extension added.

    If both 'configfile' and 'modulname' are specified, the module is read
    first, followed by the config file. This means that the config file's
    options override the options in the module file.

    """
    configdict = config_obj(configfile, modulename).dict()
    configure_loggers(configdict)
    config.update(configdict)

def get(key, default_value=None, return_section=False, path=None):
    """Return config value with setting name given by 'key'.

    If the config setting is unset, return given 'default_value' instead. If
    'return_section' is specified, return the path to the value, instead of the
    value itself. If 'path' is specified, return the value of the setting
    in the context of the given URL path or below.

    """
    value = config.get(key, default_value, return_section, path)
    if value and key == 'sqlobject.dburi' and os.name == 'nt':
        value = re.sub('///([A-Za-z]):', r'///\1|', value)
    return value

def update(configvalues):
    """Update the configuration with the values from the dictionary."""
    return config.update(configvalues)

def copy():
    """Return a copy of config values."""
    return config.configMap.copy()
