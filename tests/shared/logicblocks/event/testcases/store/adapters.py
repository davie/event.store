import asyncio
import concurrent.futures
from abc import ABC, abstractmethod
from collections.abc import Sequence
from itertools import batched
from random import randint

import pytest
import structlog
from pytest_unordered import unordered

from logicblocks.event.store import conditions as writeconditions
from logicblocks.event.store import constraints
from logicblocks.event.store.adapters import (
    EventSerialisationGuarantee,
    EventStorageAdapter,
)
from logicblocks.event.store.conditions import NoCondition
from logicblocks.event.store.exceptions import UnmetWriteConditionError
from logicblocks.event.testing import NewEventBuilder, data
from logicblocks.event.testing.data import (
    random_event_category_name,
    random_event_stream_name,
)
from logicblocks.event.types import NewEvent, StoredEvent, identifier

logger = structlog.get_logger()


class ConcurrencyParameters:
    def __init__(self, *, concurrent_writes: int, repeats: int):
        self.concurrent_writes = concurrent_writes
        self.repeats = repeats


class Base(ABC):
    @abstractmethod
    def construct_storage_adapter(
        self,
        *,
        serialisation_guarantee: EventSerialisationGuarantee = EventSerialisationGuarantee.LOG,
    ) -> EventStorageAdapter:
        raise NotImplementedError()

    @abstractmethod
    async def clear_storage(self) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def retrieve_events(
        self,
        *,
        adapter: EventStorageAdapter,
        category: str | None = None,
        stream: str | None = None,
    ) -> Sequence[StoredEvent]:
        raise NotImplementedError()

    @property
    @abstractmethod
    def concurrency_parameters(self) -> ConcurrencyParameters:
        raise NotImplementedError()


class SaveCases(Base, ABC):
    async def test_stores_single_event_for_later_retrieval(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        new_event = NewEventBuilder().build()

        stored_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[new_event],
        )
        stored_event = stored_events[0]

        actual_events = await self.retrieve_events(adapter=adapter)
        expected_events = [
            StoredEvent(
                id=stored_event.id,
                name=new_event.name,
                category=event_category,
                stream=event_stream,
                position=0,
                sequence_number=stored_event.sequence_number,
                payload=new_event.payload,
                observed_at=new_event.observed_at,
                occurred_at=new_event.occurred_at,
            )
        ]

        assert actual_events == expected_events

    async def test_stores_multiple_events_in_same_stream(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        new_event_1 = NewEventBuilder().build()
        new_event_2 = NewEventBuilder().build()

        stored_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[new_event_1, new_event_2],
        )
        stored_event_1 = stored_events[0]
        stored_event_2 = stored_events[1]

        actual_events = await self.retrieve_events(adapter=adapter)
        expected_events = [
            StoredEvent(
                id=stored_event_1.id,
                name=new_event_1.name,
                category=event_category,
                stream=event_stream,
                position=0,
                sequence_number=stored_event_1.sequence_number,
                payload=new_event_1.payload,
                observed_at=new_event_1.observed_at,
                occurred_at=new_event_1.occurred_at,
            ),
            StoredEvent(
                id=stored_event_2.id,
                name=new_event_2.name,
                category=event_category,
                stream=event_stream,
                position=1,
                sequence_number=stored_event_2.sequence_number,
                payload=new_event_2.payload,
                observed_at=new_event_2.observed_at,
                occurred_at=new_event_2.occurred_at,
            ),
        ]

        assert actual_events == expected_events

    async def test_stores_multiple_events_in_sequential_saves(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        new_event_1 = NewEventBuilder().build()
        new_event_2 = NewEventBuilder().build()

        stored_events_1 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[new_event_1],
        )
        stored_event_1 = stored_events_1[0]

        stored_events_2 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[new_event_2],
        )
        stored_event_2 = stored_events_2[0]

        actual_events = await self.retrieve_events(adapter=adapter)
        expected_events = [
            StoredEvent(
                id=stored_event_1.id,
                name=new_event_1.name,
                category=event_category,
                stream=event_stream,
                position=0,
                sequence_number=stored_event_1.sequence_number,
                payload=new_event_1.payload,
                observed_at=new_event_1.observed_at,
                occurred_at=new_event_1.occurred_at,
            ),
            StoredEvent(
                id=stored_event_2.id,
                name=new_event_2.name,
                category=event_category,
                stream=event_stream,
                position=1,
                sequence_number=stored_event_2.sequence_number,
                payload=new_event_2.payload,
                observed_at=new_event_2.observed_at,
                occurred_at=new_event_2.occurred_at,
            ),
        ]

        assert actual_events == expected_events


