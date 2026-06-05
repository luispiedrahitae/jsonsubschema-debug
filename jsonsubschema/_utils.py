'''
Created on May 24, 2019
@author: Andrew Habib
'''


import copy
import fractions
import functools
import math
import numbers
import re
import sys
import json

import jsonschema
import portion as I
from greenery import parse

import jsonsubschema.config as config
import jsonsubschema._constants as definitions
import jsonsubschema.observability as observability

# Cache for compiled (parsed + reduced) greenery FSMs keyed on pattern string.
# Avoids re-parsing identical patterns across different schema comparisons.
_greenery_cache: dict = {}

# Cache for validate_schema results keyed on JSON-serialized schema.
# check_schema() costs ~1ms each; schemas repeat heavily in batch pipelines.
_validate_cache: dict = {}

# Cache for get_valid_enum_vals results keyed on JSON-serialized schema.
# Avoids rebuilding Draft4Validator and re-validating each enum item on repeated calls.
_enum_vals_cache: dict = {}


def _compiled_pattern(p: str):
    if p not in _greenery_cache:
        _greenery_cache[p] = parse(p).reduce()
    return _greenery_cache[p]


def is_str(i):
    return isinstance(i, str)


def is_int(i):
    if isinstance(i, bool):
        return False
    return isinstance(i, int)


def is_int_equiv(i):
    if isinstance(i, bool):
        return False
    return isinstance(i, int) or (isinstance(i, float) and float(i).is_integer())


# def is_float(i):
#     return isinstance(i, float)


def is_num(i):
    if isinstance(i, bool):
        return False
    return isinstance(i, numbers.Number)


def is_bool(i):
    return isinstance(i, bool)


# def is_null(i):
#     isinstance(i, type(None))


def is_list(i):
    return isinstance(i, list)


def is_dict(i):
    return isinstance(i, dict)


# def is_empty_dict_or_none(i):
#     return i == {} or i == None


# def is_dict_or_true(i):
#     return isinstance(i, dict) or i == True


def validate_schema(s):
    try:
        key = json.dumps(s, sort_keys=True, allow_nan=True)
    except TypeError:
        return config.VALIDATOR.check_schema(s)  # non-serializable edge case, skip cache
    if key not in _validate_cache:
        _validate_cache[key] = config.VALIDATOR.check_schema(s)
    return _validate_cache[key]


def get_valid_enum_vals(enum, s):
    # Build Draft4Validator once per (enum, schema) pair instead of calling
    # jsonschema.validate() per item. jsonschema.validate() calls check_schema()
    # internally, which resolves all $ref references in the Draft4 meta-schema —
    # once per enum value, not once per schema. The schema is already validated by
    # validate_schema() at this point.
    #
    # Cache key includes enum because this function is called from two contexts:
    # canonicalize_enum (enum == s["enum"]) and subtype_enum (enum == LHS checker
    # enum, s == RHS schema), so enum and s["enum"] may differ.
    try:
        key = (json.dumps(enum, sort_keys=True, allow_nan=True),
               json.dumps(s, sort_keys=True, allow_nan=True))
    except TypeError:
        validator = config.VALIDATOR(s)
        return [i for i in enum if validator.is_valid(i)]

    if key not in _enum_vals_cache:
        validator = config.VALIDATOR(s)
        _enum_vals_cache[key] = [i for i in enum if validator.is_valid(i)]
    return list(_enum_vals_cache[key])


def get_typed_enum_vals(enum, t):
    if t == "integer":
        enum = filter(lambda i: not isinstance(i, bool), enum)
    # try:
    #     return sorted(filter(lambda i: isinstance(i, definitions.JtypesToPyTypes[t]), enum))
    # except TypeError:
    #     return list(filter(lambda i: isinstance(i, definitions.JtypesToPyTypes[t]), enum))
    return list(filter(lambda i: isinstance(i, definitions.JtypesToPyTypes[t]), enum))


def print_db(*args):
    if config.PRINT_DB:
        msg = "".join(str(arg) + " " for arg in args) if args else ""
        print(msg)
        observability.log_event("debug.internal", msg=msg.strip())


