from typing import Any, Sequence, TypeGuard

from psycopg.types.json import Jsonb

from logicblocks.event import query as genericquery
from logicblocks.event.persistence.postgres import query as postgresquery


def expression_for_path(
    path: genericquery.Path,
    operator: postgresquery.Operator | None = None,
    value: str | int | float | bool | None = None,
    for_function: bool = False,
) -> postgresquery.Expression:
    if path.is_nested():
        if for_function:
            text_extract = False
            cast_type = None
        elif operator and operator.extraction_type == postgresquery.ExtractionType.JSONB:
            text_extract = False
            cast_type = None
        else:
            text_extract = True

            cast_type = None
            if value is not None:
                if isinstance(value, bool):
                    cast_type = "boolean"
                elif isinstance(value, int | float):
                    cast_type = "numeric"

        return postgresquery.JsonPathExpression(
            column=path.top_level,
            path=list(path.sub_levels),
            text_extract=text_extract,
            cast_type=cast_type,
        )
    else:
        return postgresquery.ColumnReference(field=path.top_level)


def expression_for_function(
    function: genericquery.Function,
) -> postgresquery.Expression:
    return postgresquery.ColumnReference(field=function.alias)


def expression_for_field(
    field: genericquery.Path | genericquery.Function,
    operator: postgresquery.Operator | None = None,
) -> postgresquery.Expression:
    match field:
        case genericquery.Path():
            return expression_for_path(field, operator=operator)
        case genericquery.Function():
            return expression_for_function(field)
        case _:  # pragma: no cover
            raise ValueError(f"Unsupported field type: {type(field)}")


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
