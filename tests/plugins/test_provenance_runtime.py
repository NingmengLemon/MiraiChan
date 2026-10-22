"""核验插件的运行期状态: 冷却与图片级去重

入口模块需要 bot 实例, 测试导入不了, 所以这部分逻辑单独放一个模块测。
"""

from __future__ import annotations

from mbplugin_provenance.client import ProvenanceResult
from mbplugin_provenance.runtime import CheckRegistry, Cooldown, access_level

RESULTS = (ProvenanceResult(type="c2pa", outcome="not_detected"),)


def test_access_level() -> None:
    # allow_all 优先; 默认 (False, True) 对应现网只开管理员
    assert access_level(True, False) == "all"
    assert access_level(True, True) == "all"
    assert access_level(False, True) == "admins"
    assert access_level(False, False) == "owner"


def test_cooldown_remaining() -> None:
    cooldown = Cooldown(seconds=10.0)
    assert cooldown.remaining(1, now=100.0) == 0.0
    cooldown.touch(1, now=100.0)
    assert cooldown.remaining(1, now=103.0) == 7.0
    assert cooldown.remaining(1, now=115.0) == 0.0
    # 独立用户不共享冷却
    assert cooldown.remaining(2, now=103.0) == 0.0


def test_registry_caches_recent_result() -> None:
    registry = CheckRegistry(ttl=60.0)
    assert registry.cached("abc", now=100.0) is None
    assert registry.begin("abc")
    registry.finish("abc", RESULTS, now=100.0)
    assert registry.cached("abc", now=130.0) == RESULTS
    # 过了 TTL 就不再复用
    assert registry.cached("abc", now=200.0) is None


def test_registry_skips_running_digest() -> None:
    registry = CheckRegistry(ttl=60.0)
    assert registry.begin("abc")
    # 同一个摘要正在检查时, 第二个请求不能开始
    assert not registry.begin("abc")
    # 不同摘要互不影响
    assert registry.begin("def")
    registry.finish("abc", RESULTS, now=0.0)
    # 结束后可以重新占用 (命中缓存时根本不会走到 begin)
    assert registry.begin("abc")


def test_registry_does_not_cache_failures() -> None:
    registry = CheckRegistry(ttl=60.0)
    assert registry.begin("abc")
    registry.finish("abc", None, now=0.0)
    assert registry.cached("abc", now=1.0) is None
    assert registry.begin("abc")


def test_registry_prunes_expired_entries() -> None:
    registry = CheckRegistry(ttl=10.0)
    registry.begin("old")
    registry.finish("old", RESULTS, now=0.0)
    registry.begin("new")
    registry.finish("new", RESULTS, now=100.0)
    # 落后 TTL 的条目在写入新结果时被清掉
    assert registry.cached("old", now=100.0) is None
    assert registry.cached("new", now=105.0) == RESULTS