class WriteConditionCases(Base, ABC):
    async def test_writes_if_empty_stream_condition_and_stream_empty(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        new_event = NewEventBuilder().build()

        stored_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[new_event],
            condition=writeconditions.stream_is_empty(),
        )
        stored_event = stored_events[0]

        actual_events = await self.retrieve_events(
            adapter=adapter, category=event_category, stream=event_stream
        )
        expected_events = [
            StoredEvent(
                id=stored_event.id,
                name=new_event.name,
                category=event_category,
                stream=event_stream,
                position=0,
                sequence_number=stored_event.sequence_number,
                payload=new_event.payload,
                observed_at=new_event.observed_at,
                occurred_at=new_event.occurred_at,
            )
        ]

        assert actual_events == expected_events

    async def test_writes_if_empty_stream_condition_and_category_not_empty(
        self,
    ):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        new_event_1 = NewEventBuilder().build()
        new_event_2 = NewEventBuilder().build()

        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_1
            ),
            events=[new_event_1],
        )

        stored_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_2
            ),
            events=[new_event_2],
            condition=writeconditions.stream_is_empty(),
        )
        stored_event = stored_events[0]

        actual_records = await self.retrieve_events(
            adapter=adapter, category=event_category, stream=event_stream_2
        )
        expected_records = [
            StoredEvent(
                id=stored_event.id,
                name=new_event_2.name,
                category=event_category,
                stream=event_stream_2,
                position=0,
                sequence_number=stored_event.sequence_number,
                payload=new_event_2.payload,
                observed_at=new_event_2.observed_at,
                occurred_at=new_event_2.occurred_at,
            )
        ]

        assert actual_records == expected_records

    async def test_writes_if_empty_stream_condition_and_log_not_empty(self):
        adapter = self.construct_storage_adapter()

        event_category_1 = random_event_category_name()
        event_category_2 = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        new_event_1 = NewEventBuilder().build()
        new_event_2 = NewEventBuilder().build()

        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream_1
            ),
            events=[new_event_1],
        )

        stored_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream_2
            ),
            events=[new_event_2],
            condition=writeconditions.stream_is_empty(),
        )
        stored_event = stored_events[0]

        actual_records = await self.retrieve_events(
            adapter=adapter, category=event_category_2, stream=event_stream_2
        )
        expected_records = [
            StoredEvent(
                id=stored_event.id,
                name=new_event_2.name,
                category=event_category_2,
                stream=event_stream_2,
                position=0,
                sequence_number=stored_event.sequence_number,
                payload=new_event_2.payload,
                observed_at=new_event_2.observed_at,
                occurred_at=new_event_2.occurred_at,
            )
        ]

        assert actual_records == expected_records

    async def test_raises_if_empty_stream_condition_and_stream_not_empty(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        with pytest.raises(UnmetWriteConditionError):
            await adapter.save(
                target=identifier.StreamIdentifier(
                    category=event_category, stream=event_stream
                ),
                events=[NewEventBuilder().build()],
                condition=writeconditions.stream_is_empty(),
            )

    async def test_writes_if_position_condition_and_correct_position(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        new_event_1 = NewEventBuilder().build()
        new_event_2 = NewEventBuilder().build()

        stored_events_1 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[new_event_1],
        )
        stored_event_1 = stored_events_1[0]

        stored_events_2 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[new_event_2],
            condition=writeconditions.position_is(0),
        )

        stored_event_2 = stored_events_2[0]

        actual_records = await self.retrieve_events(adapter=adapter)
        expected_records = [
            StoredEvent(
                id=stored_event_1.id,
                name=new_event_1.name,
                category=event_category,
                stream=event_stream,
                position=0,
                sequence_number=stored_event_1.sequence_number,
                payload=new_event_1.payload,
                observed_at=new_event_1.observed_at,
                occurred_at=new_event_1.occurred_at,
            ),
            StoredEvent(
                id=stored_event_2.id,
                name=new_event_2.name,
                category=event_category,
                stream=event_stream,
                position=1,
                sequence_number=stored_event_2.sequence_number,
                payload=new_event_2.payload,
                observed_at=new_event_2.observed_at,
                occurred_at=new_event_2.occurred_at,
            ),
        ]

        assert actual_records == expected_records

    async def test_raises_if_position_condition_and_less_than_expected(self):
        adapter = self.construct_storage_adapter()

        await adapter.save(
            target=identifier.StreamIdentifier(
                category=random_event_category_name(),
                stream=random_event_stream_name(),
            ),
            events=[NewEventBuilder().build()],
        )

        with pytest.raises(UnmetWriteConditionError):
            await adapter.save(
                target=identifier.StreamIdentifier(
                    category=random_event_category_name(),
                    stream=random_event_stream_name(),
                ),
                events=[NewEventBuilder().build()],
                condition=writeconditions.position_is(1),
            )

    async def test_raises_if_position_condition_and_greater_than_expected(
        self,
    ):
        adapter = self.construct_storage_adapter()

        await adapter.save(
            target=identifier.StreamIdentifier(
                category=random_event_category_name(),
                stream=random_event_stream_name(),
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )

        with pytest.raises(UnmetWriteConditionError):
            await adapter.save(
                target=identifier.StreamIdentifier(
                    category=random_event_category_name(),
                    stream=random_event_stream_name(),
                ),
                events=[NewEventBuilder().build()],
                condition=writeconditions.position_is(1),
            )

    async def test_raises_if_position_condition_and_stream_empty(self):
        adapter = self.construct_storage_adapter()

        with pytest.raises(UnmetWriteConditionError):
            await adapter.save(
                target=identifier.StreamIdentifier(
                    category=random_event_category_name(),
                    stream=random_event_stream_name(),
                ),
                events=[NewEventBuilder().build()],
                condition=writeconditions.position_is(0),
            )


class StorageAdapterSaveTask:
    def __init__(
        self,
        *,
        adapter: EventStorageAdapter,
        target: identifier.StreamIdentifier,
        events: Sequence[NewEvent],
        condition: writeconditions.WriteCondition = NoCondition,
    ):
        self.adapter = adapter
        self.target = target
        self.events = events
        self.condition = condition
        self.result: Sequence[StoredEvent] | None = None
        self.exception: BaseException | None = None

    async def execute(
        self,
    ) -> None:
        try:
            self.result = await self.adapter.save(
                target=self.target,
                events=self.events,
                condition=self.condition,
            )
            await asyncio.sleep(0)
        except BaseException as e:
            self.exception = e


# TODO: Work out how to make these tests reliable on all machines.
#       Since they test race conditions they aren't perfectly repeatable,
#       although the chosen concurrency and number of repeats means they are
#       _relatively_ reliable on at least Toby's machine.
#
#       Potentially through a combination of hooks and barriers, these could
#       be made more reliable still but it would potentially leak implementation
#       details.
class ThreadingConcurrencyCases(Base, ABC):
    async def test_simultaneous_checked_writes_to_empty_stream_from_different_threads_write_once(
        self,
    ):
        test_concurrency = self.concurrency_parameters.concurrent_writes
        test_repeats = self.concurrency_parameters.repeats

        test_results = []

        for _ in range(test_repeats):
            await self.clear_storage()

            adapter = self.construct_storage_adapter()

            event_category = random_event_category_name()
            event_stream = random_event_stream_name()

            target = identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            )

            tasks = [
                StorageAdapterSaveTask(
                    adapter=adapter,
                    target=target,
                    events=[
                        (
                            NewEventBuilder()
                            .with_name(f"event-1-for-thread-{thread_id}")
                            .build()
                        ),
                        (
                            NewEventBuilder()
                            .with_name(f"event-2-for-thread-{thread_id}")
                            .build()
                        ),
                    ],
                    condition=writeconditions.stream_is_empty(),
                )
                for thread_id in range(test_concurrency)
            ]

            with concurrent.futures.ThreadPoolExecutor() as executor:
                executor.map(lambda task: asyncio.run(task.execute()), tasks)

            failed_saves = [
                task.exception for task in tasks if task.exception is not None
            ]
            successful_saves = [
                task.result for task in tasks if task.result is not None
            ]

            is_single_successful_save = len(successful_saves) == 1
            is_all_others_failed_saves = (
                len(failed_saves) == test_concurrency - 1
            )
            is_correct_save_counts = (
                is_single_successful_save and is_all_others_failed_saves
            )

            actual_records = await self.retrieve_events(
                adapter=adapter, category=event_category, stream=event_stream
            )
            expected_records = None

            is_expected_events = False
            if is_correct_save_counts:
                expected_records = successful_saves[0]
                is_expected_events = actual_records == expected_records

            test_results.append(
                {
                    "passed": is_correct_save_counts and is_expected_events,
                    "successful_saves": len(successful_saves),
                    "failed_saves": len(failed_saves),
                    "actual_records": actual_records,
                    "expected_records": expected_records,
                }
            )

        failing_tests = [
            test_result
            for test_result in test_results
            if not test_result["passed"]
        ]

        assert len(failing_tests) == 0, (
            f"{len(failing_tests)} out of {test_repeats} failed: "
            f"{failing_tests}"
        )

    async def test_simultaneous_checked_writes_to_existing_stream_from_different_threads_write_once(
        self,
    ):
        test_concurrency = self.concurrency_parameters.concurrent_writes
        test_repeats = self.concurrency_parameters.repeats

        test_results = []

        for _ in range(test_repeats):
            await self.clear_storage()

            adapter = self.construct_storage_adapter()

            event_category = random_event_category_name()
            event_stream = random_event_stream_name()

            preexisting_events = await adapter.save(
                target=identifier.StreamIdentifier(
                    category=event_category, stream=event_stream
                ),
                events=[
                    (
                        NewEventBuilder()
                        .with_name("event-1-preexisting")
                        .build()
                    ),
                    (
                        NewEventBuilder()
                        .with_name("event-2-preexisting")
                        .build()
                    ),
                ],
            )

            target = identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            )

            tasks = [
                StorageAdapterSaveTask(
                    adapter=adapter,
                    target=target,
                    events=[
                        (
                            NewEventBuilder()
                            .with_name(f"event-1-for-thread-{thread_id}")
                            .build()
                        ),
                        (
                            NewEventBuilder()
                            .with_name(f"event-2-for-thread-{thread_id}")
                            .build()
                        ),
                    ],
                    condition=writeconditions.position_is(1),
                )
                for thread_id in range(test_concurrency)
            ]

            with concurrent.futures.ThreadPoolExecutor() as executor:
                executor.map(lambda task: asyncio.run(task.execute()), tasks)

            failed_saves = [
                task.exception for task in tasks if task.exception is not None
            ]
            successful_saves = [
                task.result for task in tasks if task.result is not None
            ]

            is_single_successful_save = len(successful_saves) == 1
            is_all_others_failed_saves = (
                len(failed_saves) == test_concurrency - 1
            )
            is_correct_save_counts = (
                is_single_successful_save and is_all_others_failed_saves
            )

            actual_records = await self.retrieve_events(
                adapter=adapter, category=event_category, stream=event_stream
            )
            expected_records = None

            is_expected_events = False
            if is_correct_save_counts:
                expected_records = list(preexisting_events) + list(
                    successful_saves[0]
                )
                is_expected_events = actual_records == expected_records

            test_results.append(
                {
                    "passed": is_correct_save_counts and is_expected_events,
                    "successful_saves": len(successful_saves),
                    "failed_saves": len(failed_saves),
                    "actual_records": actual_records,
                    "expected_records": expected_records,
                }
            )

        failing_tests = [
            test_result
            for test_result in test_results
            if not test_result["passed"]
        ]

        assert len(failing_tests) == 0, (
            f"{len(failing_tests)} out of {test_repeats} failed: "
            f"{failing_tests}"
        )

    async def test_simultaneous_unchecked_writes_from_different_threads_are_serialised(
        self,
    ):
        test_concurrency = self.concurrency_parameters.concurrent_writes
        test_repeats = self.concurrency_parameters.repeats

        test_results = []

        for _ in range(test_repeats):
            await self.clear_storage()

            adapter = self.construct_storage_adapter()

            event_category = random_event_category_name()
            event_stream = random_event_stream_name()

            event_writes = [
                [
                    NewEventBuilder()
                    .with_name(f"event-1-write-{write_id}")
                    .build(),
                    NewEventBuilder()
                    .with_name(f"event-2-write-{write_id}")
                    .build(),
                    NewEventBuilder()
                    .with_name(f"event-3-write-{write_id}")
                    .build(),
                ]
                for write_id in range(test_concurrency)
            ]

            target = identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            )

            tasks = [
                StorageAdapterSaveTask(
                    adapter=adapter, target=target, events=events
                )
                for events in event_writes
            ]

            with concurrent.futures.ThreadPoolExecutor() as executor:
                executor.map(lambda task: asyncio.run(task.execute()), tasks)

            actual_events = await self.retrieve_events(
                adapter=adapter,
                category=event_category,
                stream=event_stream,
            )
            actual_names = [event.name for event in actual_events]
            actual_name_groups = set(batched(actual_names, 3))
            expected_name_groups = {
                tuple(event.name for event in event_write)
                for event_write in event_writes
            }

            actual_positions = [event.position for event in actual_events]
            expected_positions = list(range(test_concurrency * 3))

            is_correct_event_count = len(actual_events) == test_concurrency * 3
            is_correct_event_sequencing = (
                actual_name_groups == expected_name_groups
            )
            is_correct_event_positioning = (
                actual_positions == expected_positions
            )

            test_results.append(
                {
                    "passed": (
                        is_correct_event_count
                        and is_correct_event_sequencing
                        and is_correct_event_positioning
                    ),
                    "actual_name_groups": actual_name_groups,
                    "expected_name_groups": expected_name_groups,
                    "actual_positions": actual_positions,
                    "expected_positions": expected_positions,
                }
            )

        failed_tests = [
            test_result
            for test_result in test_results
            if not test_result["passed"]
        ]

        assert len(failed_tests) == 0, (
            f"{len(failed_tests)} out of {test_repeats} failed: {failed_tests}"
        )


