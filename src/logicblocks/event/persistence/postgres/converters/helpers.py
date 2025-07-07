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
        # Choose between JSON extraction (->) and text extraction (->>)
        # based on the context and operator type
        if for_function:
            # Functions need JSON extraction without text extraction
            # because they handle their own casting
            text_extract = False
            cast_type = None
        elif operator == postgresquery.Operator.CONTAINS:
            # CONTAINS operations need JSON extraction to compare JSON values
            text_extract = False
            cast_type = None
        else:
            # Most operations use text extraction for cleaner comparisons
            text_extract = True

            # Determine cast type based on value type for text extraction
            cast_type = None
            if value is not None:
                if isinstance(value, bool):
                    cast_type = "boolean"
                elif isinstance(value, int):
                    cast_type = "integer"
                elif isinstance(value, float):
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
            # CONTAINS operations need JSON values for comparison
            return postgresquery.Constant(Jsonb(value))
        else:
            # Most operations use text extraction, so values can be used directly
            return postgresquery.Constant(value)
    else:
        return postgresquery.Constant(value)


def is_multi_valued(value: Any) -> TypeGuard[Sequence[Any]]:
    return (
        not isinstance(value, str)
        and not isinstance(value, bytes)
        and isinstance(value, Sequence)
    )