# def one(iterable):
#     for i in range(len(iterable)):
#         if iterable[i]:
#             return not (any(iterable[:i]) or any(iterable[i+1:]))
#     return False

#
# To avoid regex bottlenecks, instead of using '.*'
# as the default value for string.pattern, we use
# 'None' and apply explicit checks for 'None'.
# E.g. regex_meet(s1, None) = s1
#


def prepare_pattern_for_greenry(s):
    ''' The greenery library we use for regex intersection assumes 
        patterns are unanchored by default. Anchoring chars ^ and $ are
        treated as literals by greenery.
        So basically strip any non-escaped ^ and $ when using greenery.
        Moreover, for any escaped ^ or $, we remove the \ to adhere to 
        greenery syntax (when they are escaped, they are literals). '''

    s = re.sub(r'(?<!\\|\[)((?:\\{2})*)\^', r'\g<1>',
               s)  # strip non-escaped ^ that is not inside []
    s = re.sub(r'(?<!\\)((?:\\{2})*)\$', r'\g<1>', s)  # strip non-escaped $
    s = re.sub(r'(?<!\\)((?:\\{1})*)\\\^', r'\g<1>^', s)  # strip \ before ^
    s = re.sub(r'(?<!\\)((?:\\{1})*)\\\$', r'\g<1>$', s)  # strip \ before $

    return s


def regex_unanchor(p):
    # We need this cuz JSON regexs are not anchored by default
    # while the regex library we use assumes the opposite:
    # regexes are anchored by default AND ^ and $ are literals
    # and don't carry their anchoring meaning.
    if p:
        if p[0] == "^":
            p = p[1:]
        elif p[:2] != ".*":
            p = ".*" + p
        if p[-1] == "$":
            p = p[:-1]
        elif p[-2:] != ".*":
            p = p + ".*"
    # else:  # case p == "" the empty string
    #     p = ".*"
    return p


def regex_matches_string(regex=None, s=None):
    if regex:
        return parse(regex).matches(s)
    else:
        return True


@functools.lru_cache(maxsize=512)
def regex_meet(s1, s2):
    if s1 and s2:
        ret = _compiled_pattern(s1) & _compiled_pattern(s2)
        return str(ret.reduce()) if not ret.empty() else None
    elif s1:
        return s1
    elif s2:
        return s2
    else:
        return None


@functools.lru_cache(maxsize=512)
def regex_isSubset(s1, s2):
    ''' regex subset is quite expensive to compute
        especially for complex patterns. '''
    if s1 and s2:
        fsm1 = _compiled_pattern(s1)
        fsm2 = _compiled_pattern(s2)
        try:
            fsm1.cardinality()
            fsm2.cardinality()
            return set(fsm1.strings()).issubset(fsm2.strings())
        except (OverflowError, Exception):
            # catching a general exception thrown from greenery
            # see https://github.com/qntm/greenery/blob/master/greenery/lego.py
            # ... raise Exception("Please choose an 'otherchar'")
            return fsm1.equivalent(fsm2) or (fsm1 & fsm2.everythingbut()).empty()
        except Exception as e:
            exit_with_msg("regex failure from greenry", e)
    elif s1:
        return True
    elif s2:
        return _compiled_pattern(s2).equivalent(parse(".*"))


# def regex_isProperSubset(s1, s2):
#     ''' regex proper subset is quite expensive to compute
#         so we try to break it into two separate checks,
#         and do the more expensive check, only if the
#         cheaper one passes first. '''

#     s1 = parse(s1).reduce()
#     s2 = parse(s2).reduce()
#     if not s1.equivalent(s2):
#         return (s1 & s2.everythingbut()).empty()
#     return False


def string_range_to_regex(min, max):
    assert min <= max, ""
    if min == max:
        pattern = ".{" + str(min) + "}"             # '.{min}'
    elif max == I.inf:
        pattern = ".{" + str(min) + ",}"            # '.{min,}'
    else:
        pattern = ".{" + str(min) + "," + str(max) + "}"  # '.{min, max}'

    return pattern


