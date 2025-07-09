from typing import Any, Sequence, TypeGuard

from psycopg.types.json import Jsonb

from logicblocks.event import query as genericquery
from logicblocks.event.persistence.postgres import query as postgresquery


def _infer_cast_type(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "boolean"
    elif isinstance(value, int | float):
        return "numeric"
    return None


def expression_for_filter(
    path: genericquery.Path,
    operator: postgresquery.Operator,
    value: str | int | float | bool | None = None,
) -> postgresquery.Expression:
    if not path.is_nested():
        return postgresquery.ColumnReference(field=path.top_level)

    if operator.extraction_type == postgresquery.ExtractionType.JSONB:
        return postgresquery.JsonPathExpression(
            column=path.top_level,
            path=list(path.sub_levels),
            text_extract=False,
            cast_type=None,
        )

    cast_type = _infer_cast_type(value)
    return postgresquery.JsonPathExpression(
        column=path.top_level,
        path=list(path.sub_levels),
        text_extract=True,
        cast_type=cast_type,
    )


def expression_for_sort(path: genericquery.Path) -> postgresquery.Expression:
    if not path.is_nested():
        return postgresquery.ColumnReference(field=path.top_level)

    return postgresquery.JsonPathExpression(
        column=path.top_level,
        path=list(path.sub_levels),
        text_extract=True,
        cast_type=None,
    )


def expression_for_function_path(
    path: genericquery.Path,
) -> postgresquery.Expression:
    if not path.is_nested():
        return postgresquery.ColumnReference(field=path.top_level)

    return postgresquery.JsonPathExpression(
        column=path.top_level,
        path=list(path.sub_levels),
        text_extract=False,
        cast_type=None,
    )


def expression_for_function(
    function: genericquery.Function,
) -> postgresquery.Expression:
    return postgresquery.ColumnReference(field=function.alias)


def value_for_path(
    value: Any, path: genericquery.Path, operator: postgresquery.Operator
) -> postgresquery.Expression:
    if path == genericquery.Path("source"):
        return postgresquery.Constant(
            Jsonb(value.serialise()),
        )
    elif path.is_nested():
        if operator == postgresquery.Operator.CONTAINS:
            return postgresquery.Constant(Jsonb(value))
        else:
            return postgresquery.Constant(value)
    else:
        return postgresquery.Constant(value)


def is_multi_valued(value: Any) -> TypeGuard[Sequence[Any]]:
    return (
        not isinstance(value, str)
        and not isinstance(value, bytes)
        and isinstance(value, Sequence)
    )