class SequenceReader:
    def __init__(
        self,
        adapter: EventStorageAdapter,
        category: str | None = None,
        stream: str | None = None,
    ):
        self.adapter = adapter
        self.running_event = asyncio.Event()
        self.shutdown_event = asyncio.Event()
        self.category = category
        self.stream = stream
        self.events: list[StoredEvent] = []
        self.exception: BaseException | None = None
        self.task: asyncio.Task[None] | None = None

    @property
    def failed(self) -> bool:
        return self.exception is not None

    @property
    def sequence_numbers(self) -> Sequence[int]:
        return [event.sequence_number for event in self.events]

    async def wait_until_running(self) -> None:
        while True:
            if self.running_event.is_set():
                return
            else:
                await asyncio.sleep(0)

    async def start(self) -> None:
        await logger.ainfo(
            "sequence.reader.starting",
            category=self.category,
            stream=self.stream,
        )
        self.task = asyncio.create_task(self.execute())
        await asyncio.wait_for(self.wait_until_running(), timeout=0.5)
        await logger.ainfo(
            "sequence.reader.started",
            category=self.category,
            stream=self.stream,
        )

    async def stop(self) -> None:
        await logger.ainfo(
            "sequence.reader.stopping",
            category=self.category,
            stream=self.stream,
        )
        if not self.shutdown_event.is_set():
            self.shutdown_event.set()
        if self.task is not None:
            await logger.ainfo(
                "sequence.reader.waiting-to-stop",
                category=self.category,
                stream=self.stream,
            )
            while not self.task.done():
                await asyncio.sleep(0)
        await logger.ainfo(
            "sequence.reader.stopped",
            category=self.category,
            stream=self.stream,
        )

    async def execute(self) -> None:
        try:
            last_sequence_number = -1
            shutdown_requested = False
            last_iteration_completed = False
            await logger.ainfo(
                "sequence.reader.running",
                category=self.category,
                stream=self.stream,
            )
            while True:
                new_events = [
                    event
                    async for event in self.adapter.scan(
                        target=identifier.target(
                            category=self.category, stream=self.stream
                        ),
                        constraints={
                            constraints.sequence_number_after(
                                last_sequence_number
                            )
                        },
                    )
                ]

                if len(new_events) > 0:
                    last_sequence_number = new_events[-1].sequence_number

                self.events.extend(new_events)

                if shutdown_requested:
                    last_iteration_completed = True

                if (
                    self.shutdown_event.is_set()
                    and last_iteration_completed is True
                ):
                    return

                elif self.shutdown_event.is_set():
                    shutdown_requested = True

                if not self.running_event.is_set():
                    self.running_event.set()

                await logger.ainfo(
                    "sequence.reader.polling",
                    category=self.category,
                    stream=self.stream,
                    event_count=len(self.events),
                )

                await asyncio.sleep(0)
        except asyncio.CancelledError:
            await logger.ainfo(
                "sequence.reader.cancelled",
                category=self.category,
                stream=self.stream,
            )
            raise
        except BaseException as e:
            await logger.aexception(
                "sequence.reader.errored",
                category=self.category,
                stream=self.stream,
            )
            self.exception = e


