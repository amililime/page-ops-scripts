"""
post_batch.py  —  Phase 1 batch runner
Publishes posts to multiple Facebook Page profiles concurrently,
capped at --workers simultaneous Chrome instances (default: 2).

Usage:
    python post_batch.py --posts posts.txt
    python post_batch.py --posts posts.txt --workers 2
    python post_batch.py --posts posts.txt --profiles EMI_AUTO_2,EMI_AUTO_3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env"


def _load_dotenv():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip()


def _preflight_stop(profiles: list[str]) -> None:
    """Stop all target profiles before launching to ensure clean state."""
    import json as _json
    from mlx_context import _client
    from multilogin_client import MultiloginError
    profiles_file = ROOT / "mlx_profiles.json"
    profile_map = _json.loads(profiles_file.read_text())
    client = _client()
    for name in profiles:
        pid = profile_map.get(name)
        if not pid:
            continue
        try:
            client.stop_profile(pid)
            print(f"  Stopped {name}")
        except MultiloginError:
            pass
        except Exception:
            pass


async def run_profile(
    profile_name: str,
    semaphore: asyncio.Semaphore,
    posts_path: str,
    min_delay: int,
    max_delay: int,
    results: dict,
):
    tag = f"[{profile_name}]"

    async with semaphore:
        jitter = random.uniform(5, 20)
        print(f"{tag} Waiting {jitter:.1f}s before launch (anti-detection stagger)...")
        await asyncio.sleep(jitter)

        try:
            print(f"{tag} Starting...")
            from post import run as post_run
            await asyncio.to_thread(post_run, profile_name, posts_path, min_delay, max_delay)
            results[profile_name] = "success"
            print(f"{tag} Done.")
        except Exception as exc:
            results[profile_name] = f"error: {exc}"
            print(f"{tag} Failed: {exc}")


async def main_async(profiles: list[str], workers: int, posts_path: str, min_delay: int, max_delay: int):
    semaphore = asyncio.Semaphore(workers)
    results: dict[str, str] = {}

    tasks = [
        run_profile(name, semaphore, posts_path, min_delay, max_delay, results)
        for name in profiles
    ]

    print(f"\nPosting to {len(profiles)} profile(s) — {workers} worker(s) max\n")
    await asyncio.gather(*tasks, return_exceptions=True)

    print("\n" + "=" * 54)
    print("  Results")
    print("=" * 54)
    ok   = [n for n, r in results.items() if r == "success"]
    fail = [(n, r) for n, r in results.items() if r != "success"]
    for name in ok:
        print(f"  OK   {name}")
    for name, reason in fail:
        print(f"  FAIL {name}: {reason}")
    print("=" * 54)
    print(f"  {len(ok)} succeeded, {len(fail)} failed")
    print("=" * 54)


def main():
    _load_dotenv()

    profiles_file = ROOT / "mlx_profiles.json"
    if not profiles_file.exists():
        print("Error: mlx_profiles.json not found. Run sync_profiles.py first.")
        sys.exit(1)

    all_profiles = list(json.loads(profiles_file.read_text()).keys())

    parser = argparse.ArgumentParser(description="Batch publisher — post to multiple profiles.")
    parser.add_argument("--posts",    required=True,  help="Path to posts.txt")
    parser.add_argument("--workers",  type=int, default=2,
                        help="Max simultaneous Chrome instances (default: 2)")
    parser.add_argument("--profiles",  type=str, default=None,
                        help="Comma-separated profile names (default: all in mlx_profiles.json)")
    parser.add_argument("--min-delay", type=int, default=45,
                        help="Min seconds between posts (default: 45)")
    parser.add_argument("--max-delay", type=int, default=90,
                        help="Max seconds between posts (default: 90)")
    args = parser.parse_args()

    if not Path(args.posts).exists():
        print(f"Error: posts file not found: {args.posts}")
        sys.exit(1)

    if args.profiles:
        profiles = [p.strip() for p in args.profiles.split(",")]
        unknown = [p for p in profiles if p not in all_profiles]
        if unknown:
            print(f"Error: Unknown profile(s): {', '.join(unknown)}")
            sys.exit(1)
    else:
        profiles = all_profiles

    if not profiles:
        print("No profiles to run.")
        sys.exit(0)

    print("=" * 54)
    print("   Facebook Page Publisher — Batch Mode")
    print("=" * 54)
    print(f"  Profiles : {', '.join(profiles)}")
    print(f"  Workers  : {args.workers}")
    print(f"  Posts    : {args.posts}")
    print(f"  Delay    : {args.min_delay}–{args.max_delay}s between posts")

    print("\nStopping any running profiles before launch...")
    _preflight_stop(profiles)

    try:
        asyncio.run(main_async(profiles, args.workers, args.posts, args.min_delay, args.max_delay))
    except KeyboardInterrupt:
        print("\nCancelled.")


if __name__ == "__main__":
    main()
