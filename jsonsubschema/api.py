'''
Created on June 24, 2019
@author: Andrew Habib
'''

import sys
import time
import jsonref

from jsonsubschema._canonicalization import (
    canonicalize_schema,
    simplify_schema_and_embed_checkers
)
from jsonsubschema._utils import (
    validate_schema,
    print_db
)
import jsonsubschema.observability as obs

from jsonsubschema.exceptions import UnsupportedRecursiveRef


def prepare_operands(s1, s2):
    # First, we load schemas using jsonref to resolve $ref
    # before starting canonicalization.
    s1 = jsonref.JsonRef.replace_refs(s1)
    s2 = jsonref.JsonRef.replace_refs(s2)

    # Canonicalize and embed checkers for both lhs and rhs schemas
    # before starting the subtype checking.
    # This also validates input schemas and canonicalized schemas.
    obs.log_event("canonicalize.start", side="s1", input=dict(s1) if hasattr(s1, 'items') else s1)
    try:
        _s1 = simplify_schema_and_embed_checkers(canonicalize_schema(s1))
    except RecursionError:
        raise UnsupportedRecursiveRef(s1, 'LHS') from None
    obs.log_event("canonicalize.done", side="s1", output=type(_s1).__name__, schema=repr(_s1)[:120])

    obs.log_event("canonicalize.start", side="s2", input=dict(s2) if hasattr(s2, 'items') else s2)
    try:
        _s2 = simplify_schema_and_embed_checkers(canonicalize_schema(s2))
    except RecursionError:
        raise UnsupportedRecursiveRef(s2, 'RHS') from None
    obs.log_event("canonicalize.done", side="s2", output=type(_s2).__name__, schema=repr(_s2)[:120])

    return _s1, _s2


def isSubschema(s1, s2):
    ''' Entry point for schema subtype checking. '''
    obs.log_event("pipeline.start", op="isSubschema", s1=s1, s2=s2)
    t0 = time.perf_counter()
    s1c, s2c = prepare_operands(s1, s2)
    result = s1c.isSubtype(s2c)
    obs.log_event("pipeline.result", op="isSubschema", result=result,
                  duration_ms=round((time.perf_counter() - t0) * 1000, 2))
    return result


def meet(s1, s2):
    ''' Entry point for schema meet operation. '''
    obs.log_event("pipeline.start", op="meet", s1=s1, s2=s2)
    t0 = time.perf_counter()
    s1c, s2c = prepare_operands(s1, s2)
    result = s1c.meet(s2c)
    obs.log_event("pipeline.result", op="meet", result=repr(result)[:120],
                  duration_ms=round((time.perf_counter() - t0) * 1000, 2))
    return result


def join(s1, s2):
    ''' Entry point for schema join operation. '''
    obs.log_event("pipeline.start", op="join", s1=s1, s2=s2)
    t0 = time.perf_counter()
    s1c, s2c = prepare_operands(s1, s2)
    result = s1c.join(s2c)
    obs.log_event("pipeline.result", op="join", result=repr(result)[:120],
                  duration_ms=round((time.perf_counter() - t0) * 1000, 2))
    return result


def isEquivalent(s1, s2):
    ''' Entry point for schema equivalence check operation. '''
    obs.log_event("pipeline.start", op="isEquivalent", s1=s1, s2=s2)
    t0 = time.perf_counter()
    result = isSubschema(s1, s2) and isSubschema(s2, s1)
    obs.log_event("pipeline.result", op="isEquivalent", result=result,
                  duration_ms=round((time.perf_counter() - t0) * 1000, 2))
    return result
