from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, final

from logicblocks.event.store.exceptions import UnmetWriteConditionError
from logicblocks.event.types import StoredEvent


class WriteCondition(ABC):
    @abstractmethod
    def assert_met_by(self, *, last_event: StoredEvent | None) -> None:
        raise NotImplementedError()

    @abstractmethod
    def __eq__(self, other: object) -> bool:
        raise NotImplementedError()

    @abstractmethod
    def __hash__(self) -> int:
        raise NotImplementedError()

    def __and__(self, other: "WriteCondition") -> "WriteCondition":
        match self, other:
            case WriteConditions(
                conditions=self_conditions, combinator="and"
            ), WriteConditions(conditions=other_conditions, combinator="and"):
                return WriteConditions(
                    conditions={*self_conditions, *other_conditions},
                    combinator="and",
                )

            case WriteConditions(
                conditions=self_conditions, combinator="and"
            ), _:
                return WriteConditions(
                    conditions={*self_conditions, other}, combinator="and"
                )

            case _, WriteConditions(
                conditions=other_conditions, combinator="and"
            ):
                return WriteConditions(
                    conditions={self, *other_conditions}, combinator="and"
                )

            case _, _:
                return WriteConditions(
                    conditions={self, other}, combinator="and"
                )

    def __or__(self, other: "WriteCondition") -> "WriteCondition":
        match self, other:
            case WriteConditions(
                conditions=self_conditions, combinator="or"
            ), WriteConditions(conditions=other_conditions, combinator="or"):
                return WriteConditions(
                    conditions={*self_conditions, *other_conditions},
                    combinator="or",
                )

            case WriteConditions(
                conditions=self_conditions, combinator="or"
            ), _:
                return WriteConditions(
                    conditions={*self_conditions, other}, combinator="or"
                )

            case _, WriteConditions(
                conditions=other_conditions, combinator="or"
            ):
                return WriteConditions(
                    conditions={self, *other_conditions}, combinator="or"
                )

            case _, _:
                return WriteConditions(
                    conditions={self, other}, combinator="or"
                )


@final
@dataclass(frozen=True)
class WriteConditions(WriteCondition):
    conditions: set[WriteCondition] = field()
    combinator: Literal["and", "or"]

    def assert_met_by(self, *, last_event: StoredEvent | None) -> None:
        match self.combinator:
            case "and":
                for condition in self.conditions:
                    condition.assert_met_by(last_event=last_event)
            case "or":
                first_exception = None
                for condition in self.conditions:
                    try:
                        condition.assert_met_by(last_event=last_event)
                        return
                    except UnmetWriteConditionError as e:
                        first_exception = e
                if first_exception is not None:
                    raise first_exception
            case _:
                raise NotImplementedError()


@dataclass(frozen=True)
class PositionIsCondition(WriteCondition):
    position: int

    def assert_met_by(self, *, last_event: StoredEvent | None):
        if last_event is None or last_event.position != self.position:
            raise UnmetWriteConditionError("unexpected stream position")

    def __eq__(self, other: object):
        if not isinstance(other, PositionIsCondition):
            return False
        return self.position == other.position


@dataclass(frozen=True)
class EmptyStreamCondition(WriteCondition):
    def assert_met_by(self, *, last_event: StoredEvent | None):
        if last_event is not None:
            raise UnmetWriteConditionError("stream is not empty")

    def __eq__(self, other: object):
        return isinstance(other, EmptyStreamCondition)


def position_is(position: int) -> WriteCondition:
    return PositionIsCondition(position=position)


def stream_is_empty() -> WriteCondition:
    return EmptyStreamCondition()
