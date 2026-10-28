"""SQL validation using the sqlglot AST (never regex)."""

from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError


class SqlValidationError(ValueError):
    pass


_FORBIDDEN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Grant,
    exp.Copy,
    exp.Merge,
    exp.Into,
    exp.Lock,
)


@dataclass(frozen=True)
class ValidatedSql:
    sql: str
    statement: exp.Expression


def validate_sql(sql: str, max_length: int) -> ValidatedSql:
    if len(sql) > max_length:
        raise SqlValidationError(
            f"Query is longer than the {max_length} character limit."
        )

    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise SqlValidationError("Query is empty.")

    try:
        statements = parse(stripped, read="postgres")
    except ParseError as exc:
        raise SqlValidationError("Query could not be parsed as PostgreSQL.") from exc

    if len(statements) != 1 or statements[0] is None:
        raise SqlValidationError("Exactly one SQL statement is required.")

    statement = statements[0]
    if statement.find(*_FORBIDDEN) is not None:
        raise SqlValidationError("Only read-only SELECT statements are allowed.")
    if statement.find(exp.Select) is None:
        raise SqlValidationError("Only read-only SELECT statements are allowed.")

    return ValidatedSql(sql=stripped, statement=statement)