class SequenceWriter:
    def __init__(
        self,
        adapter: EventStorageAdapter,
        publish_count: int,
        category: str | None = None,
        stream: str | None = None,
    ):
        self.adapter = adapter
        self.publish_count = publish_count
        self.category = category
        self.stream = stream
        self.events: list[StoredEvent] = []
        self.exception: BaseException | None = None
        self.task: asyncio.Task[None] | None = None

    @property
    def failed(self) -> bool:
        return self.exception is not None

    @property
    def sequence_numbers(self) -> Sequence[int]:
        return [event.sequence_number for event in self.events]

    def resolve_category(self) -> str:
        return (
            self.category
            if self.category is not None
            else data.random_event_category_name()
        )

    def resolve_stream(self) -> str:
        return (
            self.stream
            if self.stream is not None
            else data.random_event_stream_name()
        )

    async def start(self) -> None:
        await logger.ainfo(
            "sequence.writer.starting",
            category=self.category,
            stream=self.stream,
        )
        self.task = asyncio.create_task(self.execute())

    async def complete(self) -> None:
        await logger.ainfo(
            "sequence.writer.completing",
            category=self.category,
            stream=self.stream,
        )
        if self.task is not None:
            while not self.task.done():
                await asyncio.sleep(0)
        await logger.ainfo(
            "sequence.writer.completed",
            category=self.category,
            stream=self.stream,
        )

    async def execute(self) -> None:
        try:
            await logger.ainfo(
                "sequence.writer.running",
                category=self.category,
                stream=self.stream,
            )
            for id in range(0, self.publish_count):
                event_count = randint(1, 10)
                await logger.ainfo(
                    "sequence.writer.publishing",
                    category=self.category,
                    stream=self.stream,
                    publish_id=id,
                    event_count=event_count,
                )
                await asyncio.sleep(0)
                self.events.extend(
                    await self.adapter.save(
                        target=identifier.StreamIdentifier(
                            category=self.resolve_category(),
                            stream=self.resolve_stream(),
                        ),
                        events=[
                            NewEventBuilder()
                            .with_name(f"event-{id}-{n}")
                            .build()
                            for n in range(0, event_count)
                        ],
                    )
                )
        except asyncio.CancelledError:
            await logger.ainfo(
                "sequence.writer.cancelled",
                category=self.category,
                stream=self.stream,
            )
            raise
        except BaseException as e:
            await logger.aexception(
                "sequence.writer.failed",
                category=self.category,
                stream=self.stream,
            )
            self.exception = e


