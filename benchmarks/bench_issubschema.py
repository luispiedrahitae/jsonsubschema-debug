"""
Benchmark for isSubschema() pipeline performance.
Run before and after optimizations to measure improvement.

Usage:
    python benchmarks/bench_issubschema.py
"""
import cProfile
import io
import pstats
import timeit
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jsonsubschema import isSubschema

# --- Fixture 1: Real ML schema (10 properties, enums, numbers) ---
LALE = {
    "type": "object",
    "properties": {
        "loss": {"enum": ["deviance", "exponential"]},
        "learning_rate": {"type": "number", "minimum": 0.01, "maximum": 1.0},
        "n_estimators": {"type": "integer", "minimum": 10, "maximum": 100},
        "subsample": {"type": "number", "minimum": 0.01, "maximum": 1.0},
        "min_samples_split": {"type": "number", "minimum": 0.01, "maximum": 0.5},
        "min_samples_leaf": {"type": "number", "minimum": 0.01, "maximum": 0.5},
        "max_depth": {"type": "integer", "minimum": 3, "maximum": 5},
        "max_features": {"enum": ["auto", "sqrt", "log2", None]},
        "n_iter_no_change": {"enum": [None]},
        "tol": {"type": "number", "minimum": 1e-8, "maximum": 0.01},
    },
    "additionalProperties": False,
    "required": ["loss"],
}
LALE_NARROW = {
    "type": "object",
    "properties": {
        "loss": {"enum": ["deviance"]},
        "learning_rate": {"type": "number", "minimum": 0.05, "maximum": 0.5},
        "n_estimators": {"type": "integer", "minimum": 50, "maximum": 100},
        "subsample": {"type": "number", "minimum": 0.1, "maximum": 1.0},
        "min_samples_split": {"type": "number", "minimum": 0.05, "maximum": 0.5},
        "min_samples_leaf": {"type": "number", "minimum": 0.05, "maximum": 0.5},
        "max_depth": {"type": "integer", "minimum": 3, "maximum": 4},
        "max_features": {"enum": ["auto", "sqrt"]},
        "n_iter_no_change": {"enum": [None]},
        "tol": {"type": "number", "minimum": 1e-6, "maximum": 0.01},
    },
    "additionalProperties": False,
    "required": ["loss"],
}

# --- Fixture 2: Wide anyOf — 7 branches (all types) ---
ANYOF_WIDE = {"anyOf": [{"type": t} for t in
    ["string", "integer", "number", "boolean", "null", "array", "object"]]}
ANYOF_NARROW = {"anyOf": [{"type": t} for t in ["string", "integer", "number"]]}

# --- Fixture 3: String schemas with complex regex patterns ---
STRING_NARROW = {"type": "string", "pattern": "^(ab){1,3}$", "minLength": 2, "maxLength": 6}
STRING_WIDE   = {"type": "string", "pattern": "^(ab)*$", "maxLength": 10}

# --- Fixture 4: Integer with large enum vs range ---
INT_ENUM = {"type": "integer", "enum": list(range(1, 20))}
INT_RANGE = {"type": "integer", "minimum": 1, "maximum": 25}

# --- Fixture 5: Schema without explicit type (worst case for canonicalize_list_of_types) ---
NO_TYPE_S1 = {"enum": [1, "hello", True, None, 3.14, 2, "world"]}
NO_TYPE_S2 = {"enum": [1, "hello", True, None, 3.14, 2, "world", 42]}

# --- Fixture 6: Nested object 3 levels deep ---
NESTED_NARROW = {
    "type": "object",
    "properties": {
        "address": {
            "type": "object",
            "properties": {
                "street": {"type": "string", "minLength": 1},
                "city": {"type": "string", "minLength": 1},
                "zip": {"type": "string", "pattern": "^[0-9]{5}$"},
                "geo": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "minimum": -90, "maximum": 90},
                        "lon": {"type": "number", "minimum": -180, "maximum": 180},
                    },
                    "required": ["lat", "lon"],
                },
            },
            "required": ["street", "city"],
        }
    },
    "required": ["address"],
}
NESTED_WIDE = {
    "type": "object",
    "properties": {
        "address": {
            "type": "object",
            "properties": {
                "street": {"type": "string"},
                "city": {"type": "string"},
                "zip": {"type": "string"},
                "geo": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lon": {"type": "number"},
                    },
                },
            },
        }
    },
}

FIXTURES = [
    ("ML object (10 props, enums)",     LALE_NARROW,  LALE),
    ("Wide anyOf (7 branches)",         ANYOF_NARROW, ANYOF_WIDE),
    ("String regex (pattern + length)",  STRING_NARROW, STRING_WIDE),
    ("Integer enum vs range",           INT_ENUM,     INT_RANGE),
    ("No-type schema (enum only)",      NO_TYPE_S1,   NO_TYPE_S2),
    ("Nested object (3 levels deep)",   NESTED_NARROW, NESTED_WIDE),
]

REPS = 50


def run_benchmarks():
    print(f"\n{'='*65}")
    print(f"  isSubschema() benchmark  ({REPS} reps each)")
    print(f"{'='*65}")
    print(f"{'Fixture':<38} {'ms/call':>8}  {'total ms':>10}")
    print(f"{'-'*65}")

    total = 0.0
    for name, s1, s2 in FIXTURES:
        elapsed = timeit.timeit(lambda s1=s1, s2=s2: isSubschema(s1, s2), number=REPS)
        ms_per = elapsed / REPS * 1000
        total += elapsed
        print(f"  {name:<36} {ms_per:>8.2f}  {elapsed*1000:>10.1f}")

    print(f"{'-'*65}")
    print(f"  {'TOTAL':<36} {'':>8}  {total*1000:>10.1f}")
    print(f"{'='*65}\n")


def run_profile():
    print("\n--- cProfile top-15 (combined run of all fixtures) ---\n")
    pr = cProfile.Profile()
    pr.enable()
    for _, s1, s2 in FIXTURES:
        for _ in range(10):
            isSubschema(s1, s2)
    pr.disable()

    buf = io.StringIO()
    ps = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
    ps.print_stats(15)
    print(buf.getvalue())


def run_batch_benchmark():
    """Simulate a batch pipeline reusing the same base schema across many variants."""
    base = LALE
    variants = [dict(base, required=[k]) for k in list(base["properties"].keys())[:10]]
    variants += [NESTED_WIDE, NESTED_NARROW, ANYOF_WIDE, ANYOF_NARROW,
                 INT_RANGE, INT_ENUM, NO_TYPE_S1, NO_TYPE_S2,
                 STRING_NARROW, STRING_WIDE]

    BATCH_REPS = 5
    print(f"\n{'='*65}")
    print(f"  Batch simulation ({len(variants)} variants × {BATCH_REPS} passes)")
    print(f"{'='*65}")
    elapsed = timeit.timeit(
        lambda: [isSubschema(v, base) for v in variants],
        number=BATCH_REPS
    )
    total_calls = len(variants) * BATCH_REPS
    print(f"  Total calls : {total_calls}")
    print(f"  Total time  : {elapsed*1000:.1f} ms")
    print(f"  ms/call     : {elapsed/total_calls*1000:.2f}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    run_benchmarks()
    run_batch_benchmark()
    run_profile()