def complement_of_string_pattern(s):
    return str(parse(s).everythingbut().reduce())


def lcm(x, y):
    bad_values = [None, ]  # I.inf, -I.inf]
    if x in bad_values:
        if y in bad_values:
            return None
        else:
            return y
    elif y in bad_values:
        return x
    else:
        if is_int(x) and is_int(y):
            return x * y / math.gcd(int(x), int(y))
        else:
            # import warnings
            # with warnings.catch_warnings():
            #     warnings.filterwarnings("ignore", category=DeprecationWarning)
            return x * y / float_gcd(x, y)


def gcd(x, y):
    bad_values = [None, ]  # I.inf, -I.inf, None]
    if x in bad_values:
        if y in bad_values:
            return None
        else:
            return None
    elif y in bad_values:
        return None
    else:
        if is_int(x) and is_int(y):
            return math.gcd(int(x), int(y))
        else:
            # import warnings
            # with warnings.catch_warnings():
            #     warnings.filterwarnings("ignore", category=DeprecationWarning)
            return float_gcd(x, y)


def float_gcd(a, b):
    # fractions.gcd used to kind-of-work but was removed in Python 3.9.
    # math.gcd still exists but only for integers.
    # This reuses the fractions.gcd logic but refines it by re-interpreting
    # the floats as fractions.
    # This is far from perfect but gives the expected result in more cases.
    fa = fractions.Fraction(str(a))
    fb = fractions.Fraction(str(b))
    while fb:
        fa, fb = fb, fa % fb
    return float(fa)


# def decrementFloat(f):
#     if f == 0.0:
#         return sys.float_info.min
#     m, e = math.frexp(f)
#     return math.ldexp(m - sys.float_info.epsilon / 2, e)


# def incrementFloat(f):
#     if f == 0.0:
#         return sys.float_info.min
#     m, e = math.frexp(f)
#     return math.ldexp(m + sys.float_info.epsilon / 2, e)


def generate_range_with_multipleOf_or(range_, pos_mul_of):
    print(pos_mul_of)
    if pos_mul_of:
        for i in range_:
            if any(i % k == 0 for k in pos_mul_of):
                yield i
    else:
        for i in range_:
            # if any(i % k == 0 for k in pos_mul_of):
            yield i


def generate_range_with_not_multipleOf_and(range_, neg_mul_of):
    if neg_mul_of:
        for i in range_:
            if all(i % k != 0 for k in neg_mul_of):
                yield i
    else:
        for i in range_:
            yield i


def generate_range_with_multipleof(range_, pos, neg):
    return generate_range_with_not_multipleOf_and(
        generate_range_with_multipleOf_or(range_, pos),
        neg)


def get_new_min_max_with_mulof(mn, mx, mulof):
    #
    # At the moment, this is part of an enumerative solution
    # for multipleOf integer.
    # Is there a more efficient way to find, for  x <= n <= y,
    # what is the smallest x_min > x s.t. x_min % f = 0
    # and the largest y_max < y s.t. x_max % f = 0
    # for some factor f.
    #
    if is_num(mulof) and mulof < mx:
        if is_num(mn):
            while mn % mulof != 0:
                mn = mn + 1
        if is_num(mx):
            while mx % mulof != 0:
                mx = mx - 1
    return mn, mx


def is_interval_finite(i):
    return is_num(i.lower) and is_num(i.upper)


def are_intervals_mergable(i1, i2):
    return i1.overlaps(i2) \
        or (is_num(i1.lower) and is_num(i2.upper) and i1.lower - i2.upper == 1) \
        or (is_num(i2.lower) and is_num(i1.upper) and i2.lower - i1.upper == 1)


def load_json_file(path, msg=None):
    with open(path, "r") as fh:
        try:
            return json.load(fh)
        except Exception as e:
            exit_with_msg(msg, e)


def exit_with_msg(msg, e=None):
    print("Message:", msg, ";", "Exception:", e)
    sys.exit(1)