class AsyncioConcurrencyCases(Base, ABC):
    async def test_simultaneous_checked_writes_to_empty_stream_from_different_async_tasks_write_once(
        self,
    ):
        adapter = self.construct_storage_adapter()

        simultaneous_write_count = 2

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        target = identifier.StreamIdentifier(
            category=event_category, stream=event_stream
        )

        tasks = [
            StorageAdapterSaveTask(
                adapter=adapter,
                target=target,
                events=[
                    (
                        NewEventBuilder()
                        .with_name(f"event-1-for-task-${task_id}")
                        .build()
                    ),
                    (
                        NewEventBuilder()
                        .with_name(f"event-2-for-task-${task_id}")
                        .build()
                    ),
                ],
                condition=writeconditions.stream_is_empty(),
            )
            for task_id in range(simultaneous_write_count)
        ]

        await asyncio.gather(
            *[task.execute() for task in tasks], return_exceptions=True
        )

        failed_saves = [
            task.exception for task in tasks if task.exception is not None
        ]
        successful_saves = [
            task.result for task in tasks if task.result is not None
        ]

        is_single_successful_save = len(successful_saves) == 1
        is_all_others_failed_saves = (
            len(failed_saves) == simultaneous_write_count - 1
        )
        is_correct_save_counts = (
            is_single_successful_save and is_all_others_failed_saves
        )

        assert is_correct_save_counts

        actual_records = await self.retrieve_events(
            adapter=adapter, category=event_category, stream=event_stream
        )
        expected_records = successful_saves[0]

        assert actual_records == expected_records

    async def test_simultaneous_checked_writes_to_existing_stream_from_different_async_tasks_write_once(
        self,
    ):
        adapter = self.construct_storage_adapter()

        simultaneous_write_count = 2

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        preexisting_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[
                (NewEventBuilder().with_name("event-1-preexisting").build()),
                (NewEventBuilder().with_name("event-2-preexisting").build()),
            ],
        )

        target = identifier.StreamIdentifier(
            category=event_category, stream=event_stream
        )

        tasks = [
            StorageAdapterSaveTask(
                adapter=adapter,
                target=target,
                events=[
                    (
                        NewEventBuilder()
                        .with_name(f"event-1-for-task-${task_id}")
                        .build()
                    ),
                    (
                        NewEventBuilder()
                        .with_name(f"event-2-for-task-${task_id}")
                        .build()
                    ),
                ],
                condition=writeconditions.position_is(1),
            )
            for task_id in range(simultaneous_write_count)
        ]

        await asyncio.gather(
            *[task.execute() for task in tasks], return_exceptions=True
        )

        failed_saves = [
            task.exception for task in tasks if task.exception is not None
        ]
        successful_saves = [
            task.result for task in tasks if task.result is not None
        ]

        is_single_successful_save = len(successful_saves) == 1
        is_all_others_failed_saves = (
            len(failed_saves) == simultaneous_write_count - 1
        )
        is_correct_save_counts = (
            is_single_successful_save and is_all_others_failed_saves
        )

        assert is_correct_save_counts

        actual_records = await self.retrieve_events(
            adapter=adapter, category=event_category, stream=event_stream
        )
        expected_records = list(preexisting_events) + list(successful_saves[0])

        assert actual_records == expected_records

    async def test_simultaneous_unchecked_writes_from_different_async_tasks_are_serialised(
        self,
    ):
        adapter = self.construct_storage_adapter()

        simultaneous_write_count = 2

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        event_writes = [
            [
                NewEventBuilder()
                .with_name(f"event-1-write-{write_id}")
                .build(),
                NewEventBuilder()
                .with_name(f"event-2-write-{write_id}")
                .build(),
                NewEventBuilder()
                .with_name(f"event-3-write-{write_id}")
                .build(),
            ]
            for write_id in range(simultaneous_write_count)
        ]

        target = identifier.StreamIdentifier(
            category=event_category, stream=event_stream
        )

        tasks = [
            StorageAdapterSaveTask(
                adapter=adapter, target=target, events=events
            )
            for events in event_writes
        ]

        await asyncio.gather(
            *[task.execute() for task in tasks], return_exceptions=True
        )

        actual_events = await self.retrieve_events(
            adapter=adapter,
            category=event_category,
            stream=event_stream,
        )
        actual_names = [event.name for event in actual_events]
        actual_name_groups = set(batched(actual_names, 3))
        expected_name_groups = {
            tuple(event.name for event in event_write)
            for event_write in event_writes
        }

        actual_positions = [event.position for event in actual_events]
        expected_positions = list(range(simultaneous_write_count * 3))

        is_correct_event_count = (
            len(actual_events) == simultaneous_write_count * 3
        )
        is_correct_event_sequencing = (
            actual_name_groups == expected_name_groups
        )
        is_correct_event_positioning = actual_positions == expected_positions

        assert is_correct_event_count
        assert is_correct_event_sequencing
        assert is_correct_event_positioning

    async def test_all_writes_are_serialised_as_seen_by_readers_when_log_level_serialisation_guarantee(
        self,
    ):
        adapter = self.construct_storage_adapter(
            serialisation_guarantee=EventSerialisationGuarantee.LOG
        )

        simultaneous_writer_count = 2
        publish_count = 10

        reader = SequenceReader(adapter)
        await reader.start()

        writers = [
            SequenceWriter(adapter, publish_count=publish_count)
            for _ in range(simultaneous_writer_count)
        ]
        await asyncio.gather(*[writer.start() for writer in writers])
        await asyncio.gather(*[writer.complete() for writer in writers])

        await reader.stop()

        assert not any(writer.failed for writer in writers)
        assert not reader.failed

        written_sequence_numbers = [
            sequence_number
            for writer in writers
            for sequence_number in writer.sequence_numbers
        ]

        def no_sequence_numbers_missed_across_log() -> bool:
            return reader.sequence_numbers == unordered(
                written_sequence_numbers
            )

        def log_reader_reads_log_serially() -> bool:
            return reader.sequence_numbers == sorted(reader.sequence_numbers)

        assert no_sequence_numbers_missed_across_log()
        assert log_reader_reads_log_serially()

    async def test_category_writes_are_serialised_as_seen_by_readers_when_category_level_serialisation_guarantee(
        self,
    ):
        adapter = self.construct_storage_adapter(
            serialisation_guarantee=EventSerialisationGuarantee.CATEGORY
        )

        simultaneous_writer_count = 2
        category_count = 2
        publish_count = 10

        log_reader = SequenceReader(adapter)
        await log_reader.start()

        categories = [
            data.random_event_category_name() for _ in range(category_count)
        ]

        category_readers = [
            SequenceReader(adapter, category=category)
            for category in categories
        ]

        await asyncio.gather(
            *[category_reader.start() for category_reader in category_readers]
        )

        category_writers = [
            SequenceWriter(
                adapter, category=category, publish_count=publish_count
            )
            for category in categories
            for _ in range(simultaneous_writer_count)
        ]
        await asyncio.gather(
            *[category_writer.start() for category_writer in category_writers]
        )
        await asyncio.gather(
            *[
                category_writer.complete()
                for category_writer in category_writers
            ]
        )

        await log_reader.stop()
        await asyncio.gather(
            *[category_reader.stop() for category_reader in category_readers]
        )

        assert not any(
            category_writer.failed for category_writer in category_writers
        )
        assert not any(
            category_reader.failed for category_reader in category_readers
        )
        assert not log_reader.failed

        all_written_sequence_numbers = [
            sequence_number
            for category_writer in category_writers
            for sequence_number in category_writer.sequence_numbers
        ]

        all_read_sequence_numbers = [
            sequence_number
            for category_reader in category_readers
            for sequence_number in category_reader.sequence_numbers
        ]

        def no_sequence_numbers_missed_across_categories() -> bool:
            return all_read_sequence_numbers == unordered(
                all_written_sequence_numbers
            )

        def category_reader_reads_category_serially(sequence_numbers) -> bool:
            return sequence_numbers == sorted(sequence_numbers)

        def log_reader_does_not_read_events_serially() -> bool:
            return log_reader.sequence_numbers != sorted(
                all_written_sequence_numbers
            )

        def log_reader_skips_events() -> bool:
            return log_reader.sequence_numbers != unordered(
                all_written_sequence_numbers
            )

        assert no_sequence_numbers_missed_across_categories()
        assert all(
            category_reader_reads_category_serially(
                category_reader.sequence_numbers
            )
            for category_reader in category_readers
        )
        assert log_reader_does_not_read_events_serially()
        assert log_reader_skips_events()

    async def test_stream_writes_are_serialised_as_seen_by_readers_when_stream_level_serialisation_guarantee(
        self,
    ):
        adapter = self.construct_storage_adapter(
            serialisation_guarantee=EventSerialisationGuarantee.STREAM
        )

        simultaneous_writer_count = 5
        category_count = 2
        stream_count = 2
        publish_count = 10

        log_reader = SequenceReader(adapter)
        await log_reader.start()

        categories = [
            data.random_event_category_name() for _ in range(category_count)
        ]
        streams = [
            (category, data.random_event_stream_name())
            for _ in range(stream_count)
            for category in categories
        ]

        category_readers = [
            SequenceReader(adapter, category=category)
            for category in categories
        ]
        stream_readers = [
            SequenceReader(adapter, category=category, stream=stream)
            for category, stream in streams
        ]

        await asyncio.gather(
            *[category_reader.start() for category_reader in category_readers]
        )
        await asyncio.gather(
            *[stream_reader.start() for stream_reader in stream_readers]
        )

        stream_writers = [
            SequenceWriter(
                adapter,
                category=category,
                stream=stream,
                publish_count=publish_count,
            )
            for category, stream in streams
            for _ in range(simultaneous_writer_count)
        ]
        await asyncio.gather(
            *[stream_writer.start() for stream_writer in stream_writers]
        )
        await asyncio.gather(
            *[stream_writer.complete() for stream_writer in stream_writers]
        )

        await log_reader.stop()
        await asyncio.gather(
            *[category_reader.stop() for category_reader in category_readers]
        )
        await asyncio.gather(
            *[stream_reader.stop() for stream_reader in stream_readers]
        )

        assert not any(
            stream_writer.failed for stream_writer in stream_writers
        )
        assert not any(
            category_reader.failed for category_reader in category_readers
        )
        assert not any(
            stream_reader.failed for stream_reader in stream_readers
        )
        assert not log_reader.failed

        all_written_sequence_numbers = [
            sequence_number
            for stream_writer in stream_writers
            for sequence_number in stream_writer.sequence_numbers
        ]

        all_read_sequence_numbers = [
            sequence_number
            for stream_reader in stream_readers
            for sequence_number in stream_reader.sequence_numbers
        ]

        def no_sequence_numbers_missed_across_streams() -> bool:
            return all_read_sequence_numbers == unordered(
                all_written_sequence_numbers
            )

        def stream_reader_reads_stream_serially(sequence_numbers) -> bool:
            return sequence_numbers == sorted(sequence_numbers)

        def reader_does_not_read_events_serially(reader) -> bool:
            return reader.sequence_numbers != sorted(
                all_written_sequence_numbers
            )

        def reader_skips_events(reader) -> bool:
            return reader.sequence_numbers != unordered(
                all_written_sequence_numbers
            )

        assert no_sequence_numbers_missed_across_streams()
        assert all(
            stream_reader_reads_stream_serially(stream_reader.sequence_numbers)
            for stream_reader in stream_readers
        )
        assert all(
            reader_does_not_read_events_serially(reader)
            for reader in category_readers + [log_reader]
        )
        assert all(
            reader_skips_events(reader)
            for reader in category_readers + [log_reader]
        )


