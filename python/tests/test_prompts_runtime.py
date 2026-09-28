"""C3: the runtime-API appendix covers the crate and ends the Rust prompts."""

import re

from skelnet import prompts
from skelnet.backend import repo_root


def test_runtime_api_covers_public_fns():
    source = (repo_root() / "runtime" / "concir_sync" / "src" / "lib.rs").read_text()
    fns = set(re.findall(r"pub fn (\w+)", source)) - {"set_recorder"}
    api = prompts.read_asset(prompts.RUST_RUNTIME_API_ASSET)
    missing = [fn for fn in sorted(fns) if fn not in api]
    assert not missing, missing


def test_rust_stages_end_with_runtime_api():
    for arm, stage in (("G0", "generate"), ("SKEL", "rust"), ("CIR", "rust")):
        assert prompts.route(arm, stage)[-1] == prompts.RUST_RUNTIME_API_ASSET
