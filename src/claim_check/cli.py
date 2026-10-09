"""Command line: the Stop hook for Claude Code, and a manual check of any transcript."""

import argparse
import json
import os
import sys
import traceback

from . import claims, report, transcript


def check(message, transcript_path, cwd=None):
    """Report lines for the claims in message, judged against the transcript."""
    found = claims.find(message)
    if not found:
        return []
    return report.lines(found, transcript.read(transcript_path, cwd), cwd)


def on_stop(payload):
    """Report on the final message's claims; never blocks."""
    path = payload.get("transcript_path")
    if not path or not os.path.isfile(path):
        return None
    message = payload.get("last_assistant_message")
    if message is None:
        message = transcript.last_message(path)
    found = check(message, path, payload.get("cwd"))
    return {"systemMessage": "\n".join(found)} if found else None


def _hook(event):
    try:
        result = {"stop": on_stop}[event](json.loads(sys.stdin.read()))
    except Exception:
        # Never fail silently: the user sees the crash.
        detail = traceback.format_exc(limit=3).strip().splitlines()[-1]
        result = {"systemMessage": f"claim-check internal error ({event}): {detail}"}
    if result:
        print(json.dumps(result, ensure_ascii=False))
    return 0


def _check(args):
    message = args.message if args.message is not None else transcript.last_message(args.transcript)
    found = check(message, args.transcript, args.cwd)
    print("\n".join(found) if found else "claim-check: no test, build or lint claims in the message")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="claim-check", description="Check an agent's success claims against what actually ran.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    hook = sub.add_parser("hook", help="entry point for Claude Code hooks")
    hook.add_argument("event", choices=["stop"])
    chk = sub.add_parser("check", help="check the last message of a transcript (or --message) against that transcript")
    chk.add_argument("transcript", help="path to a session .jsonl")
    chk.add_argument("--message", help="text to check instead of the transcript's last agent message")
    chk.add_argument("--cwd", help="project directory; edits outside it are ignored")
    args = parser.parse_args(argv)
    if args.cmd == "hook":
        return _hook(args.event)
    return _check(args)
