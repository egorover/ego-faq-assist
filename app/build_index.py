import argparse
import json

from app.config import Settings
from app.index_manager import (
    BuildReport,
    IndexOperationError,
    build_index,
    get_active_version,
    rollback_index,
    validate_source,
)


def _print_report(report: BuildReport | dict[str, object]) -> None:
    payload = report.as_dict() if isinstance(report, BuildReport) else report
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate, build, activate, or roll back FAQ indexes.")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--source", choices=("demo", "real"), help="Build and activate this source.")
    operation.add_argument("--validate", choices=("demo", "real"), help="Validate a source without embeddings.")
    operation.add_argument("--rollback", action="store_true", help="Activate the previous valid index.")
    args = parser.parse_args()
    settings = Settings.from_env()

    if args.validate:
        try:
            report = validate_source(settings, args.validate)
            report.active_version_before = get_active_version(settings)
            report.active_version_after = report.active_version_before
            _print_report(report)
        except IndexOperationError as exc:
            _print_report(exc.report or {
                "selected_source": args.validate,
                "error_stage": exc.stage,
                "error_type": exc.cause_type,
            })
            raise SystemExit(1) from None
        return

    if args.rollback:
        try:
            before = get_active_version(settings)
            after = rollback_index(settings)
            _print_report({
                "selected_source": "rollback",
                "active_version_before": before,
                "active_version_after": after,
                "activation_succeeded": True,
            })
        except Exception as exc:
            _print_report({
                "selected_source": "rollback",
                "error_stage": "rollback",
                "error_type": type(exc).__name__,
            })
            raise SystemExit(1) from None
        return

    try:
        _print_report(build_index(settings, args.source))
    except IndexOperationError as exc:
        _print_report(exc.report or {
            "selected_source": args.source,
            "error_stage": exc.stage,
            "error_type": exc.cause_type,
        })
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
