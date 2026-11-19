from hypothesis import settings

# The mutation run needs repeatable verdicts: a fixed example sequence, no
# example database carried between mutants, and no deadline, since the
# mutation tool's dispatch makes every call slower.
settings.register_profile(
    "mutation", derandomize=True, database=None, deadline=None
)
