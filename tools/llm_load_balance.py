"""多 key 轮询与冷却的真端点验证

读 `NVIDIA_API_KEYS`(逗号分隔的多个 key), 把每个 key 变成一个端点, 同一个别名下跑若干次请求,
用 `Pool.stats()` 看请求是不是摊到了每个 key 上, 以及坏 key 会不会被禁用之后自动绕开。

用法: uv run --env-file .env python tools/llm_load_balance.py --requests 6
"""

from __future__ import annotations

import argparse
import asyncio
import os

from lemony_llm_provider import (
    CompletionRequest,
    EndpointSpec,
    LLMError,
    Message,
    Pool,
    resolve_quirks,
)

BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL = "z-ai/glm-5.3-flash"
BAD_KEY = "nvapi-invalid-key-for-failover-test"


def _keys() -> list[str]:
    raw = os.environ.get("NVIDIA_API_KEYS", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _request() -> CompletionRequest:
    return CompletionRequest(
        messages=(Message.user("只回复两个字: 收到"),),
        # 思考模型会先把预算花在思维链上, 给小了只剩 finish=length
        max_tokens=512,
    )


def _spec(key_id: str, key: str) -> EndpointSpec:
    return EndpointSpec(
        id=key_id,
        protocol="chat",
        base_url=BASE_URL,
        model=MODEL,
        api_key=key,
        quirks=resolve_quirks("generic"),
        max_concurrency=1,
        timeout=120.0,
    )


def _print_stats(pool: Pool) -> None:
    print("\n端点统计:")
    print(f"  {'id':10s} {'calls':>5s} {'fail':>5s} {'disabled':>8s} {'cooldown':>8s}")
    for stat in sorted(pool.stats(), key=lambda s: s.id):
        print(
            f"  {stat.id:10s} {stat.calls:5d} {stat.failures:5d} "
            f"{stat.disabled!s:>8s} {stat.cooldown_s:8.1f}"
        )


async def run(args: argparse.Namespace) -> int:
    keys = _keys()[: args.key_count] if args.key_count else _keys()
    if not keys:
        print("环境变量 NVIDIA_API_KEYS 没有设置")
        return 2

    specs = [_spec(f"nv-{index + 1}", key) for index, key in enumerate(keys)]
    if args.bad_first:
        specs.insert(0, _spec("nv-bad", BAD_KEY))

    pool = Pool(specs, {"glm": [spec.id for spec in specs]}, max_attempts=3)
    served: list[str] = []
    problems: list[str] = []
    try:
        for index in range(args.requests):
            try:
                result = await pool.complete(
                    _request(), alias="glm", session_id="lb-test"
                )
            except LLMError as exc:
                problems.append(f"第 {index + 1} 次失败 [{exc.kind}] {exc}")
                print(f"  #{index + 1} FAIL [{exc.kind}] {exc}")
                continue
            served.append(result.endpoint_id)
            usage = result.usage
            tokens = (
                f"in={usage.input_tokens} out={usage.output_tokens}"
                if usage
                else "usage=None"
            )
            print(
                f"  #{index + 1} -> {result.endpoint_id:8s} "
                f"finish={result.finish_reason:6s} {tokens}  text={result.text[:20]!r}"
            )
        stats = pool.stats()
        _print_stats(pool)
    finally:
        await pool.aclose()

    print()
    healthy = {spec.id for spec in specs if spec.id != "nv-bad"}
    covered = healthy & set(served)
    print(f"用到的健康端点: {sorted(covered)} / {sorted(healthy)}")
    if args.bad_first:
        bad = next((stat for stat in stats if stat.id == "nv-bad"), None)
        assert bad is not None
        if not bad.disabled:
            problems.append("坏 key 没有被禁用")
        elif bad.calls:
            problems.append(f"坏 key 被成功调用过 {bad.calls} 次")
    if args.requests >= len(healthy) and covered != healthy:
        problems.append("有健康端点一次都没被轮询到")
    if problems:
        print(f"\n{len(problems)} 项失败:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\n全部通过")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=6, help="总共发几次请求")
    parser.add_argument(
        "--key-count", type=int, default=0, help="只用前 N 个 key (0 表示全部)"
    )
    parser.add_argument(
        "--bad-first",
        action="store_true",
        help="在最前面插一个无效 key 的端点, 验证禁用与绕开",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