class ScanCases(Base, ABC):
    async def test_log_scan_scans_no_events_when_store_empty(self):
        adapter = self.construct_storage_adapter()

        scanned_events = [
            event
            async for event in adapter.scan(target=identifier.LogIdentifier())
        ]

        assert scanned_events == []

    async def test_log_scan_scans_single_event_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        stored_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=random_event_category_name(),
                stream=random_event_stream_name(),
            ),
            events=[NewEventBuilder().build()],
        )

        scanned_events = [
            event
            async for event in adapter.scan(target=identifier.LogIdentifier())
        ]

        assert scanned_events == stored_events

    async def test_log_scan_scans_multiple_events_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        stored_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=random_event_category_name(),
                stream=random_event_stream_name(),
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )

        scanned_events = [
            event
            async for event in adapter.scan(target=identifier.LogIdentifier())
        ]

        assert scanned_events == stored_events

    async def test_log_scan_scans_events_across_streams_in_sequence_order(
        self,
    ):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        stored_events_1 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_2 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )
        stored_events_3 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_4 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = (
            list(stored_events_1)
            + list(stored_events_2)
            + list(stored_events_3)
            + list(stored_events_4)
        )
        scanned_events = [
            event
            async for event in adapter.scan(target=identifier.LogIdentifier())
        ]

        assert scanned_events == stored_events

    async def test_log_scan_scans_events_across_categories_in_sequence_order(
        self,
    ):
        adapter = self.construct_storage_adapter()

        event_category_1 = random_event_category_name()
        event_category_2 = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        stored_events_1 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_2 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )
        stored_events_3 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_4 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = (
            list(stored_events_1)
            + list(stored_events_2)
            + list(stored_events_3)
            + list(stored_events_4)
        )
        scanned_events = [
            event
            async for event in adapter.scan(target=identifier.LogIdentifier())
        ]

        assert scanned_events == stored_events

    async def test_log_scan_resumes_after_provided_sequence_number(self):
        adapter = self.construct_storage_adapter()

        event_category_1 = random_event_category_name()
        event_category_2 = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_2 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )
        stored_events_3 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_4 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )

        sequence_number = stored_events_2[0].sequence_number

        expected_events = list(stored_events_3) + list(stored_events_4)
        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.LogIdentifier(),
                constraints={
                    constraints.sequence_number_after(sequence_number)
                },
            )
        ]

        assert scanned_events == expected_events

    async def test_category_scan_scans_no_events_when_store_empty(self):
        adapter = self.construct_storage_adapter()

        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.CategoryIdentifier(
                    category=random_event_category_name()
                )
            )
        ]

        assert scanned_events == []

    async def test_category_scan_scans_no_events_when_category_empty(self):
        adapter = self.construct_storage_adapter()

        scan_event_category = random_event_category_name()
        other_event_category = random_event_category_name()

        await adapter.save(
            target=identifier.StreamIdentifier(
                category=other_event_category,
                stream=random_event_stream_name(),
            ),
            events=[NewEventBuilder().build()],
        )

        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.CategoryIdentifier(
                    category=scan_event_category
                )
            )
        ]

        assert scanned_events == []

    async def test_category_scan_scans_single_event_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.CategoryIdentifier(category=event_category)
            )
        ]

        assert scanned_events == stored_events

    async def test_category_scan_scans_multiple_events_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category,
                stream=event_stream,
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )

        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.CategoryIdentifier(category=event_category)
            )
        ]

        assert scanned_events == stored_events

    async def test_category_scan_scans_events_across_streams_in_sequence_order(
        self,
    ):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        stored_events_1 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_2 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )
        stored_events_3 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_4 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = (
            list(stored_events_1)
            + list(stored_events_2)
            + list(stored_events_3)
            + list(stored_events_4)
        )
        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.CategoryIdentifier(category=event_category)
            )
        ]

        assert scanned_events == stored_events

    async def test_category_scan_ignores_events_in_other_categories(self):
        adapter = self.construct_storage_adapter()

        event_category_1 = random_event_category_name()
        event_category_2 = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        stored_events_1 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_3 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )
        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = list(stored_events_1) + list(stored_events_3)
        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.CategoryIdentifier(category=event_category_1)
            )
        ]

        assert scanned_events == stored_events

    async def test_category_scan_resumes_after_provided_sequence_number(self):
        adapter = self.construct_storage_adapter()

        event_category_1 = random_event_category_name()
        event_category_2 = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        stored_events_1 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_3 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )
        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )

        sequence_number = stored_events_1[1].sequence_number

        expected_events = list(stored_events_3)
        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.CategoryIdentifier(
                    category=event_category_1
                ),
                constraints={
                    constraints.sequence_number_after(sequence_number)
                },
            )
        ]

        assert scanned_events == expected_events

    async def test_stream_scan_scans_no_events_when_store_empty(self):
        adapter = self.construct_storage_adapter()

        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.StreamIdentifier(
                    category=random_event_category_name(),
                    stream=random_event_stream_name(),
                )
            )
        ]

        assert scanned_events == []

    async def test_stream_scan_scans_no_events_when_stream_empty(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        scan_event_stream = random_event_stream_name()
        other_event_stream = random_event_stream_name()

        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=other_event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.StreamIdentifier(
                    category=event_category,
                    stream=scan_event_stream,
                )
            )
        ]

        assert scanned_events == []

    async def test_stream_scan_scans_single_event_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.StreamIdentifier(
                    category=event_category,
                    stream=event_stream,
                )
            )
        ]

        assert scanned_events == stored_events

    async def test_stream_scan_scans_multiple_events_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )

        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.StreamIdentifier(
                    category=event_category,
                    stream=event_stream,
                )
            )
        ]

        assert scanned_events == stored_events

    async def test_stream_scan_scans_events_within_stream_in_sequence_order(
        self,
    ):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events_1 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_2 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )
        stored_events_3 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_4 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = (
            list(stored_events_1)
            + list(stored_events_2)
            + list(stored_events_3)
            + list(stored_events_4)
        )
        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.StreamIdentifier(
                    category=event_category,
                    stream=event_stream,
                )
            )
        ]

        assert scanned_events == stored_events

    async def test_stream_scan_ignores_events_in_other_streams(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        stored_events_1 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_3 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )
        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = list(stored_events_1) + list(stored_events_3)
        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.StreamIdentifier(
                    category=event_category,
                    stream=event_stream_1,
                )
            )
        ]

        assert scanned_events == stored_events

    async def test_stream_scan_ignores_events_in_other_categories(self):
        adapter = self.construct_storage_adapter()

        event_category_1 = random_event_category_name()
        event_category_2 = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events_1 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_3 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )
        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = list(stored_events_1) + list(stored_events_3)
        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.StreamIdentifier(
                    category=event_category_1,
                    stream=event_stream,
                )
            )
        ]

        assert scanned_events == stored_events

    async def test_stream_scan_resumes_after_provided_sequence_number(self):
        adapter = self.construct_storage_adapter()

        event_category_1 = random_event_category_name()
        event_category_2 = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events_1 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_3 = await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_1, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )
        await adapter.save(
            target=identifier.StreamIdentifier(
                category=event_category_2, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        sequence_number = stored_events_1[1].sequence_number

        expected_events = list(stored_events_3)
        scanned_events = [
            event
            async for event in adapter.scan(
                target=identifier.StreamIdentifier(
                    category=event_category_1,
                    stream=event_stream,
                ),
                constraints={
                    constraints.sequence_number_after(sequence_number)
                },
            )
        ]

        assert scanned_events == expected_events


class LatestCases(Base, ABC):
    async def test_latest_returns_none_when_no_events_in_stream(self):
        adapter = self.construct_storage_adapter()

        latest_event = await adapter.latest(
            target=identifier.StreamIdentifier(
                category=random_event_category_name(),
                stream=random_event_stream_name(),
            )
        )

        assert latest_event is None

    async def test_latest_returns_latest_event_in_stream_when_available(self):
        adapter = self.construct_storage_adapter()

        category_name_1 = random_event_category_name()
        category_name_2 = random_event_category_name()
        stream_name_1 = random_event_stream_name()
        stream_name_2 = random_event_stream_name()
        stream_name_3 = random_event_stream_name()

        target_1 = identifier.StreamIdentifier(
            category=category_name_1, stream=stream_name_1
        )
        target_2 = identifier.StreamIdentifier(
            category=category_name_1, stream=stream_name_2
        )
        target_3 = identifier.StreamIdentifier(
            category=category_name_2, stream=stream_name_3
        )

        stored_events_1 = await adapter.save(
            target=target_1,
            events=[NewEventBuilder().build()],
        )

        await adapter.save(
            target=target_2,
            events=[NewEventBuilder().build()],
        )

        stored_events_2 = await adapter.save(
            target=target_1,
            events=[NewEventBuilder().build(), NewEventBuilder().build()],
        )

        await adapter.save(
            target=target_3,
            events=[NewEventBuilder().build()],
        )

        stream_events = [*stored_events_1, *stored_events_2]

        latest_event = await adapter.latest(
            target=identifier.StreamIdentifier(
                category=category_name_1,
                stream=stream_name_1,
            )
        )

        assert latest_event == stream_events[-1]

    async def test_latest_returns_none_when_no_events_in_category(self):
        adapter = self.construct_storage_adapter()

        latest_event = await adapter.latest(
            target=identifier.CategoryIdentifier(
                category=random_event_category_name(),
            )
        )

        assert latest_event is None

    async def test_latest_returns_latest_event_in_category_when_available(
        self,
    ):
        adapter = self.construct_storage_adapter()

        category_name_1 = random_event_category_name()
        category_name_2 = random_event_category_name()
        stream_name_1 = random_event_stream_name()
        stream_name_2 = random_event_stream_name()
        stream_name_3 = random_event_stream_name()

        target_1 = identifier.StreamIdentifier(
            category=category_name_1, stream=stream_name_1
        )
        target_2 = identifier.StreamIdentifier(
            category=category_name_2, stream=stream_name_2
        )
        target_3 = identifier.StreamIdentifier(
            category=category_name_1, stream=stream_name_3
        )

        stored_events_1 = await adapter.save(
            target=target_1,
            events=[NewEventBuilder().build()],
        )

        await adapter.save(
            target=target_2,
            events=[NewEventBuilder().build()],
        )

        stored_events_2 = await adapter.save(
            target=target_1,
            events=[NewEventBuilder().build(), NewEventBuilder().build()],
        )

        stored_events_3 = await adapter.save(
            target=target_3,
            events=[NewEventBuilder().build()],
        )

        await adapter.save(
            target=target_2,
            events=[NewEventBuilder().build()],
        )

        category_events = [
            *stored_events_1,
            *stored_events_2,
            *stored_events_3,
        ]

        latest_event = await adapter.latest(
            target=identifier.CategoryIdentifier(
                category=category_name_1,
            )
        )

        assert latest_event == category_events[-1]

    async def test_latest_returns_none_when_no_events_in_log(self):
        adapter = self.construct_storage_adapter()

        latest_event = await adapter.latest(target=identifier.LogIdentifier())

        assert latest_event is None

    async def test_latest_returns_latest_event_in_log_when_available(self):
        adapter = self.construct_storage_adapter()

        category_name_1 = random_event_category_name()
        category_name_2 = random_event_category_name()
        stream_name_1 = random_event_stream_name()
        stream_name_2 = random_event_stream_name()
        stream_name_3 = random_event_stream_name()

        target_1 = identifier.StreamIdentifier(
            category=category_name_1, stream=stream_name_1
        )
        target_2 = identifier.StreamIdentifier(
            category=category_name_2, stream=stream_name_2
        )
        target_3 = identifier.StreamIdentifier(
            category=category_name_1, stream=stream_name_3
        )

        stored_events_1 = await adapter.save(
            target=target_1,
            events=[NewEventBuilder().build(), NewEventBuilder().build()],
        )

        stored_events_2 = await adapter.save(
            target=target_3,
            events=[NewEventBuilder().build()],
        )

        stored_events_3 = await adapter.save(
            target=target_2,
            events=[NewEventBuilder().build()],
        )

        log_events = [*stored_events_1, *stored_events_2, *stored_events_3]

        latest_event = await adapter.latest(target=identifier.LogIdentifier())

        assert latest_event == log_events[-1]


class EventStorageAdapterCases(
    SaveCases,
    WriteConditionCases,
    ThreadingConcurrencyCases,
    AsyncioConcurrencyCases,
    ScanCases,
    LatestCases,
    ABC,
):
    pass
