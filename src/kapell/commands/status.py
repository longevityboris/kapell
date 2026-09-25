"""kapell status: where the project stands and what to run next, in under 2k tokens (C section 3)."""
from ..status import summarise

SPEC = {
    "name": "status",
    "effect": "read",
    "help": "phase, sections done/open, last check totals, quotas, layouts, renders, next command",
    "runtime_s": 0.6,
    "output_tokens_typ": 450,
    "examples": [["status"], ["status", "--no-check"]],
}


def add_arguments(parser):
    parser.add_argument("--no-check", action="store_true",
                        help="skip the live check and suspension count (faster; last_check is null)")


def run(args, ctx):
    data = summarise(ctx.root, ctx.cfg, live=not args.no_check, cfg_error=getattr(ctx, "cfg_error", None))
    if ctx.root is None:
        from . import Result
        return Result("no_results", data)
    return data
