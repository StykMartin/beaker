import turbogears
import bkr.common
from bkr.server import identity

def beaker_version():
   try: 
        return bkr.common.__version__
   except AttributeError, (e): 
        return 'devel-version'   

def add_custom_stdvars(vars):
    return vars.update({
        "beaker_version": beaker_version,
        "identity": identity.current, # well that's just confusing
    })

turbogears.view.variable_providers.append(add_custom_stdvars)

