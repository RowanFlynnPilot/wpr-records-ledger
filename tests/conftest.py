"""Hypothesis profiles for the clock fuzzer: "default" for every run (CI
included), "deep" for a long local search: $env:HYPOTHESIS_PROFILE = "deep"."""
import os

from hypothesis import settings

settings.register_profile("default", max_examples=1500, deadline=None)
settings.register_profile("deep", max_examples=50_000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))
