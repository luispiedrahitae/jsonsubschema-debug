'''
Created on June 24, 2019
@author: Andrew Habib
'''

import sys
import jsonschema
import jsonsubschema.observability as observability

this = sys.modules[__name__]

this.VALIDATOR = jsonschema.Draft4Validator     # Which schema validator draft to use
this.PRINT_DB = False                           # Print debugging info?
this.WARN_UNINHABITED = False                   # Enable uninhabited types warning?


# API to set which schema validator draft to use
def set_json_validator_version(v=jsonschema.Draft4Validator):
    ''' Currently, our subtype checking supports json schema draft 4 only,
        so VALIDATOR should not changed.
        We prodive the method for future support of other json schema versions. '''

    this.VALIDATOR = v


# API to set print debugging info?
def set_debug(b=False):
    this.PRINT_DB = bool(b)
    if b:
        observability.enable_debug()
    else:
        observability.disable_debug()


# API to enable uninhabited types warning?
def set_warn_uninhabited(b=False):
    if b:
        this.WARN_UNINHABITED = True
    else:
        this.WARN_UNINHABITED = False
