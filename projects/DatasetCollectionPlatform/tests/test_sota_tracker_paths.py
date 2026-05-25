from __future__ import annotations

from pathlib import Path

from tools.lib.sota_tracker_paths import SotaTrackerPaths, proxy_environment


def test_default_tracker_paths_use_data_disks():
    paths = SotaTrackerPaths.default()

    assert paths.research_root == Path("/home/data_1/research")
    assert paths.models_root == Path("/home/data_0/models")
    assert paths.cache_root == Path("/home/data_0/cache")
    assert paths.tapnet_repo == Path("/home/data_1/research/tapnet")
    assert paths.cotracker_repo == Path("/home/data_1/research/co-tracker")
    assert paths.tapnextpp_checkpoint == Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt")
    assert paths.cotracker_offline_checkpoint == Path("/home/data_0/models/cotracker3/scaled_offline.pth")
    assert paths.cotracker_online_checkpoint == Path("/home/data_0/models/cotracker3/scaled_online.pth")


def test_proxy_environment_sets_7897_for_http_download_tools():
    env = proxy_environment({"PATH": "/bin"}, proxy="http://127.0.0.1:7897")

    assert env["http_proxy"] == "http://127.0.0.1:7897"
    assert env["https_proxy"] == "http://127.0.0.1:7897"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:7897"
    assert env["PIP_CACHE_DIR"] == "/home/data_0/cache/pip"
    assert env["HF_HOME"] == "/home/data_0/cache/huggingface"
    assert env["TORCH_HOME"] == "/home/data_0/models/torch"
    assert env["PATH"] == "/bin"
